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

#: 设好目标之后「特训目标」下面那块可滚动面板（实测 y 430~1010 是真的列表）
PANEL = (250, 430, 1750, 1015)


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
        # **已经是目标了**：底部会显示「清除目标」而不是「设置为目标」。
        # 重复运行工具时必然走到这里 —— 原来直接报错退出，
        # 于是「设成同一个角色」永远失败。
        if vs.find("清除目标", (900, 760, 1400, 900)):
            print(f"    「{agent}」本来就是特训目标，不用再设")
            return True
        print("  ✘ 点了头像但底部既没有「设置为目标」也没有「清除目标」")
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


def _rows(items: list[dict]) -> list[tuple[int, list[dict]]]:
    """按 y 把 OCR 结果聚成行（同 y±18 算一行）。"""
    rows: list[tuple[int, list[dict]]] = []
    for it in sorted(items, key=lambda x: x["cy"]):
        for i, (y, group) in enumerate(rows):
            if abs(y - it["cy"]) <= 18:
                rows[i][1].append(it)
                break
        else:
            rows.append((it["cy"], [it]))
    return rows


def go_to(ui: Ui, keyword: str, max_pages: int = 12,
          allow_click: bool = False) -> int:
    """在「特训目标」面板里**滚着找** keyword，点它那一行的「前往」。

    ## 为什么不能直接点第一个「前往」（真机教训）

    这个面板是**可滚动**的，而且每屏同时有 2 个「前往」（不同 y）。
    实测滚动过程：

        没滚：  前往 (1475,652)   前往 (1475,910)
        滚1次： 前往 (1475,559)   前往 (1475,816)
        滚2次： 前往 (1474,465)   前往 (1475,722)
        滚4次： 前往 (1475,534)   前往 (1475,750)

    直接 `find("前往")` 拿到的是**最上面那一个**，和你要刷的东西
    没有任何关系 —— 会传送到错的副本。

    ## 现在的定位法

    滚着找 `keyword`（材料名或副本名都行），找到之后取**同一行**的
    「前往」（y 差 ≤ 18）点它。

    找不到就**什么都不点**并返回非零 —— 宁可不动，也不要去错副本。

    ## **按「行名 + y 配对」是错的**（2026-11-28 真机事故）

    我以为「左侧类别标签和右侧『前往』在同一 y」，于是按 y 差 ≤18 配对。
    实测点「专业挑战室」那行的前往 (1475,722) —— **进了实战模拟室-代理人技能**
    （传送后画面上是 风切测试/刚性测试/升温测试/冰结测试/电流测试）。

    也就是说：左边那 4 个类别标签（y=489/597/707/814 固定不动）
    和右边**可滚动内容**里的「前往」**不在同一行**，y 配对上就错了。

    **所以默认只列不点。** 真要传，加 `--force`，并且自己盯着落地是不是对的。
    正确做法应该是：点某个类别（左栏）让它成为选中态，再点它内容的「前往」——
    但那条路我还没测过，不猜。
    """
    vs, inp = ui.vs, ui.inp
    # **空关键词 = 只列出，不点任何东西**。
    #
    # 这个面板按「副本/任务」组织（代理人晋升 / 代理人技能 / 恶名·杜拉罕…），
    # **不是按材料** —— 实测滚 13 屏只看到任务名和进度，没有「冰结芯片」。
    # 所以让用户先看清有哪些，再指定一个。
    kw = (keyword or "").strip()
    if not kw:
        print("  （没给副本名 —— 只列出面板上能去哪，不点任何东西）")

    inp.move(1000, 700)
    time.sleep(0.25)
    for _ in range(15):
        inp.wheel(6, wait=0.22)
    vs.frame(force=True)

    seen: list[str] = []
    last = ""
    for page in range(max_pages + 1):
        if page > 0:
            inp.move(1000, 700)
            inp.wheel(-2, wait=1.1)
            try:
                vs.wait_still(quiet=0.35, timeout=2.5)
            except Exception:
                time.sleep(0.45)
            vs.frame(force=True)

        items = vs.items(PANEL)
        sig = "|".join(i["text"] for i in items)
        if page > 0 and sig == last:
            break
        last = sig

        for y, group in _rows(items):
            texts = [i["text"] for i in group]
            go = next((i for i in group if "前往" in i["text"]), None)

            if not kw:
                # 列出模式：只报「这一行有前往的，去的是哪个任务」
                if go is not None:
                    # **滤掉进度计数器**（13/37、0/50、2/5）和等级区间（20-100）
                    # —— 它们不是副本名，混在输出里没法看。
                    import re as _re
                    names = [t for t in texts
                             if not t.startswith("前往")
                             and len(t) > 1
                             and not _re.fullmatch(r"\d+\s*/\s*\d+", t)
                             and not _re.fullmatch(r"\d+\s*-\s*\d+", t)
                             and not _re.fullmatch(r"\d+", t)]
                    if names:
                        print(f"    y={y:>4}  {' / '.join(names[:3])}"
                              f"      前往@({go['cx']},{go['cy']})")
                continue

            if not any(kw in t for t in texts):
                continue
            if go is None:
                # 这一行有名字但没有「前往」按钮（可能是标题行）
                continue
            if not allow_click:
                # **默认绝不点** —— 行名和按钮对不齐，点了会去错副本。
                print(f"    第 {page + 1} 屏：{texts[:3]}  前往@({go['cx']},{go['cy']})")
                print(f"    ⚠ 只是**报告位置**，没有点 —— "
                      f"行名和按钮不在同一 y，配不准（实测会去错副本）")
                print(f"      确实知道是哪一个的话，加 --force 才会真的点")
                return 0
            print(f"    第 {page + 1} 屏找到「{kw}」那一行：{texts[:4]}")
            print(f"    点它的「前往」@({go['cx']},{go['cy']})")
            _click(vs, inp, go, wait=2.5)
            vs.frame(force=True)

            # **还有一步「是否立即传送？」**（真机实测）。
            # 不点确认就什么都没发生 —— 我第一版点完「前往」就报「已传送」，
            # 实际游戏还停在确认框上。
            ok = vs.find("确认", (700, 550, 1300, 720))
            if ok and vs.find("是否立即传送", (600, 450, 1400, 600)):
                print(f"    点「确认」@({ok['cx']},{ok['cy']})（立即传送）")
                _click(vs, inp, ok, wait=6.0)
                vs.frame(force=True)
                print("    已传送（游戏会自己进对应的副本）")
            else:
                print("    （没弹传送确认框，可能已经直接进了）")
            return 0

        seen.extend(t for t in (i["text"] for i in items) if t.strip())

    if not kw:
        print("\n  ↑ 这就是面板上所有的「前往」。")
        print("    要真去某个，把它的名字传进来：")
        print("      python tools/zzz_agent_plan.py 苍角 --go 代理人技能")
        return 0

    print(f"  ✘ 滚了 {max_pages + 1} 屏都没找到「{kw}」—— **什么都没点**")
    print(f"     面板上出现过的：{'、'.join(dict.fromkeys(seen))[:200]}")
    print(f"     提示：关键词是**副本/任务名**，不是材料名")
    return 4


