"""音像店调律（纯键鼠，走手机入口，支持定向分区）。

## 摸清的界面（实测）

**手机入口（推荐，不用走路）**
```
波浪号(~) 开手机 → 里面有「音像店」按钮 @(1458,399) → 直接进调律界面
```

**调律主界面**
```
音轨设定 @(1042,1016)     选套装（12 个套装的名字网格）
当前套装显示在 (1041,965)
定向     @(1041,753)      切到定向模式（产出指定分区）
调律×01  @(1352,995)      消耗 3 个母盘
调律×10  @(1677,995)      消耗 30 个
拆解     @(119,1043)
```

**定向模式的六个分区（数字位置，实测）**
```
1(1393,365)   6(1631,363)
2(1324,526)   5(1708,526)
3(1399,688)   4(1631,688)
```
点完顶部会显示「区[N]」，可以据此确认选中的是哪一个。

## ⚠️ 定向的三个实测结论（2026-11-25 用截图逐项确认）

**1. 有 6 个分区，不是 3 个**
六边形排列 1~6，坐标经 OCR 复核完全一致。

**2. 但一次只能选 1 个（单选）**
点了 3 号之后，1 号的黄色 `+` 会消失 —— 不能同时指定多个分区。
所以「一次调律只出一个指定分区的盘」。

**3. 定向的母盘成本是双倍**

| 模式 | ×01 | ×02 |
|---|---|---|
| 不定向 | 3 母盘 | 6 母盘 |
| **定向** | **6 母盘** | **12 母盘** |

用户可能看到界面上的 `3` / `6` 误以为是「几个碟」，
那其实是**母盘消耗量**。

所以：**7 个母盘只够做 1 次定向调律**，不是 7 次。
`core/tune_plan.py` 里的 `MOTHER_PER_TUNE_DIRECTED = 6` 就是这个。

## 用法

    python tools/zzz_tune.py 拂晓行纪                  # 音轨设定 + 调律×10
    python tools/zzz_tune.py 拂晓行纪 --times 1
    python tools/zzz_tune.py 拂晓行纪 --slot 5         # 定向 5 号位
    python tools/zzz_tune.py 拂晓行纪 --dry            # 只设音轨
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, Journal  # noqa: E402
from core.machine import Machine  # noqa: E402

R_BOTTOM = (0, 900, 1920, 1080)
R_SETS = (700, 420, 1700, 900)
R_TOP = (1000, 100, 1900, 200)
R_HINT = (900, 700, 1450, 900)

PHONE_BTN = "音像店"

# 音轨设定的 12 格（4 列 x 3 行，图标中心，实测）
TRACK_GRID = {
    "谶羽之誓": (899, 422), "荆棘玫瑰": (1063, 422),
    "拂晓行纪": (1226, 422), "呼啸沙龙": (1389, 422),
    "囚徒手记": (899, 573), "雪兔梦游仙境": (1063, 573),
    "流光咏叹": (1226, 573), "沧浪行歌": (1389, 573),
    "月光骑士颂": (899, 724), "拂晓生花": (1063, 724),
    "山大王": (1226, 724), "云岿如我": (1389, 724),
}
# 面板左侧的套装标题区域（比之前宽）
R_TRACK_TITLE = (300, 330, 780, 450)
# 定向模式的六个分区（数字位置）
RING = {1: (1393, 365), 2: (1324, 526), 3: (1399, 688),
        4: (1631, 688), 5: (1708, 526), 6: (1631, 363)}


def is_tune_ui(vs: Vision) -> bool:
    return vs.has(R_BOTTOM, "调律×01") or vs.has(R_BOTTOM, "音轨设定")


def is_track_panel(vs: Vision) -> bool:
    return vs.has((300, 180, 800, 260), "音轨设定") and not vs.has(R_BOTTOM, "调律×01")


def open_store_via_phone(ui: Ui) -> bool:
    """波浪号开手机 → 点「音像店」。比走过去稳得多。"""
    vs, inp = ui.vs, ui.inp
    for attempt in range(3):
        if is_tune_ui(vs):
            return True
        inp.key("tilde", wait=2.2)
        vs.frame(force=True)
        hit = vs.find(PHONE_BTN, (0, 0, 1920, 1080))
        if not hit:
            print(f"  手机里没找到「{PHONE_BTN}」（第 {attempt + 1} 次）")
            inp.key("esc", wait=1.2)
            continue
        inp.click(hit["cx"], hit["cy"], wait=3.0)
        vs.frame(force=True)
        if is_tune_ui(vs) or is_track_panel(vs):
            print(f"  已通过手机进入音像店")
            return True
    return False


def close_panels(ui: Ui) -> None:
    for _ in range(3):
        if is_tune_ui(ui.vs):
            return
        ui.inp.key("esc", wait=1.2)


def set_track(ui: Ui, set_name: str) -> bool:
    """音轨设定：点固定格子切 UP，再用左侧标题验证。"""
    vs, inp = ui.vs, ui.inp
    vs.frame(force=True)
    hit = vs.find("音轨设定", R_BOTTOM)
    if not hit:
        print("  找不到「音轨设定」")
        return False
    inp.click(hit["cx"], hit["cy"], wait=2.2)
    vs.frame(force=True)

    # 必须确认面板真的打开了，否则后面点格子会落到主界面上
    opened = False
    for _ in range(3):
        if vs.has((280, 140, 900, 280), "音轨设定"):
            opened = True
            break
        # 面板没开，再点一次按钮
        inp.click(hit["cx"], hit["cy"], wait=2.0)
        vs.frame(force=True)
    if not opened:
        print("  音轨设定面板打不开")
        return False

    # 套装顺序会变（实测：有时拂晓行纪在第一格，有时谶羽之誓在第一格），
    # 所以必须用 OCR 现场找名字，再点它上方的图标。固定坐标不可靠。
    # 套装列表要滚动才能看全（实测列表有 20+ 个，一屏只显示 12 个）
    hit2 = vs.find(set_name, (650, 380, 1750, 950))
    if not hit2:
        import time as _t
        inp.move(960, 600)
        _t.sleep(0.4)
        # 先滚回顶部
        for _ in range(8):
            inp.wheel(4)
            _t.sleep(0.35)
        for _ in range(14):
            vs.frame(force=True)
            hit2 = vs.find(set_name, (650, 380, 1750, 950))
            if hit2:
                break
            inp.wheel(-3)
            _t.sleep(0.45)
    if not hit2:
        print(f"  面板里没找到「{set_name}」（已滚动搜索）")
        return False
    # 文字标签在图标下方约 77px
    xy = (hit2["cx"], hit2["cy"] - 77)
    print(f"  「{set_name}」标签@{hit2['cx']},{hit2['cy']} → 点图标{xy}")

    inp.click(xy[0], xy[1], wait=1.4)
    vs.frame(force=True)
    title = vs.text(R_TRACK_TITLE)
    ok = set_name in title
    print(f"  点 {set_name}@({xy[0]},{xy[1]}) → 左侧标题「{title.strip()[:20]}」 "
          f"{'✔' if ok else '✖'}")
    if not ok:
        return False

    # 关键：点套装只是预览（黄框），必须再点底部「替换UP」才真正生效
    rep = vs.find("替换UP", (600, 800, 1500, 950))
    if rep:
        inp.click(rep["cx"], rep["cy"], wait=1.8)
        print(f"  点「替换UP」@({rep['cx']},{rep['cy']})")
    else:
        print("  没找到「替换UP」（可能已经是目标套装）")
    # 关面板（点右上角 X 或 ESC）
    inp.click(1786, 190, wait=1.4)
    vs.frame(force=True)
    if "音轨设定" in vs.text((300, 150, 800, 260)):
        inp.key("esc", wait=1.2)
    vs.frame(force=True)
    ok2 = set_name in vs.text(R_BOTTOM)
    print(f"  面板关闭后底部当前套装 {'✔' if ok2 else '✖'}")
    return ok2


def _is_directed_at(ui: Ui, slot: int) -> bool:
    """底部按钮是否已经变成「调律[N]区×..」"""
    vs = ui.vs
    vs.frame(force=True)
    return any(f"调律[{slot}]区" in it["text"] for it in vs.items(R_BOTTOM))


def set_directed(ui: Ui, slot: int) -> bool:
    """切到定向并选分区。

    实测：直接点定向会弹主属性面板，点取消后**不一定会保持定向模式**，
    单独点环形数字也可能只是预览。所以按「点一下、验一次」来：
        1. 先直接点环形数字，看底部变没变
        2. 没变就点「定向」→ 关掉弹出的面板 → 再点环形数字
        3. 再验一次
    """
    vs, inp = ui.vs, ui.inp
    xy = RING.get(slot)
    if not xy:
        return False

    # 已经就是它
    if _is_directed_at(ui, slot):
        print(f"  已经是 {slot} 号位定向")
        return True

    # 1) 直接点环形
    inp.click(xy[0], xy[1], wait=1.4)
    if _is_directed_at(ui, slot):
        print(f"  定向 {slot} 号位 ✔（直接点环形生效）")
        return True

    # 2) 先开定向面板再点
    ding = vs.find("定向", (900, 600, 1300, 900))
    if ding:
        inp.click(ding["cx"], ding["cy"], wait=1.6)
        vs.frame(force=True)
        c = vs.find("取消", (900, 900, 1600, 1000))
        if c:
            inp.click(c["cx"], c["cy"], wait=1.4)
        inp.click(xy[0], xy[1], wait=1.6)
        if _is_directed_at(ui, slot):
            print(f"  定向 {slot} 号位 ✔（先开面板再生效）")
            return True

    # 3) 再来一轮
    inp.click(xy[0], xy[1], wait=1.6)
    ok = _is_directed_at(ui, slot)
    bottom = vs.text(R_BOTTOM)[:80]
    print(f"  定向 {slot} 号位 {'✔' if ok else '✖'}　底部：{bottom}")
    return ok


def do_tune(ui: Ui, times: int = 10) -> tuple[bool, str, int]:
    """点调律按钮。

    按钮文字会随模式/资源变化，**不能写死**：
        随机：调律×01 / 调律×10
        定向：调律[3]区×01 / 调律[3]区×06 / 调律[3]区×10
    母盘只有 36 个时，定向最多只能 ×06，游戏不会给 ×10 的按钮。
    所以：优先找 ×times 的，找不到就点最大倍率的那个。
    """
    vs, inp = ui.vs, ui.inp
    vs.frame(force=True)
    cands = []
    for it in vs.items(R_BOTTOM):
        t = it["text"]
        if not t.startswith("调律"):
            continue
        m = re.search(r"×\s*(\d+)", t)
        mult = int(m.group(1)) if m else 1
        cands.append((mult, it))
    if not cands:
        print(f"  底部没有调律按钮；实际：{vs.text(R_BOTTOM)[:100]}")
        return False, "", 0

    cands.sort(key=lambda x: -x[0])
    exact = [c for c in cands if c[0] == times]
    if exact:
        mult, hit = exact[0]
        print(f"  按钮：{hit['text']}")
    else:
        # **绝不点比请求更大的倍率**（RT-11）。
        #
        # 原来这里是 `cands[0]`（最大的那个）—— 请求 ×01 而游戏只给 ×10 时
        # 就点 ×10：**一次花掉 10 倍预算**。
        # 定向 ×01 = 6 母盘，×10 = 60 —— `plan_tune` 算的「还能做几个位号」
        # 直接作废，后面几个位号没母盘了。
        #
        # 而且那时只在日志里写一行「按实际的记」，钱照花。
        #
        # 现在：只在「**不大于**请求值」的候选里挑最大的。
        # 请求 ×10、只给 ×06 -> 点 ×06（省着花，安全）；
        # 请求 ×01、只给 ×10 -> **放弃**，一个都不点。
        _safe = [c for c in cands if c[0] <= times]
        if not _safe:
            _have = "、".join("×%d" % c[0] for c in cands)
            print(f"  ✘ 只有 {_have}，都比请求的 ×{times} 大 —— 不点（避免超预算）")
            print(f"     母盘不够时游戏不给小倍率按钮。想用小倍率，先攒够母盘。")
            return False, "", 0
        mult, hit = _safe[0]
        print(f"  没有 ×{times} 的按钮，改用不大于它的「{hit['text']}」")

    before = vs.text((1100, 20, 1900, 90))
    inp.click(hit["cx"], hit["cy"], wait=1.0)
    ok = vs.wait_for((0, 0, 1920, 1080), "调律获得", timeout=15.0)
    got = ""
    if ok:
        got = vs.text((600, 100, 1500, 400))[:100]
        print(f"  ✔ 产出：{got}")
    else:
        print(f"  ✖ 点了「{label}」但没看到「调律获得」")
    # **把实际用到的倍率带回去**（BUG-081）。
    #
    # 原来这函数返回 `(ok, got)`，倍率 `mult` 算出来就丢了；
    # 调用方于是记 `×{args.times}`（**请求的**倍率）。
    # 请求 ×10 而游戏只给 ×06 时，日志记的是「×10」，**记录在说谎**。
    for _ in range(3):
        inp.key("esc", wait=1.1)
        if is_tune_ui(vs):
            break
    after = vs.text((1100, 20, 1900, 90))
    m1 = re.search(r"(\d{8})", before)
    m2 = re.search(r"(\d{8})", after)
    if m1 and m2:
        print(f"     母盘计数 {m1.group(1)} → {m2.group(1)}")
    return ok, got, mult


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("set_name")
    ap.add_argument("--times", type=int, default=10, choices=[1, 10])
    ap.add_argument("--slot", type=int, default=0, help="定向分区 1-6，0 表示不指定")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    log = Journal(f"调律_{args.set_name}")
    ui.start()

    if is_track_panel(vs):
        close_panels(ui)

    if not is_tune_ui(vs):
        # 交给状态机：波浪号 → 手机 → 音像店（实测 12 秒到）
        m = Machine(ui, verbose=False)
        if m.go_to("调律界面"):
            print("  状态机已导航到调律界面")
        elif not open_store_via_phone(ui):
            print("进不了音像店")
            return 4
    print("已在调律界面")
    log.log("进入", "调律界面", ok=True)

    if not set_track(ui, args.set_name):
        log.log("音轨设定", args.set_name, ok=False)
        return 5
    log.log("音轨设定", args.set_name, ok=True)

    if args.slot:
        if not set_directed(ui, args.slot):
            log.log("定向", f"{args.slot}号位", ok=False)
            return 6
        log.log("定向", f"{args.slot}号位", ok=True)

    if args.dry:
        print("（--dry：只设音轨/定向，不调律）")
        print(log.summary())
        return 0

    ok, got, _mult = do_tune(ui, args.times)
    # **记实际倍率，不是请求的**（BUG-081）：请求 ×10 但游戏只给 ×06 时，
    # 原来日志记「×10」—— 记录在说谎。
    _rec = f"×{_mult}" if _mult else f"×{args.times}"
    if _mult and _mult != args.times:
        print(f"  ⚠ 请求 ×{args.times}，实际 ×{_mult}（按实际的记）")
    log.log("调律", _rec, ok=ok, detail=got)
    print("调律完成" if ok else "调律未确认成功")
    print()
    print(log.summary())
    return 0 if ok else 7


if __name__ == "__main__":
    sys.exit(main())