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


# 读取方**必须**看到的字段（RT-REPORT N-3 的契约）。
REQUIRED_STATUS_KEYS = ("total", "slots", "blue_total")


def check_status_schema(agent: str, d: dict, path=None) -> list[str]:
    """检查状态文件是否满足契约，返回缺失字段列表。

    ## 为什么需要（RT-REPORT N-3）

    写入方只写 5 个字段、读取方读 8 个，**而文件看着完全正常** ——
    于是「字段从没被写过」被当成「旧文件残留」，谁都没发现契约从未实现。
    实测 `status_丽娜.json` 里只有 `agent` 和 `total` 两个键。

    现在读取前先对一遍契约，缺什么就打出来（不退出，因为下游可能只用一部分）。
    """
    miss = [k for k in REQUIRED_STATUS_KEYS if k not in d]
    if not miss:
        # **字段齐了不代表数据可信**（BUG-130）。
        # `_valid` 缺省时按「老文件」放行，但明确 False 就要喊出来。
        if d.get("_valid") is False:
            n_read = d.get("_slots_read", len(d.get("slots") or []))
            print(f"  ⚠ 「{agent}」的状态快照**无效**：只读到 {n_read}/6 个位号")
            print(f"     total=0 可能是「读取失败」而不是「真的没盘」。")
            print(f"     重跑一次：python tools/zzz_status.py {agent} --json")
            return ["_valid"]
        return []
    where = f"（{path.name}）" if path is not None else ""
    print(f"  ⚠ 「{agent}」的状态文件{where}缺字段：{miss}")
    print(f"     这份数据可能是旧版本写的，或者写入被中断了。")
    print(f"     重跑一次就好：python tools/zzz_status.py {agent} --json")
    if "_schema" in d:
        print(f"     文件 schema = {d.get('_schema')}")
    return miss


def load_status(agent: str = "", strict: bool = False) -> dict:
    """读 state/status_{agent}.json。

    **角色名先归一化**（BUG-95）。
    原来直接用调用方传进来的名字，而 `status_*.json` 是按**库里的正式名**建的。
    于是 `load_status("佩洛依斯")`（错一个字）会去找
    `status_佩洛依斯.json` —— 不存在 → 提示「先跑
    `python tools/zzz_status.py 佩洛依斯 --json`」—— **而那条命令同样会失败**，
    因为它也会用这个名字去查角色库。提示等于没用。
    """
    agent = current_agent(agent)
    try:
        from core.agent_name import canonical_agent
        canon = canonical_agent(agent)
        if canon and canon != agent:
            if not (STATE / f"status_{agent}.json").exists() \
                    and (STATE / f"status_{canon}.json").exists():
                print(f"  （「{agent}」按「{canon}」找状态文件）")
            agent = canon
    except Exception:
        pass
    p = STATE / f"status_{agent}.json"
    if not p.exists():
        _hint(agent, "状态数据")
        raise SystemExit(2)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"「{agent}」的状态文件读不了：{e}")
        print(f"  文件：{p}")
        raise SystemExit(2)
    _why = check_status_schema(agent, d, p)

    # **写路径要 `strict=True`，读到废数据直接拒**（D5）。
    #
    # 原来 `check_status_schema` 只 `print` 一行警告，然后**照样把数据返回**。
    # 于是下游拿着「6 个位号只读到 1 个」的快照继续做决策：
    #   · `zzz_cost`   当全新角色算 5480 电
    #   · `zzz_who`    报「距毕业 28.0 / ✔ 没有明显缺口」
    #   · `zzz_grind`  直接排 5 轮
    #
    # 只读展示（`zzz_who` / `zzz_cost`）可以容忍并提示；
    # **要花电量/材料的路径不能** —— 那会把资源花在错的目标上。
    if _why and strict:
        print()
        print(f"  ✘ 状态快照不可信，拒绝用它做决策（{_why}）")
        print(f"     先重跑：python tools/zzz_status.py {agent} --json")
        raise SystemExit(8)          # 8 = 读不到数据
    return d


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

