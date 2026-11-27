"""暂停 / 断点 / 续跑。

**失焦不等于失败。** 用户切走窗口只是想看个消息，不该让整个养成白跑。
**Ctrl+C 不等于丢工作。** 存个断点，下次接着来。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from . import focus

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
CKPT = BASE / "state" / "run_checkpoint.json"


def save(agent: str, done: list[str], pending: list[str], reason: str) -> pathlib.Path:
    """存断点。"""
    CKPT.parent.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps({
        "agent": agent,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "done": list(done),
        "pending": list(pending),
        "reason": reason,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return CKPT


def load(agent: str = "", today_only: bool = True) -> dict | None:
    """读断点。给了 agent 就检查是不是同一个角色。

    ## **断点只当天有效**（RT-10）

    原来只校验角色，不校验日期。于是「昨天跑完一轮」留下的断点，
    今天 `--run --resume` 会把**全部步骤当成已完成**跳过 —— 然后返回 0。

    **看起来像跑完了，其实一步没做。**

    而 `zzz_daily` 本来是「每日养成」工具，断点的语义就是「今天做到哪了」，
    跨天继续是错的。

    `today_only=False` 可以关掉这个检查（调试用）。
    """
    if not CKPT.exists():
        return None
    try:
        d = json.loads(CKPT.read_text(encoding="utf-8"))
    except Exception:
        return None
    if agent and d.get("agent") and d["agent"] != agent:
        print(f"  ⚠ 断点是「{d['agent']}」的，不是「{agent}」，忽略")
        return None
    if today_only:
        _ts = str(d.get("ts") or "")
        _today = time.strftime("%Y-%m-%d")
        if _ts[:10] != _today:
            print(f"  ⚠ 断点是 {_ts[:10] or '（无日期）'} 的，不是今天（{_today}）—— 忽略")
            print(f"     每日养成的断点只当天有效。要接着跑就重跑一遍（不加 --resume）")
            return None
    return d


def clear() -> None:
    try:
        CKPT.unlink()
    except Exception:
        pass


def on_focus_lost(hwnd: int, wait_seconds: float = 300.0,
                  label: str = "") -> bool:
    """失焦时调用：提示 + 等用户切回来。

    返回 True = 用户切回来了，继续；False = 等超时，该存断点退出。

    **不抛异常** —— 失焦是正常的，不是错误。
    """
    print()
    print("=" * 68)
    print("⏸  窗口失焦，已暂停" + (f"（步骤：{label}）" if label else ""))
    print("=" * 68)
    print("  你把游戏窗口切到后台了（或者有别的窗口抢了焦点）。")
    print("  我停下来等你 —— **不会乱点**。")
    print()
    print(f"  切回游戏窗口就自动继续（最多等 {int(wait_seconds)} 秒）")
    print("  想放弃就按 Ctrl+C，我会存断点，下次 --resume 接着跑")
    print()

    t0 = time.time()
    last_note = 0.0
    while time.time() - t0 < wait_seconds:
        if focus.is_active(hwnd):
            print(f"  ✔ 窗口回来了（等了 {time.time() - t0:.0f} 秒），继续")
            print()
            return True
        elapsed = time.time() - t0
        if elapsed - last_note >= 15:
            last_note = elapsed
            sys.stdout.write(f"\r  还在等… {elapsed:.0f}s / {wait_seconds:.0f}s   ")
            sys.stdout.flush()
        time.sleep(0.4)

    print()
    print(f"  ✘ 等了 {wait_seconds:.0f} 秒还是没回来")
    return False
