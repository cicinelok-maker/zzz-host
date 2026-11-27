"""材料库存记账。

## 为什么单独一个模块

刷本是「花电量换材料」，如果不记库存：
- 刷完不知道到手多少
- 缺口永远按「总量」算，不按「还差多少」算
- 用户看不出进度

`state/inventory.json`：
```json
{"_ts": "2026-11-26T01:20:00",
 "高维数据：深蚀回路": {"有": 6},
 "刻命残蜕": {"有": 3}}
```

## 数据从哪来

**不主动读游戏** —— 那要进技能页逐圈点材料图标，很慢。

只在这些时候顺手记：
- `zzz_core.py material` 本来就会读弹窗的「当前拥有 ×N」→ 记下来
- 刷本成功之后 → 按产出数扣减/增加

## 一个语义问题

「有」是**账号总库存**，不是某个角色的。同一个材料多个角色共用。
所以库存只有一份，缺口要**按角色汇总后减去库存**。
"""
from __future__ import annotations
from core import atomic as _aw

import json
import pathlib
import time

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
STORE = BASE / "state" / "inventory.json"


def _load() -> dict:
    """读库存。

    ## **坏文件不能静默当空**（E7）

    原来是 `except Exception: return {"_ts": "", "items": {}}` ——
    半截 JSON 被当成「没有库存」，**然后 `_save()` 会把整份文件覆盖掉**，
    历史就这么没了。

    现在：读不了先**备份成 `.corrupt`**，再报出来，然后按空继续。
    备份是关键 —— 至少让人能手工抢救。
    """
    if not STORE.exists():
        return {"_ts": "", "items": {}}
    txt = STORE.read_text(encoding="utf-8", errors="replace")
    if not txt.strip():
        return {"_ts": "", "items": {}}
    try:
        d = json.loads(txt)
    except Exception as e:
        bak = STORE.with_name(STORE.name + ".corrupt")
        moved = False
        try:
            STORE.replace(bak)
            moved = True
        except Exception:
            pass
        print(f"  ⚠ {STORE.name} 读不了（{e}）")
        if moved:
            print(f"     已备份成 {bak.name}（{len(txt)} 字节），本次按空库存继续")
            print(f"     抢救办法：手工修好后改名回 {STORE.name}")
        return {"_ts": "", "items": {}}
    if not isinstance(d, dict):
        print(f"  ⚠ {STORE.name} 的内容是 {type(d).__name__}，不是对象 —— 按空库存继续")
        return {"_ts": "", "items": {}}
    if "items" not in d:
        d = {"_ts": d.pop("_ts", ""), "items": d}
    return d


def _save(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    d["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    from core import atomic as _atomic
    _atomic.write_json(STORE, d)


def record(name: str, have: int, source: str = "") -> None:
    """记一个材料的当前库存。"""
    if not name:
        return
    d = _load()
    items = d.setdefault("items", {})
    ent = items.setdefault(name, {})
    ent["有"] = int(have)
    if source:
        ent["来源"] = source
    _save(d)


def get(name: str) -> int:
    """当前有多少。没记录过返回 0。"""
    return int((_load().get("items") or {}).get(name, {}).get("有", 0) or 0)


def spend(name: str, amount: int) -> None:
    """花掉一些（刷本消耗/升级消耗）。不会减到负数。"""
    d = _load()
    items = d.setdefault("items", {})
    ent = items.setdefault(name, {"有": 0})
    ent["有"] = max(0, int(ent.get("有", 0)) - int(amount))
    _save(d)


def add(name: str, amount: int) -> None:
    """到手一些（刷本产出）。"""
    d = _load()
    items = d.setdefault("items", {})
    ent = items.setdefault(name, {"有": 0})
    ent["有"] = int(ent.get("有", 0)) + int(amount)
    _save(d)


def snapshot() -> dict:
    """全部库存 + 时间戳。"""
    d = _load()
    out = dict(d.get("items") or {})
    out["_ts"] = d.get("_ts", "")
    return out


def age_hours() -> float | None:
    """库存多久以前的记录。"""
    ts = _load().get("_ts")
    if not ts:
        return None
    try:
        import datetime as _dt
        then = _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        return (_dt.datetime.now() - then).total_seconds() / 3600.0
    except Exception:
        return None
