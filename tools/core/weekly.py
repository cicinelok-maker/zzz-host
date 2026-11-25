"""周本次数追踪。

**为什么单独一个模块**：周本按「自然周」重置，和电量的「按分钟恢复」
是完全不同的资源模型。混在一起会让两边的判断互相污染。

数据：state/weekly_farm.json
```json
{"week": "2026-W48", "runs": {"恶名狩猎": 2}}
```
"""
from __future__ import annotations

import json
import pathlib
import time

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
STORE = BASE / "state" / "weekly_farm.json"

# 各周本每周能刷几次（2026-11-26 从游戏里确认的只有恶名狩猎 3 次）
LIMITS = {
    "恶名狩猎": 3,
    "哨站后勤": 3,          # 待确认，先按 3 给
}


def _week_key() -> str:
    """当前 ISO 周，形如 2026-W48。周一为一周开始。"""
    t = time.localtime()
    return time.strftime("%G-W%V", t)


def _load() -> dict:
    if not STORE.exists():
        return {"week": _week_key(), "runs": {}}
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"week": _week_key(), "runs": {}}
    # 换周了 → 清零
    if d.get("week") != _week_key():
        return {"week": _week_key(), "runs": {}}
    return d


def _save(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def used(name: str) -> int:
    """本周这个周本刷了几次。"""
    return int((_load().get("runs") or {}).get(name, 0))


def remaining(name: str) -> int:
    """本周还能刷几次。不认识的周本返回 0（宁可说用完，不要瞎刷）。"""
    limit = LIMITS.get(name)
    if limit is None:
        return 0
    return max(0, limit - used(name))


def can_run(name: str) -> tuple[bool, str]:
    """能不能刷。返回 (能, 说明)。"""
    limit = LIMITS.get(name)
    if limit is None:
        return False, f"不知道「{name}」每周几次，不冒险"
    u = used(name)
    left = max(0, limit - u)
    if left <= 0:
        return False, f"本周已刷 {u}/{limit} 次，用完了 —— 下周一会重置"
    return True, f"本周已刷 {u}/{limit} 次，还剩 {left} 次"


def record(name: str) -> None:
    """记一次。只在真的刷成功之后调。"""
    d = _load()
    runs = d.setdefault("runs", {})
    runs[name] = int(runs.get(name, 0)) + 1
    d["week"] = _week_key()
    _save(d)


def status() -> dict:
    """全部周本的剩余次数，给汇报用。"""
    out = {}
    for name, limit in LIMITS.items():
        out[name] = {"limit": limit, "used": used(name),
                     "left": max(0, limit - used(name))}
    return out
