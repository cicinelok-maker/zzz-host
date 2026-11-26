"""底层输入层：以鼠标为主路径，手柄只在必要时使用。

## 实测能力矩阵（2026-11-22，1920x1080）

    ┌──────────────────┬──────┬────────────────────────────┐
    │ 鼠标滚轮（键鼠态）│  ✔   │ 网格列表可滚动，能还原       │
    │ 鼠标点击          │  ✔   │ 点卡片会切换右侧详情面板     │
    │ 鼠标拖拽          │  ✔   │ 拖右侧滚动条有效            │
    │ 鼠标移动          │  ✔   │ 用于切键鼠态                │
    │ 手柄方向键        │  ✔   │ 手柄态下有效                │
    │ 手柄态下滚轮      │  ✘   │ 符合预期                    │
    │ 键盘按键          │  ✔   │ 不崩                        │
    └──────────────────┴──────┴────────────────────────────┘

结论：**UI 自动化全程只用鼠标就够了**，不需要来回切换输入模式。
      （之前认为滚轮无效，是因为游戏处在手柄态。）

## 输入模式的真相

    * 游戏跟随「最后一次输入设备」切换键鼠态 / 手柄态
    * 手柄态下鼠标点击、滚轮、拖拽全部无效
    * 键鼠态下方向键无效
    * 合成鼠标移动（MOUSEEVENTF_MOVE）足以让游戏切到键鼠态

因此本模块的策略：
    启动时调用一次 `mouse_mode()`，之后所有 UI 操作都走鼠标；
    需要手柄时（战斗、摄像机）才用 `pad_*`，用完记得 `mouse_mode()` 切回来。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
# 不硬编码本机路径 —— 用 core.paths 探测（别人的 OneDragon 不在这）
try:
    from core.paths import one_dragon_home as _odh
    _od = _odh()
    if _od:
        for _sub in ("src", "plugins"):
            _p = str(__import__("pathlib").Path(_od) / _sub)
            if __import__("pathlib").Path(_p).is_dir():
                sys.path.insert(0, _p)
except Exception:
    pass

import live
from . import focus  # noqa: E402
import vgamepad as vg  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)


# ============================================================ 输入注入失败

class InputBlocked(RuntimeError):
    """SendInput 被系统拒绝 —— 几乎总是「没以管理员身份运行」。

    Windows 的 UIPI（User Interface Privilege Isolation）会静默丢弃
    低完整性级别进程往高完整性级别窗口注入的输入。
    **实测：UIPI 拦截时 SendInput 返回 1（成功），只有 GetLastError 是 5。**
    消息是在目标的输入队列那侧被丢的，调用本身「成功」了。
    """


def _admin_hint() -> str:
    return ("  以管理员身份运行（右键终端 → 以管理员身份运行，"
            "或用项目的 .\\admin.ps1）")


ERROR_ACCESS_DENIED = 5


def check_send(ok: int, what: str, err: int | None = None) -> None:
    """输入注入失败就抛 InputBlocked。

    **两个信号都要看**（实测总结）：
      · SendInput 返回 0     → 插入失败（极端情况，比如队列满）
      · GetLastError == 5    → UIPI 拦了。**这种情况 SendInput 返回 1**，
                               因为调用本身「成功送达系统」了，
                               消息是在目标的输入队列那边被丢的。

    所以只判返回值是不够的 —— 这是第一版的错误。

    调用前必须 `ctypes.set_last_error(0)`，否则上一把的 5 会误报。
    """
    if err is None:
        err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
    if ok and err != ERROR_ACCESS_DENIED:
        return
    why = ("被 Windows UIPI 拦了（进程权限低于游戏）"
           if err == ERROR_ACCESS_DENIED else "系统拒绝插入事件")
    msg = [f"✘ 输入注入失败：{what} {why}"]
    msg.append(_admin_hint())
    msg.append("  症状：不会报错，而是白等到超时（实测 150~254 秒）")
    raise InputBlocked("\n".join(msg))


def is_admin() -> bool:
    """当前进程是不是管理员。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


MOVE = 0x0001
LDOWN, LUP = 0x0002, 0x0004
RDOWN, RUP = 0x0008, 0x0010
WHEEL = 0x0800
WHEEL_H = 0x01000



# ============ 键盘：必须用「扫描码」形式 ============
# 实测：游戏只认 scancode 的 SendInput，
#       keybd_event 和虚拟键码形式的 SendInput 都无效。
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.wintypes.WORD), ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD), ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.wintypes.DWORD), ("u", _INPUTunion)]


