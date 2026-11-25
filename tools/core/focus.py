"""窗口焦点保护。

## 为什么需要（用户 2026-11-25 23:47 实测）

> 在跑这个日常养成的过程中，如果我鼠标动了呢？
> 我刚才看到你因为我点，然后把这个绝区零的窗口推到后台了，
> 然后导致整个任务直接卡住。还有我中途也动了几下鼠标，也导致它卡住了。

## 原来的问题

`core/input.py` 里**没有任何焦点检查** —— `click()` 直接 `SetCursorPos` + `mouse_event`。

窗口被推到后台时：
- 点击落在**浏览器/桌面**上（不是游戏里）
- 工具不知道，继续按脚本往下走
- 后续读画面全部读到别人的窗口 → 判断全错 → **看起来「卡住」**

**比卡住更糟**：它在乱点别人的窗口。

## 三个能力

1. **`is_active(hwnd)`** —— 游戏窗口是不是当前前台窗口
2. **`ensure(hwnd, tries)`** —— 抢回前台；抢不回来抛 `FocusLost`
3. **`FocusLost`** —— 上层可捕获，决定「等一下」还是「放弃」

## 设计原则

**注入输入前必须确认焦点在游戏上。** 一次检查几微秒，比点错窗口便宜得多。

但**不要每次点击都抢前台** —— 抢前台本身是副作用（会把用户的窗口顶掉）。
所以：**只在失焦时才抢**，而且抢的次数有上限。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.windll.user32

SW_RESTORE = 9


class FocusLost(RuntimeError):
    """游戏窗口失去了前台焦点，而且抢不回来。"""


def active_hwnd() -> int:
    """当前前台窗口的句柄。"""
    try:
        return int(user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def is_active(hwnd: int) -> bool:
    """游戏窗口是不是当前前台窗口。"""
    if not hwnd:
        return False
    return active_hwnd() == int(hwnd)


def is_game(hwnd: int, game_hwnd: int) -> bool:
    """前台窗口是不是游戏（允许子窗口）。"""
    return bool(hwnd) and int(hwnd) == int(game_hwnd)


def bring_to_front(hwnd: int, wait: float = 0.35) -> bool:
    """把窗口抢到前台。**只在失焦时调用** —— 抢前台会把用户的窗口顶掉。"""
    if not hwnd:
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.2)
        user32.SetForegroundWindow(hwnd)
        time.sleep(wait)
        return is_active(hwnd)
    except Exception:
        return False


def ensure(hwnd: int, *, tries: int = 2, wait: float = 0.35,
           raise_on_fail: bool = True) -> bool:
    """确保游戏在前台。

    先查（便宜），失焦才抢（有副作用）。抢 `tries` 次还不行就抛 `FocusLost`。

    **不要每帧都调** —— 只在「要注入输入」和「要读画面」之前调。
    """
    if is_active(hwnd):
        return True
    for _ in range(max(1, tries)):
        if bring_to_front(hwnd, wait):
            return True
    if raise_on_fail:
        raise FocusLost(
            "游戏窗口不在前台，抢不回来。\n"
            "  可能原因：别的窗口一直抢焦点（弹窗广告 / 输入法候选框 / 远程桌面）\n"
            "  怎么办：手动点一下游戏窗口，或先关掉抢焦点的程序，再继续")
    return False


def wait_active(hwnd: int, timeout: float = 60.0, interval: float = 0.5,
                on_wait=None) -> bool:
    """等游戏回到前台，最多 timeout 秒。

    用于「用户切走了，等他切回来」这种场景 —— 不抛异常，等不到返回 False。

    on_wait: 每次等待时回调（打日志用），签名 on_wait(已等秒数)
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if is_active(hwnd):
            return True
        if on_wait:
            try:
                on_wait(time.time() - t0)
            except Exception:
                pass
        time.sleep(interval)
    return is_active(hwnd)
