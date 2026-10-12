"""协调员 Agent：对接本地模型做任务拆解与分发，并负责消息分级（私聊/内部群）。

路由方式：查询「能力注册表」（capabilities）选择能力并执行——
- 有本地模型时，让模型输出 {"capability": "...", "args": {...}} 选择能力；
- 无本地模型或模型解析失败时，按关键词打分兜底；
- 未命中任何非 chat 能力时，回退通用对话（保留分层记忆）。
新增能力只需在 capabilities 注册，无需改动本文件的路由逻辑。
"""
import json

from .. import capabilities, llm, memory
from ..models import VIS_ALL, VIS_INTERNAL
from ..progress import TaskCancelled
from .base import BaseAgent, say

SYSTEM_PROMPT = """你是本地 AI 协作工作台的协调员，仅以第一人称与用户对话。
输出规则：
1. 给用户的最终回复、需要用户确认的问题、重要告警，属于结果类消息；
2. 给其他 Agent 的任务指令、过程沟通、中间校验，属于过程类消息；
3. 永远不要在私聊窗口提及其他 Agent 的存在，只以第一人称回复用户；
4. 用户问起过程细节时，回复「可以点击顶部『内部群聊』查看完整执行过程」。
5. 你只能选择下面已注册的能力来完成任务，不要臆造未注册的能力。"""


class Coordinator(BaseAgent):
    name = "coordinator"
    display = "协调员"

    async def handle(self, user_text: str) -> None:
        """处理一条用户需求：拆解 → 选能力 → 执行。

        功能：先广播「收到需求」提示，再路由选择能力并执行；chat 能力走通用对话。
        参数：user_text —— 用户输入的原始文本。
        返回值：无。
        """
        await say(self.project, self.name, "收到需求，正在拆解任务…", VIS_ALL)
        try:
            key, args = await self._route(user_text)
            args = dict(args or {})
            args.setdefault("text", user_text)
            cap = capabilities.get(key)
            if key == "chat" or cap is None or cap.handler is None:
                await self._chat_reply()
                return
            await cap.handler(self.project, args)
        except TaskCancelled:
            await say(self.project, self.name, "任务已取消。", VIS_ALL)
        except Exception as exc:  # 兜底，避免后台任务静默失败
            await say(self.project, self.name, f"处理失败：{exc}", VIS_ALL)

    # ---------------- 能力路由 ----------------
    async def _route(self, user_text: str) -> tuple:
        """选择要执行的能力及其参数。

        功能：有本地模型时先让模型选能力（解析失败或能力不存在则回退关键词打分），
              无本地模型时直接用关键词打分。
        参数：user_text —— 用户输入文本。
        返回值：(能力 key, args)。
        """
        if llm.available():
            routed = await self._llm_route(user_text)
            if routed and capabilities.get(routed[0]):
                return routed
        return capabilities.match(user_text)

    async def _llm_route(self, user_text: str) -> tuple | None:
        """调用本地模型选择能力。

        功能：在系统提示词中列出可用能力清单，要求模型只输出 JSON。
        参数：user_text —— 用户输入文本。
        返回值：(能力 key, args)，无法解析时返回 None。
        """
        system = (
            SYSTEM_PROMPT
            + "\n\n" + capabilities.describe()
            + '\n请只输出 JSON：{"capability": "能力key", "args": {...}}，'
              "args 为传给该能力的参数（如日期 date），无参数则为 {}。"
        )
        reply = await llm.chat([{"role": "system", "content": system},
                                {"role": "user", "content": user_text}])
        if not reply:
            return None
        try:
            obj = json.loads(reply[reply.find("{"):reply.rfind("}") + 1])
        except (ValueError, json.JSONDecodeError):
            return None
        key = obj.get("capability")
        if not isinstance(key, str) or not key.strip():
            return None
        args = obj.get("args")
        return key.strip(), args if isinstance(args, dict) else {}

    # ---------------- 通用问答（带分层记忆与自动压缩） ----------------
    async def _chat_reply(self) -> None:
        """通用对话兜底：带分层记忆与自动压缩的回复。

        功能：装配上下文（长期档案 + 摘要 + 近期原文），调用本地模型回复；
              无模型时给出可用能力引导文案（保持原有文案）。
        参数：无（使用该类实例的项目上下文）。
        返回值：无。
        """
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