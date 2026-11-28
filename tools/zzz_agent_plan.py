"""设置「特训目标」，然后让游戏自己路由到要刷的副本。

## 为什么需要这个工具

计算「材料 → 副本」这条路**走不通**：

* `高维数据：深蚀回路` 该去哪个专业挑战室 boss？`dungeon_data.json` 里没有这张表
* 实战模拟室的任务名要靠 `compendium` 一张张查（芯片=元素测试名、认证章=职业演练…）

**但游戏自己有这条路**：设好「特训目标」之后点「前往」，
**游戏直接把你路由到该刷的副本** —— 不需要我们猜。

## 实测的界面流程（2026-11-28 真机）

游戏开着、在「大世界」时按 **F2** 打开快捷手册，然后：

```
快捷手册
  Tab 栏：目标(799,177) 日常(987,179) 训练(1173,180) 作战(1362,180) 战术(1549,180)
  ↓ 点「训练」
训练页
  特训目标 (301,380)   查看攻略 (1089,353)   **更换特训目标 (1391,354)**
  当前目标名字 (569,301)
  ↓ 点「更换特训目标」
更换特训目标（网格）
  第一屏实测：潘引壶(497,545) 蕾米埃尔(682) 维琳娜(867)
              **佩洛伊斯(1053,546)** 简(1236) 丽娜(1422)
              第二行：凯撒(866,783) 派派(1051)
  底部：特训方案 (814,830)   清除目标 (1143,830)
  ↓ **点角色头像**（名字在 y，头像在它上方约 60px）
  ↓ 底部按钮变成「**设置为目标**」(1143,830)
  ↓ 点它
面板下方的列表**可以上下滚动**，点「前往」直接路由到要刷的副本
```

## 为什么头像要点在名字上方 60px

和驱动盘网格一样：名字是头像下方的标签。
实测点 `(1053, 486)`（名字在 546）能选中，点名字那行不行。

## 滚动要慢

`wheel(-2)` + `wait_still`。一次滚 4 格会跳过整行 ——
这条在 `zzz_guide.select_agent` 上踩过，同一个病。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from core import Vision, Input, Ui, anchors  # noqa: E402

#: 头像相对名字的 y 偏移（实测 -60）
AVATAR_DY = -60

#: 网格区域（实测第一屏覆盖 x 460~1460, y 460~800）
GRID = (440, 430, 1500, 830)


def _click(vs: Vision, inp: Input, hit: dict, wait: float = 2.0) -> None:
    inp.move(hit["cx"], hit["cy"])
    time.sleep(0.3)
    inp.click(hit["cx"], hit["cy"], wait=wait)


def _find_and_click(vs: Vision, inp: Input, text: str,
                    region=(0, 0, 1920, 1080),
                    wait: float = 2.2) -> bool:
    # **找之前一定先刷帧**（audit_stale_frame 的规矩）。
    # 上一次动作之后画面已经变了，拿旧帧找目标会点在错位置。
    vs.frame(force=True)
    h = vs.find(text, region)
    if not h:
        return False
    _click(vs, inp, h, wait)
    vs.frame(force=True)
    return True


def open_handbook(ui: Ui) -> bool:
    """F2 打开快捷手册。**必须是 F2** —— 主菜单底部栏里没有这个入口。"""
    vs, inp = ui.vs, ui.inp
    for _ in range(8):
        vs.frame(force=True)
        if anchors.describe(vs) == "世界":
            break
        inp.key("esc", wait=1.3)
    vs.frame(force=True)
    if anchors.describe(vs) != "世界":
        print(f"  ✘ 回不到大世界（当前 {anchors.describe(vs)}）")
        return False

    inp.key("f2", wait=2.5)
    vs.frame(force=True)
    if not vs.find("快捷手册", (0, 0, 900, 120)) and \
       not vs.find("目标", (700, 120, 1700, 240)):
        print("  ✘ F2 之后没看到快捷手册的 Tab 栏")
        return False
    return True


def open_train_tab(ui: Ui) -> bool:
    vs, inp = ui.vs, ui.inp
    if not _find_and_click(vs, inp, "训练", (700, 120, 1700, 240)):
        print("  ✘ 找不到「训练」Tab")
        return False
    if not vs.find("特训目标", (0, 250, 900, 450)):
        print("  ✘ 进了训练页但没看到「特训目标」")
        return False
    return True


def open_target_grid(ui: Ui) -> bool:
    vs, inp = ui.vs, ui.inp
    if not _find_and_click(vs, inp, "更换特训目标", (1200, 300, 1700, 430), wait=2.8):
        print("  ✘ 找不到「更换特训目标」")
        return False
    # 打开了就该看到标题和「特训方案」/「清除目标」之一
    vs.frame(force=True)
    if not vs.find("更换特训目标", (300, 200, 900, 330)):
        print("  ✘ 更换特训目标面板没打开")
        return False
    return True


def find_in_grid(ui: Ui, agent: str, max_pages: int = 24) -> dict | None:
    """在网格里找角色名。**一屏只滚 2 格 + 等画面停稳**。"""
    vs, inp = ui.vs, ui.inp
    inp.move(950, 620)
    time.sleep(0.2)
    for _ in range(15):
        inp.wheel(6, wait=0.25)
    vs.frame(force=True)

    last = ""
    for page in range(max_pages + 1):
        if page > 0:
            inp.move(950, 620)
            inp.wheel(-2, wait=1.0)
            try:
                vs.wait_still(quiet=0.35, timeout=2.5)
            except Exception:
                time.sleep(0.45)
            vs.frame(force=True)

        hits = vs.items(GRID)
        sig = "|".join(h["text"] for h in hits)
        if page > 0 and sig == last:
            break
        last = sig

        for h in hits:
            if h["text"].strip() == agent:
                print(f"    第 {page + 1} 屏找到「{agent}」@({h['cx']},{h['cy']})")
                return h
    return None


def set_target(ui: Ui, agent: str) -> bool:
    """把特训目标设成 `agent`。返回是否成功。"""
    vs, inp = ui.vs, ui.inp

    hit = find_in_grid(ui, agent)
    if not hit:
        print(f"  ✘ 网格里滚了 24 屏都没找到「{agent}」")
        return False

    ax, ay = hit["cx"], hit["cy"] + AVATAR_DY
    print(f"    点头像 @({ax},{ay})（名字在 ({hit['cx']},{hit['cy']})）")
    inp.move(ax, ay)
    time.sleep(0.35)
    inp.click(ax, ay, wait=2.2)
    vs.frame(force=True)

    btn = vs.find("设置为目标", (900, 760, 1400, 900))
    if not btn:
        print("  ✘ 点了头像但底部没出现「设置为目标」")
        return False
    print(f"    点「设置为目标」@({btn['cx']},{btn['cy']})")
    _click(vs, inp, btn, wait=2.5)
    vs.frame(force=True)

    # **还有一步「确认」** —— 真机实测漏了它就等于没设。
    #
    # 点了「设置为目标」之后弹的是：
    #
    #     已将潘引壶设置为特训目标，
    #     是否替换？
    #     [取消 (826,679)]  [确认 (1128,679)]
    #
    # 不点确认，面板会**停在网格上、按钮仍显示「设置为目标」** ——
    # 看起来像点没生效，其实是等确认。
    ok = vs.find("确认", (700, 600, 1300, 760))
    if ok:
        print(f"    点「确认」@({ok['cx']},{ok['cy']})（替换掉原来的目标）")
        _click(vs, inp, ok, wait=3.0)
        vs.frame(force=True)
    else:
        print("    （没弹确认框，可能原来就没有目标，直接设上了）")
    return True


def _on_grid(vs: Vision) -> bool:
    """判断是不是还停在「更换特训目标」网格上。

    **不能用「特训目标」当判据** —— 网格标题是「**更换**特训目标」，
    包含那四个字，`find` 会命中，于是以为已经在训练页、不按 ESC。
    真机就是这么卡住的。

    用「特训方案」：那是网格底部独有的按钮，训练页没有。
    """
    return bool(vs.find("特训方案", (600, 780, 1000, 890)))


def verify(ui: Ui, agent: str) -> bool:
    """回到训练页确认当前特训目标就是 `agent`。"""
    vs, inp = ui.vs, ui.inp
    for _ in range(4):
        if not _on_grid(vs):
            break
        inp.key("esc", wait=1.8)
        vs.frame(force=True)
    # 训练页上「特训目标」块里显示的是当前目标名字（实测 x≈586, y≈302）
    shown = vs.find(agent, (300, 250, 1200, 360))
    return bool(shown)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="设置「特训目标」，让游戏自己路由到要刷的副本")
    ap.add_argument("agent", help="角色名，如 佩洛伊斯")
    ap.add_argument("--go", action="store_true",
                    help="设完之后点「前往」直接传送到副本")
    ap.add_argument("--dry-run", action="store_true",
                    help="只走到更换特训目标面板，不真的设置")
    args = ap.parse_args()

    from core.agent_cfg import resolve_agent
    agent = resolve_agent(args.agent)

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    try:
        vs.frame(force=True)
        print(f"目标角色：{agent}（当前界面 {anchors.describe(vs)}）")

        if not open_handbook(ui):
            return 4
        if not open_train_tab(ui):
            return 4
        if not open_target_grid(ui):
            return 4

        cur = vs.find("特训目标", (0, 250, 900, 450))
        if cur:
            vs.frame(force=True)

        if args.dry_run:
            print("（--dry-run：停在更换特训目标面板，不设置）")
            return 0

        if not set_target(ui, agent):
            return 3

        if verify(ui, agent):
            print(f"✔ 特训目标已设为「{agent}」")
        else:
            print("⚠ 设置了但没能确认 —— 面板上没读到新目标名字")

        if args.go:
            h = vs.find("前往", (1200, 300, 1750, 750))
            if h:
                print(f"  点「前往」@({h['cx']},{h['cy']})")
                _click(vs, inp, h, wait=4.0)
                print("  已传送（游戏会自己进对应的副本）")
            else:
                print("  ✘ 面板上没找到「前往」")
                return 4
        return 0
    finally:
        ui.stop()


if __name__ == "__main__":
    sys.exit(main())
