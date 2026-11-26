"""读取角色状态的唯一入口（读不到时给清晰提示）。

## 为什么需要

分析类工具（check_42 / gap_analysis / selfcheck / explain_crit）各自写：
```python
st = json.loads((BASE / "state" / f"status_{AGENT}.json").read_text(...))
```
换一个没读过的角色时报：
```
FileNotFoundError: [Errno 2] No such file or directory: '.../status_安比.json'
```

用户看到 traceback 不知道下一步干什么。

## 统一入口

```python
from core.state import load_status, load_meta
st = load_status("安比")     # 没有就提示 + 退出码 2
cfg = load_meta("安比")      # 同上
```

同时把「用哪个角色」也统一：环境变量 `ZZZ_AGENT`，
没设就用 `DEFAULT_AGENT`。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
STATE = BASE / "state"


def current_agent(default: str = "") -> str:
    """当前操作的角色：环境变量 ZZZ_AGENT > default > DEFAULT_AGENT。"""
    if os.environ.get("ZZZ_AGENT"):
        return os.environ["ZZZ_AGENT"]
    if default:
        return default
    from core.game_cfg import DEFAULT_AGENT
    return DEFAULT_AGENT


def _hint(agent: str, what: str) -> None:
    print(f"还没有「{agent}」的{what}。先跑：")
    print(f"  python tools/zzz_status.py {agent} --json")


def load_status(agent: str = "") -> dict:
    """读 state/status_{agent}.json。"""
    agent = current_agent(agent)
    p = STATE / f"status_{agent}.json"
    if not p.exists():
        _hint(agent, "状态数据")
        raise SystemExit(2)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"「{agent}」的状态文件读不了：{e}")
        print(f"  文件：{p}")
        raise SystemExit(2)


def load_meta(agent: str = "") -> dict:
    """读 disc_meta.json 里该角色的配置。"""
    agent = current_agent(agent)
    p = BASE / "tools" / "disc_meta.json"
    meta = json.loads(p.read_text(encoding="utf-8"))
    cfg = (meta.get("角色") or {}).get(agent)
    if not cfg:
        have = list((meta.get("角色") or {}).keys())
        print(f"disc_meta.json 里没有「{agent}」的配置。")
        print(f"  已配置的角色：{have}")
        raise SystemExit(2)
    return cfg


# ============================================================ 状态新鲜度
# 所有状态文件都该带时间戳。三天前读的 slots 算出来的缺口是错的，
# 但文件看起来完全正常 —— 这是最容易被当成「工具坏了」的一类问题。

# 各类状态的「多久算过期」（小时）
STALE_HOURS = {
    "status": 24,        # 驱动盘/技能/等级 —— 一天一读够
    "core": 48,          # 核心技要进技能页逐圈点，5 分钟一次，两天
    "wengine": 48,
}

_TS_KEY = "_ts"


# **状态文件的 schema 版本**（RT-REPORT 最小修复第 2 条）。
#
# 真机实测踩过：写入方只写 5 个字段、读取方读 8 个，
# 而文件看着完全正常 —— 于是「字段从没被写过」被当成「旧文件残留」，
# 谁都没发现契约从未实现。
#
# 有版本号之后，读取方可以判断「这份文件的写入方是不是我期望的版本」。
SCHEMA = 2


def stamp(data: dict) -> dict:
    """给状态字典打时间戳 + schema 版本（原地改 + 返回，方便链式）。"""
    if isinstance(data, dict):
        import time as _t
        data[_TS_KEY] = _t.strftime("%Y-%m-%dT%H:%M:%S")
        data["_schema"] = SCHEMA
    return data


def age_hours(data: dict) -> float | None:
    """这份状态多久以前写的（小时）。没有时间戳返回 None。"""
    if not isinstance(data, dict):
        return None
    ts = data.get(_TS_KEY)
    if not ts:
        return None
    try:
        import datetime as _dt
        then = _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        return (_dt.datetime.now() - then).total_seconds() / 3600.0
    except Exception:
        return None


def check_fresh(data: dict, kind: str = "status", label: str = "") -> bool:
    """检查是否过期。过期就打警告到 stderr，返回 True=新鲜的。"""
    import sys as _s
    age = age_hours(data)
    limit = STALE_HOURS.get(kind, 24)
    if age is None:
        print(f"  ⚠ {label or kind} 状态没有时间戳，不知道是多久前读的"
              f"（建议重跑一次）", file=_s.stderr)
        return False
    if age > limit:
        print(f"  ⚠ {label or kind} 状态是 {age:.1f} 小时前的（超过 {limit} 小时）"
              f"—— 算出来的缺口可能已经不准，建议重跑一次", file=_s.stderr)
        return False
    return True

