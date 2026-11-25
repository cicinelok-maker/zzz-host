"""自己打开绝区零（不用手动点）。

## 用户问（2026-11-25）

「你能自己打开绝区零吗，还是要我一直开着」

## 回答

**能自己开，但有几个前提要先确认：**

1. 游戏客户端路径存在（`A:/miHoYo Launcher/games/ZenlessZoneZero Game/ZenlessZoneZero.exe`）
2. 登录态还在（HoYoverse 客户端会记住账号，一般不用重新登录）
3. 分辨率/窗口位置和之前一致（工具按 1920x1080 定位）

**做不到的：**
- 重新登录（要验证码/扫码）
- 首次启动的协议同意
- 游戏更新

## 流程

```
① 已在运行 → 直接返回窗口句柄
② 没运行 → 启动 exe → 轮询等窗口（最多 120 秒）
③ 等到窗口 → 恢复前台 → 返回
④ 超时 → 报错并给出可能原因
```

## 用法

```bash
python tools/zzz_launch.py              # 确保游戏开着（没开就启动）
python tools/zzz_launch.py --check      # 只检查状态
python tools/zzz_launch.py --timeout 180
```
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import live  # noqa: E402

# 候选路径（按优先级）
CANDIDATES = [
    r"A:/miHoYo Launcher/games/ZenlessZoneZero Game/ZenlessZoneZero.exe",
    r"C:\Program Files\HoYoPlay\games\ZenlessZoneZero Game\ZenlessZoneZero.exe",
    r"D:\miHoYo Launcher\games\ZenlessZoneZero Game\ZenlessZoneZero.exe",
    r"E:\miHoYo Launcher\games\ZenlessZoneZero Game\ZenlessZoneZero.exe",
]


def find_exe() -> str:
    """找游戏客户端 exe。"""
    for p in CANDIDATES:
        if Path(p).exists():
            return p
    return ""


def game_running() -> dict | None:
    """游戏窗口在不在。"""
    return live.find_window()


def launch(exe: str) -> bool:
    """启动游戏客户端。"""
    try:
        subprocess.Popen([exe], cwd=str(Path(exe).parent),
                         creationflags=subprocess.DETACHED_PROCESS)
        return True
    except Exception as e:
        print(f"启动失败：{e}")
        return False


def wait_window(timeout: int = 120, interval: float = 2.0) -> dict | None:
    """轮询等窗口出现。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        w = live.find_window()
        if w:
            return w
        time.sleep(interval)
    return None


def ensure(timeout: int = 120) -> int:
    """确保游戏开着。返回 0 = 可以继续。"""
    w = game_running()
    if w:
        print(f"游戏已在运行：{w.get('title', '')} "
              f"@({w.get('x')},{w.get('y')}) {w.get('w')}x{w.get('h')}")
        return 0

    exe = find_exe()
    if not exe:
        print("找不到游戏客户端。检查过的路径：")
        for p in CANDIDATES:
            print(f"  {p}")
        print("→ 请手动启动一次，或告我实际路径")
        return 3

    print(f"游戏没开，启动：{exe}")
    if not launch(exe):
        return 4

    print(f"等窗口出现（最多 {timeout} 秒）…")
    w = wait_window(timeout)
    if not w:
        print("等超时。可能原因：")
        print("  1 需要登录（弹了账号界面）")
        print("  2 需要同意协议")
        print("  3 游戏在更新")
        print("  4 启动被拦截（杀软/权限）")
        return 5

    print(f"窗口出来了：{w.get('title', '')} "
          f"@({w.get('x')},{w.get('y')}) {w.get('w')}x{w.get('h')}")
    time.sleep(5)     # 等画面渲染

    print("处理开始界面…")
    rc = enter_game(90)
    if rc == 2:
        return 6      # 需要登录
    if rc == 3:
        return 7      # 超时
    return 0


# ---- 开始界面处理 ----
ENTER_WORDS = ["点击进入游戏", "点击进入", "点击开始", "进入游戏", "开始游戏"]
LOGIN_WORDS = ["登录", "账号", "密码", "扫码"]


def enter_game(timeout: int = 90) -> int:
    """等窗口出来后，自动点「进入游戏」直到到世界。

    返回 0 = 已到世界，1 = 停在开始界面但没找到按钮，
        6 = 需要登录（做不了），3 = 超时
    """
    # 权限闸：这个函数要「点进入游戏」。注入被 UIPI 丢掉的话会白等满 timeout，
    # 最后只报「超时」—— 看不出是权限问题（朋友实测普通权限下就是这样）。
    # 它是所有人第一个跑的命令（AGENTS.md 五条命令的第 2 条），闸必须在这。
    from core.input import is_admin
    if not is_admin():
        print("✘ 需要管理员权限")
        print("  要点「点击进入游戏」—— 没有管理员权限时这个点击会被")
        print("  Windows UIPI 静默丢弃，然后白等满超时，最后只报「超时」。")
        print()
        print("  正确用法：右键终端 → 以管理员身份运行")
        print("  或跑项目根的：.\\admin.ps1")
        return 2

    from core import Vision, Input, anchors
    vs, inp = Vision(), Input()
    t0 = time.time()
    while time.time() - t0 < timeout:
        vs.frame(force=True)
        state = anchors.describe(vs)
        if state == "世界":
            print(f"  已到世界")
            return 0

        txt = vs.text((0, 0, 1920, 1080))
        for w in LOGIN_WORDS:
            if w in txt:
                print(f"  停在登录界面（看到「{w}」）")
                print("  → 需要账号密码/扫码，这一步做不了，请手动登录一次")
                return 6

        clicked = False
        for w in ENTER_WORDS:
            hit = vs.find(w, (0, 0, 1920, 1080))
            if hit:
                print(f"  点「{w}」@({hit['cx']},{hit['cy']})")
                inp.click(hit["cx"], hit["cy"], wait=4.0)
                clicked = True
                break
        if not clicked:
            print(f"  当前 {state}，没看到进入按钮，等 3 秒…")
            time.sleep(3)
    print("  等进入游戏超时")
    return 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查不启动")
    ap.add_argument("--timeout", type=int, default=120, help="等窗口多少秒")
    ap.add_argument("--no-enter", action="store_true", help="不自动点进入游戏")
    args = ap.parse_args()

    if args.check:
        w = game_running()
        if w:
            print(f"运行中：{w.get('title', '')} "
                  f"@({w.get('x')},{w.get('y')}) {w.get('w')}x{w.get('h')}")
            return 0
        print("没在运行")
        exe = find_exe()
        print(f"客户端：{exe or '找不到'}")
        return 1

    return ensure(args.timeout)


if __name__ == "__main__":
    sys.exit(main())