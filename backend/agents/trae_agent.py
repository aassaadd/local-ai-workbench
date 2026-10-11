"""Trae Agent 连接器：本地文件/脚本类任务（自调用本地能力）。

用于处理「整理文件 / 汇总 / 统计」类需求，扫描项目公共文件夹产出清单文件。
配置 TRAE_URL 时可转发给外部 Trae 服务。
"""
import asyncio
import time
from pathlib import Path

from .. import config, projects
from ..progress import ProgressReporter
from .base import BaseAgent


class TraeAgent(BaseAgent):
    name = "trae"
    display = "Trae"

    async def consolidate(self, scope: str = "public") -> dict:
        task_id = f"trae_consolidate_{int(time.time())}"
        reporter = ProgressReporter(
            project=self.project, agent_name=self.name, task_id=task_id,
            task_name="整理项目文件并生成清单", total=100,
        )
        await reporter.emit_pending()
        folder = projects.folder(self.project, scope)
        files = [f for f in sorted(folder.iterdir()) if f.is_file()]
        await reporter.set_total(len(files), "开始扫描文件夹…")

        rows = []
        for i, f in enumerate(files):
            await reporter.guard()
            st = f.stat()
            rows.append((f.name, st.st_size, st.st_mtime))
            await reporter.update(i + 1, f"正在整理第 {i + 1}/{len(files)} 个文件")
            await asyncio.sleep(0.03)

        out = projects.folder(self.project, "public") / "文件清单.md"
        md = ["# 项目文件清单", "", f"- 扫描目录：{scope}/", f"- 文件数量：{len(rows)}", "",
              "| 文件 | 大小(B) | 更新时间 |", "| --- | --- | --- |"]
        for name, size, mtime in rows:
            md.append(f"| {name} | {size} | {time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))} |")
        out.write_text("\n".join(md) + "\n", encoding="utf-8")

        await reporter.finish(f"已整理 {len(rows)} 个文件，输出 {out.name}")
        return {"count": len(rows), "file": out}