# 常用键的扫描码
SCANCODES = {
    "esc": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    # 移动
    "q": 0x10, "e": 0x12, "r": 0x13, "f": 0x21,
    "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20,
    "shift": 0x2A, "space": 0x39,
    "tab": 0x0F, "enter": 0x1C, "ctrl": 0x1D, "alt": 0x38,
    "tilde": 0x29, "grave": 0x29, "backspace": 0x0E,
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D,
    "up": 0x48, "left": 0x4B, "right": 0x4D, "down": 0x50,
    # 数字键
    "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
}


def _scan(vk_or_name) -> int:
    if isinstance(vk_or_name, int):
        return vk_or_name
    return SCANCODES.get(str(vk_or_name).lower(), 0)


PAD = {
    "a": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "b": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "x": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "start": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "back": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "lb": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "rb": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "up": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "down": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "left": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "right": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
}


def _jit(base: float, ratio: float = 0.3) -> float:
    """给等待时间加随机抖动。机械的固定间隔偶尔会丢事件，人的操作本来就有波动。"""
    if base <= 0:
        return 0.0
    return base * (1.0 + random.uniform(-ratio, ratio))


class Input:
    """所有输入的唯一入口。坐标一律是游戏内像素坐标（1920x1080）。

    所有等待时间都带 ±30% 随机抖动，更接近真人节奏，也避免固定间隔踩到动画节拍。
    """

    def __init__(self, jitter: bool = True):
        self.jitter = jitter
        user32.SetProcessDPIAware()
        self.win = live.find_window()
        if not self.win:
            raise RuntimeError("没找到游戏窗口")
        self.ox, self.oy = self.win["x"], self.win["y"]
        # 窗口句柄 —— 每次注入输入前要用它确认游戏在前台。
        # 窗口被推到后台时，点击会落在别的程序上（用户实测踩过）。
        self.hwnd = self.win.get("hwnd") or 0
        # 焦点检查开关：调试时可以关（比如故意在后台测坐标换算）
        self.guard = True
        # 不在初始化时创建虚拟手柄：VX360Gamepad() 一构造，Windows 就会
        # 报告「新控制器已连接」，游戏弹窗；进程退出又弹「已断开」。
        # 改成懒加载——第一次真正需要按手柄键时才建，
        # 只用键鼠的流程就不会弹这个窗。
        self._pad_obj = None
        self.mode = "unknown"

    @property
    def _pad(self):
        """第一次用的时候才创建虚拟手柄（避免不必要的控制器连接弹窗）。"""
        if self._pad_obj is None:
            self._pad_obj = vg.VX360Gamepad()
        return self._pad_obj

    def _guard(self, what: str = "") -> None:
        """注入输入前确认游戏在前台。

        失焦时先尝试抢回来（最多 2 次）；抢不回来抛 `focus.FocusLost`，
        上层可以决定「等一下」还是「放弃」。

        **不静默跳过** —— 静默跳过会让脚本以为点过了，继续往下走，
        后面读画面全错，表现成「卡住」。
        """
        if not self.guard or not self.hwnd:
            return
        if focus.is_active(self.hwnd):
            return
        # 失焦了 —— 尝试抢回来
        if focus.ensure(self.hwnd, tries=2, raise_on_fail=False):
            return
        raise focus.FocusLost(
            f"游戏窗口不在前台（要做的动作：{what or '输入'}）\n"
            f"  当前前台窗口句柄：{focus.active_hwnd()}，游戏：{self.hwnd}\n"
            "  抢了 2 次没抢回来。可能别的程序一直抢焦点。\n"
            "  怎么办：手动点一下游戏窗口，然后重跑（或加 --resume 从断点继续）")

    def refocus(self) -> bool:
        """外部显式抢前台（Ui.start 用）。失败不抛，返回 bool。"""
        if not self.hwnd:
            return True
        return focus.ensure(self.hwnd, tries=3, raise_on_fail=False)

    # ================= 模式 =================
    def mouse_mode(self, wait: float = 0.25) -> None:
        """切到键鼠态。UI 自动化开始前调一次即可。

        原理：在游戏窗口内做几次真实鼠标移动（MOUSEEVENTF_MOVE），
        游戏会把「最后一次输入设备」判定为鼠标。
        """
        self._guard("切键鼠态")
        cx, cy = self.ox + 960, self.oy + 540
        user32.SetCursorPos(cx, cy)
        time.sleep(0.08)
        for dx, dy in ((18, 0), (-18, 0), (0, 14), (0, -14), (12, 12), (-12, -12)):
            user32.mouse_event(MOVE, dx, dy, 0, 0)
            time.sleep(0.03)
        user32.SetCursorPos(cx, cy)
        time.sleep(wait)
        self.mode = "mouse"

    def move(self, x: int, y: int) -> None:
        self._guard("移动鼠标")
        user32.SetCursorPos(self.ox + x, self.oy + y)
        time.sleep(0.06)

    def click(self, x: int, y: int, *, wait: float = 0.35,
              hold: float = 0.06, button: str = "left") -> None:
        """点击游戏内坐标。默认参数是实测下来最稳的。"""
        self._guard("点击")
        if not user32.SetCursorPos(self.ox + x, self.oy + y):
            check_send(0, f'鼠标移到 ({x},{y})')
        time.sleep(0.05)
        down, up = (LDOWN, LUP) if button == "left" else (RDOWN, RUP)
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(_jit(hold, 0.35) if self.jitter else hold)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "mouse"


    def drag(self, x1: int, y1: int, x2: int, y2: int, *,
             wait: float = 0.4, hold: float = 0.12,
             steps: int = 12, button: str = "left") -> None:
        """按住从 (x1,y1) 拖到 (x2,y2)，然后松开。

        ## 为什么要分段移动

        游戏是按「鼠标移动事件」跟进拖拽的。**一步跳到终点会丢中间过程**，
        滑块可能完全不动（实测过）。

        所以拆成 `steps` 段，每段之间 sleep 几毫秒，让游戏能跟上。

        ## 用途

        养成指南 →「养成材料计算」→ 技能等级那 6 个滑块，
        要把拇指从当前位置拖到最右端（目标等级）。

        用法：
        ```python
        inp.drag(thumb_x, row_y, track_right_x, row_y)
        ```
        """
        self._guard("拖拽")
        down, up = (LDOWN, LUP) if button == "left" else (RDOWN, RUP)

        if not user32.SetCursorPos(self.ox + x1, self.oy + y1):
            check_send(0, f"鼠标移到 ({x1},{y1})")
        time.sleep(0.06)
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(hold)

        for k in range(1, steps + 1):
            nx = x1 + (x2 - x1) * k // steps
            ny = y1 + (y2 - y1) * k // steps
            user32.SetCursorPos(self.ox + nx, self.oy + ny)
            time.sleep(0.02)

        time.sleep(0.06)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "mouse"

    def click_item(self, item: dict, **kw) -> None:
        """点一个 OCR 结果（含 cx/cy）"""
        self._guard("点列表项")
        self.click(item["cx"], item["cy"], **kw)



    def wheel(self, notches: int, *, wait: float = 0.45) -> None:
        """滚轮：正数向上，负数向下。一格 = 120。"""
        self._guard("滚轮")
        user32.mouse_event(WHEEL, 0, 0, int(notches * 120), 0)
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "mouse"

    def _press_pad(self, button: str, gap: float = 0.05, hold: float = 0.09) -> None:
        b = PAD[button]
        self._pad.press_button(b)
        self._pad.update()
        time.sleep(hold)
        self._pad.release_button(b)
        self._pad.update()
        time.sleep(gap)

    def pad_tap(self, button: str, *, wait: float = 0.45) -> None:
        self._guard("手柄按键")
        self._press_pad(button)
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "pad"

    def pad_taps(self, button: str, n: int, *, wait: float = 0.3) -> None:
        self._guard("手柄连按")
        for _ in range(n):
            self._press_pad(button, gap=wait)
        self.mode = "pad"


    def key(self, key, *, wait: float = 0.3, hold: float = 0.06) -> None:
        """按键。key 可以是名字（"esc"/"tab"…）或扫描码整数。

        **必须用扫描码**：实测游戏只认 KEYEVENTF_SCANCODE 形式的 SendInput，
        keybd_event 和虚拟键码形式都无效。
        """
        self._guard("按键")
        scan = _scan(key)
        if not scan:
            return
        down = _INPUT(type=INPUT_KEYBOARD)
        down.u.ki = _KEYBDINPUT(wVk=0, wScan=scan,
                                dwFlags=KEYEVENTF_SCANCODE,
                                time=0, dwExtraInfo=None)
        up = _INPUT(type=INPUT_KEYBOARD)
        up.u.ki = _KEYBDINPUT(wVk=0, wScan=scan,
                              dwFlags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP,
                              time=0, dwExtraInfo=None)
        ctypes.set_last_error(0)
        n1 = user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
        time.sleep(_jit(hold, 0.3) if self.jitter else hold)
        ctypes.set_last_error(0)
        n2 = user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))
        check_send(min(n1, n2), f"按键 {key}")
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "mouse"
