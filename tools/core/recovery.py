"""看门狗 + 全局复位：任何一步卡住都能自己爬起来。

设计
====
* `watchdog(seconds)` 上下文管理器：超时抛 TimeoutError
* `reset_to_world()`：无脑把界面退回大世界（连按 B / ESC，直到出现锚点）
* `guard(fn, retries)`：执行一个动作，失败重试，连续失败进入复位

有了这三样，长时间无人值守才可能。
"""
from __future__ import annotations

import contextlib
import signal
import threading
import time
from typing import Callable

from . import anchors


class WatchdogTimeout(Exception):
    pass


@contextlib.contextmanager
def watchdog(seconds: float, label: str = ""):
    """超时中断。Windows 上用线程定时器实现（signal.alarm 不可用）。"""
    fired = {"v": False}

    def _kill():
        fired["v"] = True

    t = threading.Timer(seconds, _kill)
    t.daemon = True
    t.start()
    try:
        yield fired
    finally:
        t.cancel()


def reset_to_world(ui, limit: int = 12) -> bool:
    """把界面无脑退回大世界。

    策略：先按 B（退出各类面板），再按 ESC（退出菜单），
    每轮检查锚点。返回是否成功。
    """
    for i in range(limit):
        if anchors.is_(ui.vs, "世界"):
            ui.inp.mouse_mode()
            return True
        if i % 2 == 0:
            ui.inp.pad_tap("b", wait=0.85)
        else:
            ui.inp.key(0x1B, wait=0.85)     # ESC
        ui.vs.frame(force=True)
    if anchors.is_(ui.vs, "世界"):
        ui.inp.mouse_mode()
        return True
    print("  [recovery] 回大世界失败")
    return False


def guard(fn: Callable, *, retries: int = 3, ui=None,
          label: str = "", on_fail_reset: bool = True) -> bool:
    """执行动作，失败重试；连续失败则复位。返回是否最终成功。"""
    for i in range(retries):
        try:
            if fn():
                return True
        except WatchdogTimeout as e:
            print(f"  [guard] {label} 超时：{e}")
        except Exception as e:
            print(f"  [guard] {label} 异常：{e}")
        print(f"  [guard] {label} 第 {i + 1}/{retries} 次失败")
        time.sleep(0.6)
        if ui is not None and on_fail_reset:
            reset_to_world(ui)
    return False
