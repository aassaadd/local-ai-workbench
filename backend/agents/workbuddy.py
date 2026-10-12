"""Workbuddy 连接器：批量拉取外部联系人聊天记录。

数据来源二选一：
- 配置了 WORKBUDDY_URL 时走真实 HTTP 接口；
- 否则读取该项目 imports/ 下用户导入的本地导出文件（CSV/JSON/TXT）。
两种模式都通过 ProgressReporter 上报进度，产物统一为 public/chat_<date>.json。
若既无真实接口、又无任何导入文件，则任务失败并给出可操作提示（不再生成随机假数据）。
"""
import asyncio
import json
import re
import time
from pathlib import Path
from typing import List, Tuple

from .. import config, importer, projects
from ..progress import ProgressReporter
from .base import BaseAgent

# 意向信号词，供豆包 Agent 做本地分类
HIGH_SIGNALS = ["多少钱", "怎么买", "报价", "合同", "下单", "采购", "签", "demo", "试用", "方案报价"]
MID_SIGNALS = ["了解一下", "有没有", "怎么样", "考虑", "功能", "方案", "价格", "咨询", "对比"]
LOW_SIGNALS = ["在吗", "你好", "哈哈", "谢谢", "改天聊", "忙"]


class WorkbuddyAgent(BaseAgent):
    name = "workbuddy"
    display = "Workbuddy"

    async def pull_chat_records(self, date: str) -> Tuple[List[dict], Path]:
        """拉取指定日期的外部联系人聊天记录并导出 JSON。

        功能：优先走 WORKBUDDY_URL 真实接口，否则解析 imports/ 下的导入文件；
              全程通过 ProgressReporter 上报进度，最后导出 chat_<date>.json。
        参数：date —— 日期字符串（如 20261012，用于匹配导入文件与命名产物）。
        返回值：(records, 产物文件 Path)。
        异常：无任何导入文件且未配置 WORKBUDDY_URL 时抛 RuntimeError。
        """
        task_id = f"pull_chat_{date}_{int(time.time())}"
        reporter = ProgressReporter(
            project=self.project, agent_name=self.name, task_id=task_id,
            task_name=f"拉取 {date} 外部联系人聊天记录", total=100,
        )
        await reporter.emit_pending()
        await reporter.update(0, f"正在连接外部联系人数据源…", phase="1/3 连接数据源", force=True)

        if config.WORKBUDDY_URL:
            records = await self._fetch_remote(date)
        else:
            records = await self._load_imported(date, reporter)

        total = len(records)
        await reporter.set_total(total, f"共查询到 {total} 个外部联系人会话")

        processed = 0
        step_every = max(1, total // 40)
        for i, rec in enumerate(records):
            await reporter.guard()  # 支持任务取消
            processed += 1
            if i % step_every == 0:
                await reporter.update(
                    processed, f"正在拉取第 {processed}/{total} 个会话",
                    phase="2/3 拉取会话消息",
                )
                await asyncio.sleep(0.02)  # 轻微让出事件循环

        await reporter.update(processed, "正在导出 JSON 文件…", phase="3/3 导出文件", force=True)
        out = projects.folder(self.project, "public") / f"chat_{date}.json"
        payload = {
            "date": date,
            "generated_at": time.time(),
            "count": total,
            "records": records,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        await reporter.finish(f"共拉取 {total} 个会话，已导出 {out.name} 到公共文件夹")
        return records, out

    async def _fetch_remote(self, date: str) -> List[dict]:
        """从 WORKBUDDY_URL 真实接口拉取记录。

        功能：GET {WORKBUDDY_URL}/chat_records?date=<date>，返回 records 字段。
        参数：date —— 日期字符串。
        返回值：记录列表。
        """
        import requests
        resp = requests.get(f"{config.WORKBUDDY_URL.rstrip('/')}/chat_records",
                            params={"date": date}, timeout=30)
        resp.raise_for_status()
        return resp.json().get("records", [])

    async def _load_imported(self, date: str, reporter: ProgressReporter) -> List[dict]:
        """从项目 imports/ 下读取并解析导入文件。

        功能：优先使用文件名含该日期（YYYYMMDD 或 YYYY-MM-DD）的文件；
              无匹配则使用全部导入文件；解析失败的文件跳过。
        参数：date —— 日期字符串；reporter —— 进度上报器（用于失败上报）。
        返回值：合并后的记录列表。
        异常：imports/ 下无任何文件时上报失败并抛 RuntimeError。
        """
        d = projects.imports_dir(self.project)
        files = [f for f in sorted(d.iterdir()) if f.is_file()] if d.exists() else []
        if not files:
            msg = f"请先导入 {date} 的聊天记录（支持 CSV/JSON/TXT）"
            await reporter.fail(msg)
            raise RuntimeError(msg)

        variants = self._date_variants(date)
        matched = [f for f in files if any(v in f.name for v in variants)]
        targets = matched or files

        records: List[dict] = []
        for f in targets:
            try:
                records.extend(importer.parse_bytes(f.name, f.read_bytes()))
            except ValueError:
                continue  # 单个文件解析失败不影响整体
        return records

    @staticmethod
    def _date_variants(date: str) -> set:
        """生成用于文件名匹配的日期变体集合。

        功能：把 20261012 之类日期同时支持紧凑与带短横线两种写法。
        参数：date —— 日期字符串。
        返回值：去重后的变体集合（非空，至少包含原串）。
        """
        variants = {date} if date else set()
        digits = re.sub(r"\D", "", date or "")
        if len(digits) == 8:
            variants.add(digits)
            variants.add(f"{digits[:4]}-{digits[4:6]}-{digits[6:]}")
        return variants