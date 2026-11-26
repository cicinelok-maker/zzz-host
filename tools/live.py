"""真机操作：识屏 → 点文字/模板 → 再截一张确认。

    python tools/live.py --probe
    python tools/live.py --click-text "点击进入游戏"
    python tools/live.py --click-tpl normal_world/function_menu
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import random
import sys
import time
from pathlib import Path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import numpy as np
from PIL import ImageGrab
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

user32 = ctypes.windll.user32
SHOTS = Path(__file__).resolve().parent.parent / "od_test" / "shots"
TOKENS = ("绝区零", "Zenless", "ZZZ")
BLOCK = ("deepseek", "harness", "vscode", "chrome", "edge",
         "scanner", "scanner next", "计算器", "记事本")

# 游戏客户端固定 1920x1080，不可能更小。
# 低于这个尺寸的一定不是游戏窗口（实测「ZZZ Scanner Next」是 430x560）。
MIN_W, MIN_H = 1280, 720

# 标题完全等于这个才是最可信的匹配
EXACT_TITLE = "绝区零"


# **进程名是比窗口标题更硬的证据**（BUG-030）。
# 标题在加载/全屏切换时可能短暂变空或变成别的文字，进程名不会变。
GAME_EXE = "zenlesszonezero.exe"


def _proc_name(hwnd) -> str:
    """取窗口所属进程的可执行文件名（小写）。取不到返回空串。"""
    try:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        k32 = ctypes.windll.kernel32
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return ""
            return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            k32.CloseHandle(h)
    except Exception:
        return ""


# ---------------------------------------------------------------- 窗口
def find_window(_restore_minimized: bool = True) -> dict | None:
    hits = []
    minimized = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        low = title.lower()
        # 类名优先：Unity 客户端固定是 UnityWndClass，绝不会和聊天窗口混淆
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        is_unity = "unity" in cls.value.lower()

        # **标题或进程名必须证明它是绝区零**（BUG-030）。
        #
        # 原来 `if not is_unity and (...)` —— Unity 类名直接短路掉整段校验，
        # 任何 Unity 窗口（编辑器、别的 Unity 游戏）都被当成游戏本体，
        # 键鼠注入就落到那个程序上了。
        #
        # 现在 is_unity 只是加分项，不再是通行证。
        title_hit = any(t.lower() in low for t in TOKENS)
        proc_hit = _proc_name(hwnd) == GAME_EXE
        if any(b in low for b in BLOCK):
            return True                       # 黑名单永远排除
        if not (title_hit or proc_hit):
            return True                       # 认不出是绝区零 → 跳过
        r = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        cw, ch = r.right - r.left, r.bottom - r.top
        if cw < MIN_W or ch < MIN_H:
            # 尺寸不够：只有「标题命中 + Unity 类名」才当「被最小化的游戏」
            if is_unity and title_hit:
                minimized.append(hwnd)
            return True
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        hits.append({"hwnd": hwnd, "title": title, "x": pt.x, "y": pt.y,
                     "w": cw, "h": ch, "unity": is_unity,
                     "title_hit": title_hit, "proc_hit": proc_hit})
        return True

    user32.EnumWindows(_cb, 0)
    # 排序：精确标题 > Unity 类名 > 面积
    # 排序：精确标题 > 进程名命中 > Unity 类名 > 面积
    hits.sort(key=lambda h: (h["title"] != EXACT_TITLE,
                             not h.get("proc_hit"),
                             not h["unity"],
                             -h["w"] * h["h"]))
    if not hits and minimized and _restore_minimized:
        for hwnd in minimized:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            try:
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
        time.sleep(0.3)
        return find_window(False)
    return hits[0] if hits else None


def grab(win) -> np.ndarray:
    box = (win["x"], win["y"], win["x"] + win["w"], win["y"] + win["h"])
    return np.array(ImageGrab.grab(bbox=box, all_screens=True).convert("RGB"))[:, :, ::-1]


def foreground(win) -> bool:
    """把游戏抢到前台并**验证**，返回是否真的拿到了前台。"""
    for _ in range(3):
        if user32.GetForegroundWindow() == win["hwnd"]:
            return True
        user32.ShowWindow(win["hwnd"], 9)
        try:
            user32.SetForegroundWindow(win["hwnd"])
        except Exception:
            pass
        if user32.GetForegroundWindow() == win["hwnd"]:
            return True
        # 前台锁：ALT 抖一下解锁再抢
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(win["hwnd"])
        user32.keybd_event(0x12, 0, 2, 0)
        time.sleep(0.3)
    return user32.GetForegroundWindow() == win["hwnd"]


# ---------------------------------------------------------------- 输入
def scale(win, x: int, y: int) -> tuple:
    """标准 1080p 坐标 → 当前客户区坐标 → 屏幕坐标"""
    kx = win["w"] / 1920.0
    ky = win["h"] / 1080.0
    return int(win["x"] + x * kx), int(win["y"] + y * ky)


def click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(random.uniform(0.05, 0.12))
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(random.uniform(0.05, 0.11))
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def ocr_items(ocr, img):
    return ocr.ocr(img) or []


def pick(items, keyword: str):
    try:
        from agent_growth.core.navigator import pick_text
    except ImportError:
        print("✘ 这个功能需要 agent_growth / pyautogui，发布版没有")
        print("   本地开发才有：pip install pyautogui + od_plugin/agent_growth")
        return 2
    return pick_text(
        [{"text": getattr(i, "data", ""), "c": 0.9,
          "center": (int(i.center.x), int(i.center.y))} for i in items], keyword)



def enter_game(win, ocr) -> int:
    """从标题页进入游戏：校验前台 → 连点两次 → 等 12s → 看「点击进入游戏」还在不在"""
    ok = foreground(win)
    fg = user32.GetForegroundWindow()
    print(f"前台校验: {'✔' if ok else '✖'}  fg={fg}  game={win['hwnd']}")
    if not ok:
        return 4
    img = grab(win)
    hit = pick(ocr_items(ocr, img), "点击进入游戏")
    if not hit:
        print("不在标题页（没找到「点击进入游戏」）")
        return 0
    x, y = hit["center"]
    print(f"点 ({x},{y}) ×2")
    px, py = scale(win, x, y)
    click(px, py)
    time.sleep(0.8)
    click(px, py)
    time.sleep(12)
    after = grab(win)
    from PIL import Image
    Image.fromarray(after[:, :, ::-1]).save(SHOTS / "after_enter.png")
    still = pick(ocr_items(ocr, after), "点击进入游戏")
    print("12s 后还在标题页" if still else "✔ 已离开标题页，进入加载/主界面")
    return 0

def enter_loop(win, ocr, tries: int = 4, gap: float = 10.0) -> int:
    """ZZZ 要连点两次进入：第一次加载配置，第二次才真正进。反复点到标题页消失为止。"""
    try:
        import pyautogui
    except ImportError:
        print("✘ 这个功能需要 agent_growth / pyautogui，发布版没有")
        print("   本地开发才有：pip install pyautogui + od_plugin/agent_growth")
        return 2
    pyautogui.FAILSAFE = False
    for i in range(1, tries + 1):
        if not foreground(win):
            print("✖ 拿不到前台")
            return 4
        img = grab(win)
        hit = pick(ocr_items(ocr, img), "点击进入游戏")
        if not hit:
            print(f"第 {i} 次：标题页已消失 → 已在加载/主界面")
            return 0
        x, y = hit["center"]
        print(f"第 {i} 次点击 ({x},{y})")
        px, py = scale(win, x, y)
        pyautogui.moveTo(px, py, duration=0.22)
        time.sleep(0.15)
        pyautogui.click()
        time.sleep(gap)
    img = grab(win)
    from PIL import Image
    Image.fromarray(img[:, :, ::-1]).save(SHOTS / "enter_loop.png")
    print("4 次之后仍在标题页")
    return 5
def main() -> int:
    try:
        from agent_growth.core import preflight
    except ImportError:
        print("✘ 这个功能需要 agent_growth / pyautogui，发布版没有")
        print("   本地开发才有：pip install pyautogui + od_plugin/agent_growth")
        return 2
    ok, lines = preflight.report()
    print("\n".join(lines))
    if not ok:
        print("\n✖ 前置没满足，不测了（上面的 → 就是修法）")
        return 6

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--enter", action="store_true")
    ap.add_argument("--enter-loop", action="store_true")
    ap.add_argument("--click-text")
    ap.add_argument("--click-tpl")
    ap.add_argument("--shot", default="live")
    ap.add_argument("--wait", type=float, default=1.2)
    args = ap.parse_args()

    win = find_window()
    if not win:
        print("✖ 没找到游戏窗口")
        return 1
    print(f"窗口 «{win['title']}» {win['w']}x{win['h']} @({win['x']},{win['y']})")

    img = grab(win)
    SHOTS.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.fromarray(img[:, :, ::-1]).save(SHOTS / f"{args.shot}.png")

    from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher
    ocr = OnnxOcrMatcher()
    try:
        ocr.init_model(ocr_model_size="small")
    except Exception:
        ocr.init_model()
    items = ocr_items(ocr, img)

    if args.enter_loop:
        return enter_loop(win, ocr)
    if args.enter:
        return enter_game(win, ocr)

    if args.probe or not (args.click_text or args.click_tpl):
        print(f"\n■ OCR {len(items)} 条")
        for it in sorted(items, key=lambda i: (i.center.y, i.center.x)):
            print(f"  ({int(it.center.x):4d},{int(it.center.y):4d})  {it.data}")
        return 0

    if args.click_text:
        hit = pick(items, args.click_text)
        if not hit:
            print(f"✖ 界面上没有「{args.click_text}」")
            return 2
        x, y = hit["center"]
        print(f"→ 点「{args.click_text}」({x},{y})")
        foreground(win)
        click(win["x"] + x, win["y"] + y)
        time.sleep(args.wait)
        after = grab(win)
        Image.fromarray(after[:, :, ::-1]).save(SHOTS / f"{args.shot}_after.png")
        items2 = ocr_items(ocr, after)
        print(f"  点击后 OCR {len(items2)} 条：")
        for it in sorted(items2, key=lambda i: (i.center.y, i.center.x))[:15]:
            print(f"    ({int(it.center.x):4d},{int(it.center.y):4d})  {it.data}")
        return 0

    if args.click_tpl:
        try:
            from agent_growth.core.vision import TemplateBank
        except ImportError:
            print("✘ 这个功能需要 agent_growth / pyautogui，发布版没有")
            print("   本地开发才有：pip install pyautogui + od_plugin/agent_growth")
            return 2
        try:
            from agent_growth.core.navigator import _assets_root
        except ImportError:
            print("✘ 这个功能需要 agent_growth / pyautogui，发布版没有")
            print("   本地开发才有：pip install pyautogui + od_plugin/agent_growth")
            return 2
        bank = TemplateBank(Path("x"), fallback_root=_assets_root())
        hit = bank.find(img, args.click_tpl, threshold=0.85)
        if not hit:
            print(f"✖ 没找到模板 {args.click_tpl}")
            return 3
        x, y, score = hit
        print(f"→ 点模板 {args.click_tpl} ({x},{y}) score={score:.3f}")
        foreground(win)
        click(win["x"] + x, win["y"] + y)
        time.sleep(args.wait)
        after = grab(win)
        Image.fromarray(after[:, :, ::-1]).save(SHOTS / f"{args.shot}_after.png")
        print("  已截图")
        return 0


if __name__ == "__main__":
    sys.exit(main())