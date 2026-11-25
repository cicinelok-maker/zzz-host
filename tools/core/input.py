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
sys.path.insert(0, r"E:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full\plugins")

import live  # noqa: E402
import vgamepad as vg  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)

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

    # ================= 模式 =================
    def mouse_mode(self, wait: float = 0.25) -> None:
        """切到键鼠态。UI 自动化开始前调一次即可。

        原理：在游戏窗口内做几次真实鼠标移动（MOUSEEVENTF_MOVE），
        游戏会把「最后一次输入设备」判定为鼠标。
        """
        cx, cy = self.ox + 960, self.oy + 540
        user32.SetCursorPos(cx, cy)
        time.sleep(0.08)
        for dx, dy in ((18, 0), (-18, 0), (0, 14), (0, -14), (12, 12), (-12, -12)):
            user32.mouse_event(MOVE, dx, dy, 0, 0)
            time.sleep(0.03)
        user32.SetCursorPos(cx, cy)
        time.sleep(wait)
        self.mode = "mouse"

    def pad_mode(self, wait: float = 0.4) -> None:
        """切到手柄态（战斗、摄像机操作用）。"""
        self._press_pad("up", gap=0.08)
        time.sleep(wait)
        self.mode = "pad"

    # ================= 鼠标 =================
    def move(self, x: int, y: int) -> None:
        user32.SetCursorPos(self.ox + x, self.oy + y)
        time.sleep(0.06)

    def click(self, x: int, y: int, *, wait: float = 0.35,
              hold: float = 0.06, button: str = "left") -> None:
        """点击游戏内坐标。默认参数是实测下来最稳的。"""
        user32.SetCursorPos(self.ox + x, self.oy + y)
        time.sleep(0.05)
        down, up = (LDOWN, LUP) if button == "left" else (RDOWN, RUP)
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(_jit(hold, 0.35) if self.jitter else hold)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "mouse"

    def click_item(self, item: dict, **kw) -> None:
        """点一个 OCR 结果（含 cx/cy）"""
        self.click(item["cx"], item["cy"], **kw)

    def double_click(self, x: int, y: int, wait: float = 0.4) -> None:
        self.click(x, y, wait=0.06, hold=0.04)
        self.click(x, y, wait=wait, hold=0.04)

    def right_click(self, x: int, y: int, wait: float = 0.35) -> None:
        self.click(x, y, wait=wait, button="right")

    def wheel(self, notches: int, *, wait: float = 0.45) -> None:
        """滚轮：正数向上，负数向下。一格 = 120。"""
        user32.mouse_event(WHEEL, 0, 0, int(notches * 120), 0)
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "mouse"

    def drag(self, x1: int, y1: int, x2: int, y2: int, *,
             steps: int = 14, wait: float = 0.4, hold_before: float = 0.12) -> None:
        """按住从左点拖到右点（拖滚动条、滑块、列表）。"""
        user32.SetCursorPos(self.ox + x1, self.oy + y1)
        time.sleep(0.08)
        user32.mouse_event(LDOWN, 0, 0, 0, 0)
        time.sleep(hold_before)
        for i in range(1, steps + 1):
            x = int(x1 + (x2 - x1) * i / steps)
            y = int(y1 + (y2 - y1) * i / steps)
            user32.SetCursorPos(self.ox + x, self.oy + y)
            time.sleep(0.025)
        time.sleep(0.10)
        user32.mouse_event(LUP, 0, 0, 0, 0)
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "mouse"

    # ================= 手柄 =================
    def _press_pad(self, button: str, gap: float = 0.05, hold: float = 0.09) -> None:
        b = PAD[button]
        self._pad.press_button(b)
        self._pad.update()
        time.sleep(hold)
        self._pad.release_button(b)
        self._pad.update()
        time.sleep(gap)

    def pad_tap(self, button: str, *, wait: float = 0.45) -> None:
        self._press_pad(button)
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "pad"

    def pad_taps(self, button: str, n: int, *, wait: float = 0.3) -> None:
        for _ in range(n):
            self._press_pad(button, gap=wait)
        self.mode = "pad"

    def pad_trigger(self, side: str = "rt", value: int = 255, *, wait: float = 0.4) -> None:
        fn = self._pad.right_trigger if side == "rt" else self._pad.left_trigger
        fn(value=value)
        self._pad.update()
        time.sleep(0.09)
        fn(value=0)
        self._pad.update()
        time.sleep(wait)
        self.mode = "pad"

    def pad_stick(self, x: float, y: float, *, hold: float = 0.4) -> None:
        """左摇杆推一下（-1~1），用于角色移动/摄像机"""
        self._pad.left_joystick_float(x_value_float=x, y_value_float=y)
        self._pad.update()
        time.sleep(hold)
        self._pad.left_joystick_float(x_value_float=0, y_value_float=0)
        self._pad.update()

    # ================= 键盘 =================
    def key(self, key, *, wait: float = 0.3, hold: float = 0.06) -> None:
        """按键。key 可以是名字（"esc"/"tab"…）或扫描码整数。

        **必须用扫描码**：实测游戏只认 KEYEVENTF_SCANCODE 形式的 SendInput，
        keybd_event 和虚拟键码形式都无效。
        """
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
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
        time.sleep(_jit(hold, 0.3) if self.jitter else hold)
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))
        time.sleep(_jit(wait) if self.jitter else wait)
        self.mode = "mouse"

    def hold_key(self, key, seconds: float = 0.6) -> None:
        """按住某个键一段时间（走路用）"""
        scan = _scan(key)
        if not scan:
            return
        down = _INPUT(type=INPUT_KEYBOARD)
        down.u.ki = _KEYBDINPUT(wVk=0, wScan=scan, dwFlags=KEYEVENTF_SCANCODE,
                                time=0, dwExtraInfo=None)
        up = _INPUT(type=INPUT_KEYBOARD)
        up.u.ki = _KEYBDINPUT(wVk=0, wScan=scan,
                              dwFlags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP,
                              time=0, dwExtraInfo=None)
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
        time.sleep(seconds)
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))
        time.sleep(0.1)
        self.mode = "mouse"

    def type_text(self, text: str, *, wait: float = 0.4) -> None:
        """逐字符输入（ASCII；中文需用剪贴板）"""
        for ch in text:
            vk = user32.VkKeyScanW(ord(ch)) & 0xFF
            if vk == 0xFF:
                continue
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.01)
            user32.keybd_event(vk, 0, 2, 0)
            time.sleep(0.02)
        time.sleep(wait)
