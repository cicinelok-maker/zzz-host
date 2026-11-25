"""周本 / 免费次数的电量模型。

## 关键区分（用户 2026-11-26 纠正）

**「免费额度」不是「总上限」。**

  前 N 次  电量 0
  第 N+1 次起  花电量

上一版把它当成总上限（用完就跳过），**错了** —— 那会让工具在还能刷的时候放弃。

## 数据

state/weekly_farm.json
```json
{"week": "2026-W48", "runs": {"恶名狩猎": 2}}
```

`week` 用 ISO 周（%G-W%V，周一为开始），换周自动清零。
"""
from __future__ import annotations

import json
import pathlib
import time

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
STORE = BASE / "state" / "weekly_farm.json"

# 每周免费次数
FREE_RUNS = {
    "恶名狩猎": 3,
    "哨站后勤": 3,      # 待确认
}
# 免费次数用完之后，每次要花多少电（**待用户确认**，先按 40 给）
BATTERY_AFTER_FREE = {
    "恶名狩猎": 40,
    "哨站后勤": 40,
}


def _week_key() -> str:
    return time.strftime("%G-W%V", time.localtime())


def _load() -> dict:
    if not STORE.exists():
        return {"week": _week_key(), "runs": {}}
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"week": _week_key(), "runs": {}}
    if d.get("week") != _week_key():
        return {"week": _week_key(), "runs": {}}
    return d


def _save(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def used(name: str) -> int:
    return int((_load().get("runs") or {}).get(name, 0))


def free_left(name: str) -> int:
    """本周还剩几次免费。"""
    lim = FREE_RUNS.get(name)
    if lim is None:
        return 0
    return max(0, lim - used(name))


def cost_for_next(name: str) -> int:
    """**下一次**刷要花多少电量。免费期返回 0。"""
    if name not in FREE_RUNS:
        return -1              # 不认识
    if free_left(name) > 0:
        return 0
    return BATTERY_AFTER_FREE.get(name, 40)


def can_run(name: str) -> tuple[bool, str]:
    """能不能刷 + 说明。**免费次数用完不代表不能刷。**"""
    if name not in FREE_RUNS:
        return False, f"不知道「{name}」的规则，不冒险"
    left = free_left(name)
    u = used(name)
    lim = FREE_RUNS[name]
    if left > 0:
        return True, f"本周免费 {u}/{lim} 次，还剩 {left} 次（不花电量）"
    c = BATTERY_AFTER_FREE.get(name, 40)
    return True, f"本周免费 {lim} 次已用完，之后每次花 {c} 电量"


def record(name: str) -> None:
    """记一次。只在真刷成功之后调。"""
    d = _load()
    runs = d.setdefault("runs", {})
    runs[name] = int(runs.get(name, 0)) + 1
    d["week"] = _week_key()
    _save(d)


def status() -> dict:
    out = {}
    for name, lim in FREE_RUNS.items():
        out[name] = {"free_limit": lim, "used": used(name),
                     "free_left": free_left(name),
                     "next_cost": cost_for_next(name)}
    return out
