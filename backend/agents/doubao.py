"""豆包 Agent 连接器：读取公共文件夹的聊天记录，生成客户意向摘要。

- 配置了 DOUBAO_BASE_URL 时走豆包 API 做语义分析；
- 否则使用本地关键词规则引擎（离线可用），产出真实 Markdown 文件。
"""
import asyncio
import json
import time
from pathlib import Path

from .. import config, projects
from ..progress import ProgressReporter
from .base import BaseAgent
from .workbuddy import HIGH_SIGNALS, MID_SIGNALS, LOW_SIGNALS

SYSTEM_PROMPT = """你是客户意向分析助手。给定一个客户的聊天记录，判断其购买意向等级。
只输出 JSON：{"level": "high|mid|low", "reason": "一句话依据"}"""


class DoubaoAgent(BaseAgent):
    name = "doubao"
    display = "豆包"

    async def generate_summary(self, src_file: Path, date: str) -> dict:
        task_id = f"summary_{date}_{int(time.time())}"
        reporter = ProgressReporter(
            project=self.project, agent_name=self.name, task_id=task_id,
            task_name="生成客户意向摘要", total=100,
        )
        await reporter.emit_pending()
        await reporter.update(0, f"正在读取 {src_file.name}…", phase="1/3 读取数据", force=True)

        data = json.loads(src_file.read_text(encoding="utf-8"))
        records = data.get("records", [])
        total = len(records)
        await reporter.set_total(total, f"共 {total} 位客户待分析")

        high, mid, low = [], [], []
        details = []
        step_every = max(1, total // 40)
        for i, rec in enumerate(records):
            await reporter.guard()
            level, reason = await self._classify(rec)
            bucket = {"high": high, "mid": mid, "low": low}[level]
            bucket.append(rec["contact"])
            details.append({"contact": rec["contact"], "company": rec.get("company", ""),
                            "level": level, "reason": reason})
            if i % step_every == 0:
                await reporter.update(
                    i + 1, f"正在分析第 {i + 1}/{total} 位客户对话",
                    phase="2/3 分析客户意向",
                )
                await asyncio.sleep(0.05)

        await reporter.update(total, "正在生成摘要文档…", phase="3/3 生成摘要", force=True)
        out = projects.folder(self.project, "public") / "客户意向摘要.md"
        out.write_text(self._render_md(date, total, high, mid, low, details), encoding="utf-8")

        await reporter.finish(
            f"已生成 {len(high) + len(mid) + len(low)} 位客户意向摘要，输出 {out.name}"
        )
        return {
            "total": total, "contacts": total,
            "high": high, "mid": mid, "low": low,
            "file": out,
        }

    async def _classify(self, rec: dict) -> tuple:
        text = " ".join(m.get("text", "") for m in rec.get("msgs", []))
        if config.DOUBAO_BASE_URL:
            result = await self._classify_remote(text)
            if result:
                return result
        high = sum(text.count(k) for k in HIGH_SIGNALS)
        mid = sum(text.count(k) for k in MID_SIGNALS)
        low = sum(text.count(k) for k in LOW_SIGNALS)
        if high > 0:
            return "high", "提及报价/合同/采购等明确成交信号"
        if mid > 0:
            return "mid", "主动咨询产品/价格/方案，处于了解阶段"
        return "low", f"以寒暄为主（low信号 {low} 次），暂无意向"

    async def _classify_remote(self, text: str):
        import requests
        try:
            url = config.DOUBAO_BASE_URL.rstrip("/") + "/chat/completions"
            headers = {"Content-Type": "application/json"}
            if config.DOUBAO_API_KEY:
                headers["Authorization"] = f"Bearer {config.DOUBAO_API_KEY}"
            payload = {
                "model": config.DOUBAO_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "temperature": 0,
            }
            resp = await asyncio.to_thread(
                lambda: requests.post(url, headers=headers, json=payload, timeout=30)
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            obj = json.loads(content[content.find("{"):content.rfind("}") + 1])
            return obj.get("level", "low"), obj.get("reason", "")
        except Exception:
            return None

    def _render_md(self, date, total, high, mid, low, details) -> str:
        lines = [
            f"# 客户意向摘要（{date}）",
            "",
            f"- 处理会话：{total} 条",
            f"- 覆盖客户：{total} 位",
            f"- 高意向：{len(high)} 位",
            f"- 中意向：{len(mid)} 位",
            f"- 低意向：{len(low)} 位",
            "",
            "## 高意向客户",
            "",
        ]
        for d in details:
            if d["level"] == "high":
                lines.append(f"- **{d['contact']}**（{d['company']}）：{d['reason']}")
        lines += ["", "## 中意向客户", ""]
        for d in details:
            if d["level"] == "mid":
                lines.append(f"- {d['contact']}（{d['company']}）：{d['reason']}")
        lines += ["", "## 低意向客户", ""]
        lines.append("、".join(low) if low else "无")
        lines.append("")
        return "\n".join(lines)
