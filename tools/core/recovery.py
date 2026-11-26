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
    # **连判 3 次才算到世界**（RT-REPORT 柱 2）。
    #
    # 原来只判一帧。单帧可能是过渡动画的中间态 ——
    # 认出来了但其实是半截画面，返回后 `describe()` 又变成别的界面，
    # 上层于是「再复位一次」，每次导航白烧 20~30 秒。
    #
    # `_at_world()` 会刷新 3 帧，**全部**认出「世界」才算数。
    # 被遮挡时 `is_()` 一律 False（BUG-032），所以这里也自然等下去。
    def _at_world(tries: int = 3) -> bool:
        for k in range(tries):
            ui.vs.frame(force=True)
            if not anchors.is_(ui.vs, "世界"):
                return False
            time.sleep(0.12)
        return True

    # **左上角返回箭头**的固定坐标（1920x1080）。
    #
    # 实测：代理人详情页（装备/技能/基础）**不响应 ESC 也不响应 B** ——
    # 连按 12 次画面一点没动（21 秒白烧）。
    # 必须点左上角那个圆形返回箭头，实测 @(96,47)。
    XY_BACK = (96, 47)

    for i in range(limit):
        if _at_world():
            ui.inp.mouse_mode()
            return True
        ui.vs.frame(force=True)
        # 代理人详情页：点左上角返回箭头（ESC 对它无效）
        try:
            _top = ui.vs.text((150, 20, 700, 110))
        except Exception:
            _top = ""
        # **过渡中别按键，等着**（2026-11-27 实测）。
        #
        # 实测主菜单的退出过程：
        #   主菜单 --B--> 「未知界面」（过渡）--ESC--> 世界
        # 也就是说**按完 B 会先经过一个「未知界面」阶段**。
        # 原来这时候下一轮立刻又按键 —— 把过渡打断，于是永远退不出去
        # （实测卡在主菜单 50 秒，12 轮全白烧）。
        #
        # 现在：认出「未知界面」就先等它稳，等到了世界就直接返回，
        # 等不到再按键。
        try:
            _cur = anchors.describe(ui.vs)
        except Exception:
            _cur = ""
        if _cur == "未知界面":
            for _w in range(6):                 # 最多等 6 × 0.6 = 3.6 秒
                ui.vs.frame(force=True)
                if anchors.is_(ui.vs, "世界"):
                    ui.inp.mouse_mode()
                    return True
                time.sleep(0.6)
            # 等不到才继续按

        if "代理人攻略" in _top:
            ui.inp.click(XY_BACK[0], XY_BACK[1], wait=1.4)
        elif i % 2 == 0:
            ui.inp.pad_tap("b", wait=1.6)       # 按键后多给点时间过过渡
        else:
            ui.inp.key(0x1B, wait=1.6)          # ESC
        ui.vs.frame(force=True)
    if _at_world():
        ui.inp.mouse_mode()
        return True
    # 失败时把「为什么」说清楚，别只说「回大世界失败」
    try:
        got = anchors.describe(ui.vs)
    except Exception:
        got = "?"
    print(f"  [recovery] 回大世界失败（当前界面：{got}）")
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
