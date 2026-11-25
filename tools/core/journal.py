"""结构化日志 + 截图留证：出问题能复盘。

每步记录：时间、模块、动作、耗时、结果、附带截图文件名。
日志是 JSONL，方便直接过滤统计；截图进 od_test/journal/日期/ 下。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
LOG_DIR = BASE / "od_test" / "journal"


class Journal:
    def __init__(self, task: str = "general", keep_shots: bool = True):
        self.task = task
        self.keep_shots = keep_shots
        day = datetime.now().strftime("%Y%m%d")
        self.dir = LOG_DIR / day
        self.dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]+", "_", task)[:40]
        self.path = self.dir / f"{safe}.jsonl"
        self.t0 = time.time()
        self.records: list[dict] = []

    # ---------- 记录 ----------
    def log(self, step: str, action: str, *, ok: bool = True,
            ms: float = 0.0, detail: str = "", shot=None) -> dict:
        rec = {
            "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "t": round(time.time() - self.t0, 2),
            "task": self.task,
            "step": step,
            "action": action,
            "ok": ok,
            "ms": round(ms, 1),
            "detail": detail[:300],
        }
        if shot is not None and self.keep_shots:
            rec["shot"] = self.shot(step, shot)
        self.records.append(rec)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        flag = "OK" if ok else "--"
        print(f"  [{flag}] {step:<10} {action:<22} {ms:6.0f}ms  {detail[:60]}")
        return rec

    def shot(self, step: str, img) -> str:
        """保存一帧到日志目录，返回文件名"""
        try:
            from PIL import Image
            safe = re.sub(r"[^\w-]+", "_", step)
            stamp = datetime.now().strftime("%H%M%S")
            name = f"{stamp}_{safe}.png"
            Image.fromarray(img[:, :, ::-1]).save(self.dir / name)
            return name
        except Exception:
            return ""

    # ---------- 统计 ----------
    def summary(self) -> str:
        total = len(self.records)
        bad = [r for r in self.records if not r["ok"]]
        slow = sorted(self.records, key=lambda r: -r["ms"])[:5]
        lines = [f"任务 {self.task}：{total} 步，失败 {len(bad)} 步，"
                 f"总耗时 {time.time() - self.t0:.1f}s",
                 f"  日志：{self.path}"]
        if bad:
            lines.append("  失败步骤：")
            for r in bad[:10]:
                lines.append(f"    {r['step']}/{r['action']}  {r['detail'][:60]}")
        if slow:
            lines.append("  最慢 5 步：")
            for r in slow:
                lines.append(f"    {r['step']:<10} {r['ms']:.0f}ms")
        return "\n".join(lines)


# 全局默认实例，方便随时记录
GLOBAL = Journal("global")
