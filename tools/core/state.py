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