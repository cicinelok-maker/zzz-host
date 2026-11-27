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


# **`watchdog()` 已经删掉了**（RT-24）。
#
# 它原来长这样：
#
#     @contextlib.contextmanager
#     def watchdog(seconds, label=""):
#         """超时中断。Windows 上用线程定时器实现。"""
#         fired = {"v": False}
#         def _kill(): fired["v"] = True
#         t = threading.Timer(seconds, _kill); t.start()
#         try: yield fired
#         finally: t.cancel()
#
# **名字和 docstring 都说「超时中断」，实际只是设了一个标志位。**
# Python 的线程定时器**打断不了**正在阻塞的调用（OCR、点击、等窗口），
# 而全仓**没有任何地方检查 `fired["v"]`** —— 所以它连「标记」都没起作用。
#
# 留着的害处：看到 `with watchdog(60):` 会以为这里有超时保护，
# 实际上什么保护都没有。**一个让人误以为安全的东西，比没有更糟。**
#
# 真要超时，得在**等待循环内部**判时间（`wait_for(..., timeout=)` 就是那样做的）。
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
        # 统一走 `anchors.at`（三帧取两帧）。
        # 原来这里是「三帧**全中**」—— 太严：OCR 抖一下（技能页的「影画」
        # 偶尔读不出）就判 False，然后上层以为「没到世界」，白烧时间。
        return anchors.at(ui.vs, "世界", tries=tries, need=2)

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
    """执行动作，失败重试；连续失败则复位。返回是否最终成功。

    ## **目前没有调用方**（RT-24）

    这是个能用的实现（重试 + 复位 + 记日志），但全仓**一处都没调**。
    审计把它和 `watchdog()` 一起列为「空壳且零调用」—— 对
    `watchdog()` 它是准确的（已删），对这里只对了一半：
    **实现是真的，只是没接上**。

    想用的时候：套在「一个动作 + 一次校验」外面，比如

        ok = guard(lambda: ui.click_text("确认", R) and vs.has(R, "已确认"),
                   retries=2, ui=ui, label="点确认")

    注意它会**在连续失败后调 `reset_to_world()`** ——
    在「不该退出当前界面」的流程里要传 `on_fail_reset=False`。
    """
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
