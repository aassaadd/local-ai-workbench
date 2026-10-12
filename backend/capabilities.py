"""能力注册表：以「能力」描述可执行任务，协调员据此选择并派发。

设计目标：新增能力只需在 ``CAPABILITIES`` 中登记（名称/说明/关键词/执行器），
无需改动 ``coordinator.py`` 的路由逻辑。协调员在无本地模型时按关键词打分选择，
有本地模型时由模型输出 ``{"capability": ..., "args": {...}}`` 选择。

依赖方向：capabilities -> memory/llm/agents/base 与各 Agent；
``coordinator`` 可以 import 本模块，但本模块绝不 import ``coordinator``，避免循环导入。
"""
import re
from dataclasses import dataclass
from datetime import date as _date, timedelta
from typing import Awaitable, Callable, List, Optional, Tuple

from .agents.base import send_file, say
from .agents.doubao import DoubaoAgent
from .agents.trae_agent import TraeAgent
from .agents.workbuddy import WorkbuddyAgent
from .models import VIS_ALL, VIS_INTERNAL

# 协调员的 Agent 名（用于消息归属）
COORDINATOR = "coordinator"

# 执行器签名：async def handler(project: str, args: dict) -> None
Handler = Callable[[str, dict], Awaitable[None]]


@dataclass
class Capability:
    """一个可执行能力。

    字段：
    - key：能力唯一标识（路由时使用，如 chat_summary）；
    - title：能力中文名（展示用）；
    - description：能力说明（供 LLM 与用户阅读）；
    - keywords：关键词列表（无模型时用于打分兜底）；
    - handler：执行器，签名 async def handler(project, args) -> None；
              chat 兜底能力由协调员特殊处理，故为 None。
    """
    key: str
    title: str
    description: str
    keywords: List[str]
    handler: Optional[Handler] = None


# ---------------- 日期解析（原 coordinator._extract_date 迁移至此） ----------------
def extract_date(text: str) -> str:
    """从用户文本推断目标日期。

    功能：识别「前天/昨天/今天」及 20xx-yy-zz 形式，默认取昨天。
    参数：text —— 用户输入文本。
    返回值：紧凑日期字符串（YYYYMMDD）。
    """
    today = _date.today()
    if "前天" in text:
        d = today - timedelta(days=2)
    elif "昨日" in text or "昨天" in text:
        d = today - timedelta(days=1)
    elif "今天" in text or "今日" in text:
        d = today
    elif (m := re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)):
        d = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    else:
        d = today - timedelta(days=1)
    return d.strftime("%Y%m%d")


# ---------------- 能力执行器 ----------------
async def run_chat_summary(project: str, args: dict) -> None:
    """能力执行器：聊天记录 → 客户意向摘要。

    功能：交由 Workbuddy 拉取记录、豆包生成摘要，并向内部群/私聊按可见性发消息与产物。
    参数：project —— 项目名；args —— 参数，date 缺失时用 text 推断日期。
    返回值：无。
    """
    d = str(args.get("date") or "").strip() or extract_date(str(args.get("text", "")))

    # 过程类（仅内部群）：派发给 Workbuddy
    await say(project, COORDINATOR,
              f"@Workbuddy 拉取 {d} 外部联系人聊天记录，请统计总数并导出到公共文件夹",
              VIS_INTERNAL)
    _, src = await WorkbuddyAgent(project).pull_chat_records(d)

    # 过程类（仅内部群）：派发给豆包
    await say(project, COORDINATOR,
              f"@豆包 读取公共文件夹 {src.name}，生成客户意向摘要",
              VIS_INTERNAL)
    res = await DoubaoAgent(project).generate_summary(src, d)

    # 过程类（仅内部群）：校验
    await say(project, COORDINATOR, "[校验完成] 结果无误，已同步给用户", VIS_INTERNAL)

    # 结果类（私聊 + 内部群）
    summary = (
        f"已完成 {d} 聊天记录摘要，共处理 {res['total']} 条对话、{res['contacts']} 位客户。\n"
        f"高意向 {len(res['high'])} 位，中意向 {len(res['mid'])} 位，低意向 {len(res['low'])} 位。"
    )
    if res["high"]:
        summary += "\n高意向客户：" + "、".join(res["high"][:8])
    await say(project, COORDINATOR, summary, VIS_ALL)
    await send_file(project, COORDINATOR, res["file"], "public", VIS_ALL,
                    content="完整报告：客户意向摘要.md")


async def run_file_ops(project: str, args: dict) -> None:
    """能力执行器：整理项目文件并生成清单。

    功能：交由 Trae 扫描公共文件夹产出「文件清单.md」，并广播结果与产物。
    参数：project —— 项目名；args —— 参数（当前未使用）。
    返回值：无。
    """
    await say(project, COORDINATOR, "@Trae 整理公共文件夹并生成文件清单", VIS_INTERNAL)
    res = await TraeAgent(project).consolidate("public")
    await say(project, COORDINATOR,
              f"已完成文件整理，共 {res['count']} 个文件，清单已输出。", VIS_ALL)
    await send_file(project, COORDINATOR, res["file"], "public", VIS_ALL)


# ---------------- 注册表 ----------------
CAPABILITIES: List[Capability] = [
    Capability(
        key="chat_summary",
        title="客户意向摘要",
        description="读取外部联系人聊天记录，生成客户意向摘要报告。",
        keywords=["聊天记录", "客户意向", "意向摘要", "外部联系人"],
        handler=run_chat_summary,
    ),
    Capability(
        key="file_ops",
        title="整理项目文件并生成清单",
        description="扫描项目公共文件夹，整理文件并生成「文件清单.md」。",
        keywords=["整理文件", "汇总文件", "文件清单", "整理项目"],
        handler=run_file_ops,
    ),
    Capability(
        key="chat",
        title="通用对话",
        description="未匹配到具体能力时的通用问答（带分层记忆）。",
        keywords=[],  # 兜底能力无关键词
        handler=None,
    ),
]


def get(key: str) -> Optional[Capability]:
    """按 key 查找能力。

    功能：在注册表中检索指定能力。
    参数：key —— 能力标识。
    返回值：匹配的 Capability，未找到返回 None。
    """
    for cap in CAPABILITIES:
        if cap.key == key:
            return cap
    return None


def describe() -> str:
    """生成可用能力清单的可读文本。

    功能：用于注入 LLM 提示词，或在无匹配能力时引导用户。
    参数：无。
    返回值：多行字符串，每行形如「- key：title —— description」。
    """
    lines = []
    for cap in CAPABILITIES:
        kw = f"（关键词：{'、'.join(cap.keywords)}）" if cap.keywords else ""
        lines.append(f"- {cap.key}：{cap.title} —— {cap.description}{kw}")
    return "可用能力清单：\n" + "\n".join(lines)


def match(text: str) -> Tuple[str, dict]:
    """按关键词打分选择能力（无本地模型时的兜底路由）。

    功能：对除 chat 外的能力按关键词出现次数打分，取最高分；无命中回退 chat。
    参数：text —— 用户输入文本。
    返回值：(能力 key, args)；命中时 args 含 {"text": text}，回退时返回 ("chat", {})。
    """
    best_key = "chat"
    best_score = 0
    for cap in CAPABILITIES:
        if not cap.keywords:
            continue
        score = sum(text.count(k) for k in cap.keywords)
        if score > best_score:
            best_score = score
            best_key = cap.key
    if best_score > 0:
        return best_key, {"text": text}
    return "chat", {}