def main() -> int:
    ap = argparse.ArgumentParser(
        description="设置「特训目标」，让游戏自己路由到要刷的副本")
    ap.add_argument("agent", help="角色名，如 佩洛伊斯")
    ap.add_argument("--go", metavar="副本名", nargs="?", const="", default=None,
                    help="**不给值**：滚一遍面板，列出所有能去的副本（不点任何东西）。"
                         "**给值**：滚着找这个副本名，点它那一行的「前往」传送。"
                         "关键词是**副本/任务名**（代理人晋升、代理人技能、"
                         "恶名·杜拉罕…），不是材料名 —— 这个面板按副本组织")
    ap.add_argument("--force", action="store_true",
                    help="**明知道自己在点哪一个**才加。"
                         "默认 --go 只报告位置不点 —— 行名和按钮不在同一 y，"
                         "实测按 y 配对点下去会去错副本（专业挑战室 → 实战模拟室）")
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
        # **先看当前目标是不是已经是它** —— 是就不用再走一遍网格。
        # 训练页的「特训目标」块里显示当前目标名字（实测 x≈586, y≈302）。
        if vs.find(agent, (300, 250, 1200, 360)):
            print(f"  当前特训目标已经是「{agent}」，跳过设置")
            if args.go is not None:
                return go_to(ui, args.go, allow_click=args.force)
            return 0

        if not open_target_grid(ui):
            return 4

        if args.dry_run:
            print("（--dry-run：停在更换特训目标面板，不设置）")
            return 0

        if not set_target(ui, agent):
            return 3

        if verify(ui, agent):
            print(f"✔ 特训目标已设为「{agent}」")
        else:
            print("⚠ 设置了但没能确认 —— 面板上没读到新目标名字")

        if args.go is not None:
            return go_to(ui, args.go, allow_click=args.force)
        return 0
    finally:
        ui.stop()


if __name__ == "__main__":
    sys.exit(main())
