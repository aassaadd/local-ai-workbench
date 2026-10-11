"""Workbuddy 连接器：批量拉取外部联系人聊天记录。

- 配置了 WORKBUDDY_URL 时走真实 HTTP 接口；
- 否则使用内置本地数据源，生成真实 JSON 文件产物（便于离线演示与联调）。
两种模式都通过 ProgressReporter 上报进度。
"""
import asyncio
import json
import random
import time
from pathlib import Path
from typing import List, Tuple

from .. import config, projects
from ..progress import ProgressReporter
from .base import BaseAgent

SURNAMES = ["张", "李", "王", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱"]
GIVEN = ["伟", "芳", "娜", "敏", "静", "磊", "强", "洋", "艳", "勇", "军", "杰", "涛", "明"]
COMPANIES = ["云启科技", "恒达贸易", "蓝鲸传媒", "智联制造", "远航物流", "新程教育",
             "森屿设计", "启元软件", "汇通金融", "博远医疗"]

# 意向信号词，供豆包 Agent 做本地分类
HIGH_SIGNALS = ["多少钱", "怎么买", "报价", "合同", "下单", "采购", "签", "demo", "试用", "方案报价"]
MID_SIGNALS = ["了解一下", "有没有", "怎么样", "考虑", "功能", "方案", "价格", "咨询", "对比"]
LOW_SIGNALS = ["在吗", "你好", "哈哈", "谢谢", "改天聊", "忙"]

USER_LINES_HIGH = ["这个多少钱？", "能发个正式报价吗？", "我们想采购 50 套，怎么签合同？", "方便安排个 demo 吗？"]
USER_LINES_MID = ["想了解一下你们的产品", "有没有案例或者方案可以看？", "价格大概什么区间？", "我们在对比几家，先咨询下"]
USER_LINES_LOW = ["在吗", "你好呀", "哈哈改天聊", "谢谢啦"]


class WorkbuddyAgent(BaseAgent):
    name = "workbuddy"
    display = "Workbuddy"

    async def pull_chat_records(self, date: str) -> Tuple[List[dict], Path]:
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
            records = self._generate_local(date)
            await asyncio.sleep(0.4)  # 模拟查询耗时

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
                await asyncio.sleep(0.05)  # 模拟逐条拉取

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
        import requests
        resp = requests.get(f"{config.WORKBUDDY_URL.rstrip('/')}/chat_records",
                            params={"date": date}, timeout=30)
        resp.raise_for_status()
        return resp.json().get("records", [])

    def _generate_local(self, date: str) -> List[dict]:
        rnd = random.Random(f"wb-{self.project}-{date}")
        n = rnd.randint(110, 140)
        records = []
        for i in range(n):
            name = rnd.choice(SURNAMES) + rnd.choice(GIVEN)
            company = rnd.choice(COMPANIES)
            bucket = rnd.choices(["high", "mid", "low"], weights=[15, 45, 40])[0]
            lines = {"high": USER_LINES_HIGH, "mid": USER_LINES_MID, "low": USER_LINES_LOW}[bucket]
            signal = {"high": HIGH_SIGNALS, "mid": MID_SIGNALS, "low": LOW_SIGNALS}[bucket]
            msgs = []
            for _ in range(rnd.randint(2, 5)):
                msgs.append({"role": "user", "text": rnd.choice(lines)})
                msgs.append({"role": "contact", "text": rnd.choice(signal) + rnd.choice(["～", "，可以细聊", "，稍后回复", ""])})
            records.append({
                "contact": name,
                "company": company,
                "msgs": msgs,
                "time": time.time() - rnd.randint(60, 86400),
            })
        return records
