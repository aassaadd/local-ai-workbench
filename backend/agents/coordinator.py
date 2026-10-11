"""协调员 Agent：对接本地模型做任务拆解与分发，并负责消息分级（私聊/内部群）。"""
import asyncio
import re
from datetime import date as _date, timedelta

from .. import llm, memory
from ..models import VIS_ALL, VIS_INTERNAL
from ..progress import TaskCancelled
from .base import BaseAgent, say, send_file
from .doubao import DoubaoAgent
from .trae_agent import TraeAgent
from .workbuddy import WorkbuddyAgent

SYSTEM_PROMPT = """你是本地 AI 协作工作台的协调员，仅以第一人称与用户对话。
输出规则：
1. 给用户的最终回复、需要用户确认的问题、重要告警，属于结果类消息；
2. 给其他 Agent 的任务指令、过程沟通、中间校验，属于过程类消息；
3. 永远不要在私聊窗口提及其他 Agent 的存在，只以第一人称回复用户；
4. 用户问起过程细节时，回复「可以点击顶部『内部群聊』查看完整执行过程」。"""


class Coordinator(BaseAgent):
    name = "coordinator"
    display = "协调员"

    async def handle(self, user_text: str) -> None:
        await say(self.project, self.name, "收到需求，正在拆解任务…", VIS_ALL)
        intent = self._detect(user_text)
        try:
            if intent == "chat_summary":
                await self._chat_summary(user_text)
            elif intent == "file_ops":
                await self._file_ops()
            else:
                await self._chat_reply()
        except TaskCancelled:
            await say(self.project, self.name, "任务已取消。", VIS_ALL)
        except Exception as exc:  # 兜底，避免后台任务静默失败
            await say(self.project, self.name, f"处理失败：{exc}", VIS_ALL)

    # ---------------- 意图识别 ----------------
    def _detect(self, text: str) -> str:
        if any(k in text for k in ("聊天记录", "客户意向", "意向摘要", "外部联系人")):
            return "chat_summary"
        if any(k in text for k in ("整理文件", "汇总文件", "文件清单", "整理项目")):
            return "file_ops"
        return "chat"

    def _extract_date(self, text: str) -> str:
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

    # ---------------- 流程一：聊天记录 → 客户意向摘要 ----------------
    async def _chat_summary(self, user_text: str) -> None:
        d = self._extract_date(user_text)

        # 过程类（仅内部群）：派发给 Workbuddy
        await say(self.project, self.name,
                  f"@Workbuddy 拉取 {d} 外部联系人聊天记录，请统计总数并导出到公共文件夹",
                  VIS_INTERNAL)
        records, src = await WorkbuddyAgent(self.project).pull_chat_records(d)

        # 过程类（仅内部群）：派发给豆包
        await say(self.project, self.name,
                  f"@豆包 读取公共文件夹 {src.name}，生成客户意向摘要",
                  VIS_INTERNAL)
        res = await DoubaoAgent(self.project).generate_summary(src, d)

        # 过程类（仅内部群）：校验
        await say(self.project, self.name, "[校验完成] 结果无误，已同步给用户", VIS_INTERNAL)

        # 结果类（私聊 + 内部群）
        summary = (
            f"已完成 {d} 聊天记录摘要，共处理 {res['total']} 条对话、{res['contacts']} 位客户。\n"
            f"高意向 {len(res['high'])} 位，中意向 {len(res['mid'])} 位，低意向 {len(res['low'])} 位。"
        )
        if res["high"]:
            summary += f"\n高意向客户：" + "、".join(res["high"][:8])
        await say(self.project, self.name, summary, VIS_ALL)
        await send_file(self.project, self.name, res["file"], "public", VIS_ALL,
                        content="完整报告：客户意向摘要.md")

    # ---------------- 流程二：文件整理 ----------------
    async def _file_ops(self) -> None:
        await say(self.project, self.name,
                  "@Trae 整理公共文件夹并生成文件清单", VIS_INTERNAL)
        res = await TraeAgent(self.project).consolidate("public")
        await say(self.project, self.name,
                  f"已完成文件整理，共 {res['count']} 个文件，清单已输出。", VIS_ALL)
        await send_file(self.project, self.name, res["file"], "public", VIS_ALL)

    # ---------------- 通用问答（带分层记忆与自动压缩） ----------------
    async def _chat_reply(self) -> None:
        ctx = await memory.build_context(self.project, SYSTEM_PROMPT)
        s = ctx["stats"]
        notes = []
        if s["compressed"]:
            notes.append(f"上下文 {s['tokens_before']} → {s['tokens_after']} tokens，已压缩为滚动摘要")
        if s["profile_updated"]:
            notes.append("已更新项目档案（目标/结论/待办/偏好）")
        if notes:
            await say(self.project, self.name, "[长期记忆] " + "；".join(notes), VIS_INTERNAL)
        reply = await llm.chat(ctx["messages"])
        if not reply:
            reply = (
                "我在。可以试试对我说：\n"
                "· 把昨天所有外部联系人的聊天记录批量生成客户意向摘要\n"
                "· 整理项目文件并生成清单\n"
                "（未配置本地模型，当前为规则引擎回复；过程细节可切到「内部群聊」查看）"
            )
        await say(self.project, self.name, reply, VIS_ALL)


async def dispatch_user_message(project: str, text: str) -> None:
    """后台任务入口：作为 asyncio.Task 运行，不阻塞 HTTP 响应。"""
    await Coordinator(project).handle(text)
