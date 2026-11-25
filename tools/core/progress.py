"""断点续跑：把进度写盘，崩溃/中断后从中断处继续。

长时间无人值守的前提。没有它，一次意外就要从头再来。

用法
====
    prog = Progress("佩洛伊斯_驱动盘")
    if prog.done("3号位"):
        continue
    ... 干活 ...
    prog.mark("3号位", {"level": 15, "eff": 4.5})
    prog.save()
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE / "state" / "progress"


class Progress:
    def __init__(self, task: str, autosave: bool = True):
        self.task = task
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task)
        self.path = STATE_DIR / f"{safe}.json"
        self.autosave = autosave
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = self._fresh()
        else:
            self.data = self._fresh()

    def _fresh(self) -> dict:
        return {"task": self.task, "created": self._now(),
                "updated": self._now(), "done": {}, "notes": []}

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---------- 查询 ----------
    def done(self, key: str) -> bool:
        return key in self.data.get("done", {})

    def get(self, key: str, default=None):
        return (self.data.get("done") or {}).get(key, default)

    def pending(self, keys: list[str]) -> list[str]:
        return [k for k in keys if not self.done(k)]

    # ---------- 记录 ----------
    def mark(self, key: str, info: dict | None = None) -> None:
        self.data.setdefault("done", {})[key] = {
            "at": self._now(), **(info or {})}
        self.save()

    def note(self, text: str) -> None:
        self.data.setdefault("notes", []).append(
            {"at": self._now(), "text": text[:300]})
        self.save()

    def reset(self) -> None:
        self.data = self._fresh()
        self.save()

    def save(self) -> None:
        if not self.autosave:
            return
        self.data["updated"] = self._now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    # ---------- 展示 ----------
    def summary(self) -> str:
        done = self.data.get("done") or {}
        lines = [f"进度 {self.task}：已完成 {len(done)} 项  （{self.path}）"]
        for k, v in done.items():
            extra = {kk: vv for kk, vv in v.items() if kk != "at"}
            lines.append(f"  ✔ {k}  {extra if extra else ''}")
        return "\n".join(lines)
