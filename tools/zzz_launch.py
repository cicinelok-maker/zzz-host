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


def _map_enter(rc: int) -> int:
    """enter_game 的返回码 → 全局退出码（AGENTS.md 那张表）。

    enter_game: 0=已到世界 1=没找到按钮 2=需要管理员 3=超时 6=需要登录
    全局表:     0=成功     1=一般失败   2=配置缺失   7=等进入游戏超时 6=需人工登录
    """
    return {0: 0, 1: 1, 2: 2, 3: 7, 6: 6}.get(rc, rc)


def ensure(timeout: int = 120, no_enter: bool = False) -> int:
    """确保游戏开着。返回 0 = 可以继续。"""
    w = game_running()
    if w:
        print(f"游戏已在运行：{w.get('title', '')} "
              f"@({w.get('x')},{w.get('y')}) {w.get('w')}x{w.get('h')}")
        if no_enter:
            return 0
        # 窗口在不等于是可操作 —— 可能停在标题页/登录页。
        # 只看 game_running() 就 return 0 会让用户以为好了，
        # 接着跑 zzz_status 才卡住（报「选不中角色」看不出根因）。
        print("确认游戏可操作…")
        rc = enter_game(30)      # 已在大世界时第一轮就返回，约 1 秒
        return _map_enter(rc)

    exe = find_exe()
    if not exe:
        print("找不到游戏客户端。检查过的路径：")
        for p in CANDIDATES:
            print(f"  {p}")
        print("→ 请手动启动一次，或告我实际路径")
        return 2      # 配置缺失（找不到客户端）

    print(f"游戏没开，启动：{exe}")
    if not launch(exe):
        return 1      # 一般失败（启动不起来）

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
    return _map_enter(rc)


# ---- 开始界面处理 ----
ENTER_WORDS = ["点击进入游戏", "点击进入", "点击开始", "进入游戏", "开始游戏"]
# 登录页的判据。
# **不要放「登录」** —— 那词在游戏里到处都是（登录奖励/每日登录/登录活动），
# 实测游戏日常面板就能命中，把普通界面误判成登录页。
# 真正的登录页会**同时**有「账号」「密码」（或「扫码」），
# 所以要求 >= 2 个同时出现，且不含宽泛词。
LOGIN_STRONG = ["账号", "密码", "扫码", "验证码", "手机号"]
LOGIN_NEED = 2          # 至少同时命中几个才算登录页


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

    # 抢前台 —— 文件头 L25 一直写着「恢复前台」，但代码里从来没有。
    # 窗口被别的程序挡住时，ImageGrab 抓到的是遮挡物，
    # 「已到世界」会被误判成「不在世界」。
    win = game_running()
    if win:
        try:
            import live
            live.foreground(win)
            time.sleep(0.3)
        except Exception:
            pass
    t0 = time.time()
    _back_count = 0
    while time.time() - t0 < timeout:
        vs.frame(force=True)
        state = anchors.describe(vs)
        if state == "世界":
            print(f"  已到世界")
            return 0

        # 只在「认不出界面」时才考虑登录页 ——
        # describe() 能认出是哪个界面时，说明根本不是登录页。
        if state == "未知界面":
            txt = vs.text((0, 0, 1920, 1080))
            hits = [w for w in LOGIN_STRONG if w in txt]
            if len(hits) >= LOGIN_NEED:
                print(f"  停在登录界面（看到 {hits}）")
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
            if state != "未知界面" and _back_count < 3:
                print(f"  当前 {state}，没看到进入按钮 —— 按 B 退出去")
                # 认得出界面（说明不是登录页/黑屏），但不在世界 → 按 B 退。
                # 用 B 不用 ESC：ESC 在有些界面会打开菜单，越按越远。
                try:
                    inp.pad_tap("b", wait=1.2)
                except Exception:
                    inp.key("esc", wait=1.5)
                _back_count += 1
                continue
            print(f"  当前 {state}，没看到进入按钮，等 3 秒…")
            time.sleep(3)
            time.sleep(3)
    print("  等进入游戏超时")
    print("  ── 可能的原因 ──")
    print("  1 游戏停在某个菜单/面板里（不是标题页，也没有「进入游戏」按钮）")
    print("     手动按 B 或 ESC 退回大世界，然后重新跑这个命令")
    print("  2 或者直接用 --no-enter 跳过「点进入游戏」这一步：")
    print("     python tools/zzz_launch.py --no-enter")
    print("     （后面跑 zzz_status 时会自己导航到目标界面）")
    print("  3 游戏在更新 / 弹了协议窗口")
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

    return ensure(args.timeout, no_enter=args.no_enter)


if __name__ == "__main__":
    sys.exit(main())