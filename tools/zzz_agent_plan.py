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
import re
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
# **左栏在 x≈180~350，必须排除** —— 否则「专业挑战室」这个左栏标签
# 也会被当任务名匹配到，然后找它那一行的「前往」当然找不到。
PANEL = (430, 430, 1750, 1015)

#: **左栏是类别切换**（从截图量出来的，不是猜的）。
#:
#: 真机截图看得清清楚楚：左边一竖列是
#:     特训目标（默认选中，蓝色）
#:     实战模拟室 / 区域巡防 / 专业挑战室 / 恶名狩猎
#: 点哪个，右边就只显示那个类别的任务。
LEFT_RAIL = {
    "特训目标": (263, 309),
    "实战模拟室": (263, 461),
    "区域巡防": (263, 596),
    "专业挑战室": (263, 736),
    "恶名狩猎": (263, 830),
}

#: **任务名和它那行的「前往」y 差约 80px**（真机实测 79/85/84）。
#:
#: 我原来按 y 差 ≤18 配对 —— 永远配不上，于是配到别的行、传到错的副本。
ROW_GO_DY = 80

#: 配对时允许的 y 差范围（实测 79/85/84，留余量）
ROW_GO_LO, ROW_GO_HI = 40, 130


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


def _norm(t: str) -> str:
    """去掉引号/空格，方便匹配「征服者」和 `「征服者」` 这种差异。"""
    return re.sub(r"[\s「」『』\"']", "", t or "")


def _pick_rail(vs: Vision, category: str) -> bool:
    """点左栏类别，让右边只显示该类别。"""
    xy = LEFT_RAIL.get(category)
    if not xy:
        return False
    inp = Input()
    inp.move(xy[0], xy[1])
    time.sleep(0.3)
    inp.click(xy[0], xy[1], wait=2.4)
    vs.frame(force=True)
    return True


def go_to(ui: Ui, keyword: str, max_pages: int = 12,
          allow_click: bool = True) -> int:
    """在「特训目标」面板里找到指定任务，点它那一行的「前往」传送。

    ## 真机看懂的布局（截图，不是 OCR 猜的）

    ```
    左栏（类别切换，固定）        右边（该类别下的任务，可滚动）
    特训目标(选中)                 ┌ 恶名·杜拉罕   40   [前往] ┐
    实战模拟室                     └ 差 79px                 ┘
    区域巡防                       ┌「征服者」    40-80 [前往] ┐
    专业挑战室  ← 点它             └ 差 85px                 ┘
    恶名狩猎                       ┌「空域戒戍者」 40-80 [前往]
    ```

    ## 两个坑

    ① **左栏是类别切换，不是行标签**。我原来把「专业挑战室」这个左侧
       标签和右侧某个「前往」按 y 配对 —— 传到了实战模拟室。

    ② **任务名和它那行的「前往」y 差约 80px**（79/85/84），
       不是我原来假设的 ±18。

    ## 现在的规则

    · `keyword` 命中**左栏类别** -> 切过去，然后**列出**该类别的任务，不点
      （一个类别下有多个 boss，我不替你选）
    · `keyword` 命中**任务名** -> 点它那一行（y+80）的「前往」
    · 都没有 -> 什么都不点，返回非零
    """
    vs, inp = ui.vs, ui.inp
    kw = (keyword or "").strip()
    if not kw:
        kv = _norm(kw)
        print("  （没给关键词 —— 只列出面板上能去哪，不点任何东西）")

    # 先回顶
    inp.move(1000, 700)
    time.sleep(0.25)
    for _ in range(15):
        inp.wheel(6, wait=0.22)
    vs.frame(force=True)

    # **命中左栏类别就先切过去**（右边随之只剩该类别的任务）
    if kw in LEFT_RAIL:
        print(f"  左栏切到「{kw}」")
        _pick_rail(vs, kw)
        inp.move(1000, 700)
        time.sleep(0.25)
        for _ in range(12):
            inp.wheel(6, wait=0.22)
        vs.frame(force=True)

    want = _norm(kw)
    seen: list[str] = []

    def _scan_current(pages: int) -> tuple[bool, list[str]]:
        """在当前类别里滚着找 `want`。找到就点并返回 (True, [])。"""
        last = ""
        for page in range(pages + 1):
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

            gos = sorted([i for i in items if "前往" in i["text"]],
                         key=lambda x: x["cy"])
            names = sorted([i for i in items
                            if not i["text"].startswith("前往")
                            and len(i["text"]) > 1
                            and not re.fullmatch(r"[\d,]+(\s*/\s*[\d,]+)?", i["text"])
                            and not re.fullmatch(r"\d+\s*-\s*\d+", i["text"])],
                           key=lambda x: x["cy"])

            if not kw:
                for nm in names:
                    g = next((g for g in gos
                              if ROW_GO_LO <= g["cy"] - nm["cy"] <= ROW_GO_HI), None)
                    if g:
                        print(f"    {nm['text'][:22]:<24} 前往@({g['cx']},{g['cy']})")
                seen.extend(n["text"] for n in names)
                continue

            hit = next((n for n in names if want and _norm(n["text"]) == want), None)
            if hit is None:
                seen.extend(n["text"] for n in names)
                continue
            g = next((g for g in gos
                      if ROW_GO_LO <= g["cy"] - hit["cy"] <= ROW_GO_HI), None)
            if g is None:
                print(f"    找到「{hit['text']}」但没找到它那一行的「前往」")
                return False, seen
            print(f"    第 {page + 1} 屏找到「{hit['text']}」@({hit['cx']},{hit['cy']})")
            print(f"    点它的「前往」@({g['cx']},{g['cy']})")
            _click(vs, inp, g, wait=2.5)
            vs.frame(force=True)
            ok = vs.find("确认", (700, 550, 1300, 720))
            if ok and vs.find("是否立即传送", (600, 450, 1400, 600)):
                print(f"    点「确认」@({ok['cx']},{ok['cy']})（立即传送）")
                _click(vs, inp, ok, wait=6.0)
                vs.frame(force=True)
                print("    已传送")
            else:
                print("    （没弹传送确认框）")
            return True, seen
        return False, seen

    # **不是类别名 -> 在 4 个类别里逐个找**。
    # 一个任务只属于一个类别，所以逐个切过去扫是最稳的；
    # 一开始我在「特训目标」这个默认视图里滚，内容是混的、还滚不到底。
    if kw and kw not in LEFT_RAIL:
        for cat in ("实战模拟室", "区域巡防", "专业挑战室", "恶名狩猎"):
            print(f"  在「{cat}」里找「{kw}」…")
            _pick_rail(vs, cat)
            inp.move(1000, 700)
            time.sleep(0.25)
            for _ in range(12):
                inp.wheel(6, wait=0.22)
            vs.frame(force=True)
            found, seen2 = _scan_current(8)
            seen.extend(seen2)
            if found:
                return 0
        print(f"  ✘ 4 个类别都翻遍了也没找到「{kw}」—— **什么都没点**")
        print(f"     看到过：{'、'.join(dict.fromkeys(seen))[:240]}")
        return 4

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

        gos = sorted([i for i in items if "前往" in i["text"]],
                     key=lambda x: x["cy"])
        names = sorted([i for i in items
                        if not i["text"].startswith("前往")
                        and len(i["text"]) > 1
                        and not re.fullmatch(r"[\d,]+(\s*/\s*[\d,]+)?", i["text"])
                        and not re.fullmatch(r"\d+\s*-\s*\d+", i["text"])],
                       key=lambda x: x["cy"])

        # ---- 只列不点 ----
        if not kw:
            for nm in names:
                g = next((g for g in gos if ROW_GO_LO <= g["cy"] - nm["cy"] <= ROW_GO_HI), None)
                if g:
                    print(f"    {nm['text'][:22]:<24} 前往@({g['cx']},{g['cy']})")
            seen.extend(n["text"] for n in names)
            continue

        # ---- 找任务 ----
        # **类别名不参与任务匹配** —— 它是左栏的筛选按钮，不是任务
        if kw not in LEFT_RAIL and want in {_norm(n["text"]) for n in names} and want:
            nm = next(n for n in names if _norm(n["text"]) == want)
            g = next((g for g in gos if ROW_GO_LO <= g["cy"] - nm["cy"] <= ROW_GO_HI), None)
            if g is None:
                print(f"    找到「{nm['text']}」但没找到它那一行的「前往」")
                return 4
            print(f"    第 {page + 1} 屏找到「{nm['text']}」@({nm['cx']},{nm['cy']})")
            if not allow_click:
                print(f"    它那行的「前往」@({g['cx']},{g['cy']}) —— **没有点**")
                return 0
            print(f"    点它的「前往」@({g['cx']},{g['cy']})")
            _click(vs, inp, g, wait=2.5)
            vs.frame(force=True)
            ok = vs.find("确认", (700, 550, 1300, 720))
            if ok and vs.find("是否立即传送", (600, 450, 1400, 600)):
                print(f"    点「确认」@({ok['cx']},{ok['cy']})（立即传送）")
                _click(vs, inp, ok, wait=6.0)
                vs.frame(force=True)
                print("    已传送")
            else:
                print("    （没弹传送确认框）")
            return 0

        seen.extend(n["text"] for n in names)

    if not kw:
        print("\n  ↑ 面板上能去的都在这。要真去某个，把**任务名**传进来：")
        print("     python tools/zzz_agent_plan.py 苍角 --go 「征服者」")
        return 0
    if kw in LEFT_RAIL:
        print(f"\n  「{kw}」下的任务：{'、'.join(dict.fromkeys(seen))[:180]}")
        print("  一个类别下有多个 boss —— 指名一个才会点。")
        return 0

    print(f"  ✘ 滚了 {max_pages + 1} 屏都没找到「{kw}」—— **什么都没点**")
    print(f"     看到过：{'、'.join(dict.fromkeys(seen))[:200]}")
    return 4

def list_all(ui: Ui, max_pages: int = 10) -> int:
    """**把 4 个类别下的所有目标全列出来**，一个都不点。

    ## 为什么需要它

    「哪个材料该去哪个 boss」这张对照表我们没有，但**游戏里有**。
    与其去猜、去维护一张会过期的表，不如**先把可选目标列全**，
    再按名字去 `--go`。

    实现上是：逐个点左栏类别 -> 右侧滚一遍 -> 收任务名。
    左栏是**类别切换**（点它右边只剩该类别），不是行标签 ——
    这一点是截图看出来的，按 y 配对会传错副本。
    """
    vs, inp = ui.vs, ui.inp
    total = 0
    for cat in ("实战模拟室", "区域巡防", "专业挑战室", "恶名狩猎"):
        print(f"\n【{cat}】")
        _pick_rail(vs, cat)
        inp.move(1000, 700)
        time.sleep(0.25)
        for _ in range(12):
            inp.wheel(6, wait=0.2)
        vs.frame(force=True)

        seen: list[str] = []
        last = ""
        for page in range(max_pages + 1):
            if page > 0:
                inp.move(1000, 700)
                inp.wheel(-2, wait=1.0)
                try:
                    vs.wait_still(quiet=0.35, timeout=2.5)
                except Exception:
                    time.sleep(0.4)
                vs.frame(force=True)

            items = vs.items(PANEL)
            sig = "|".join(i["text"] for i in items)
            if page > 0 and sig == last:
                break
            last = sig

            names = [i["text"] for i in sorted(items, key=lambda x: x["cy"])
                     if not i["text"].startswith("前往")
                     and len(i["text"]) > 1
                     and not re.fullmatch(r"[\d,]+(\s*/\s*[\d,]+)?", i["text"])
                     and not re.fullmatch(r"\d+\s*-\s*\d+", i["text"])
                     and i["text"] not in ("双倍", "燃竭", "OD", "EMPTY")]
            for nm in names:
                if nm not in seen:
                    seen.append(nm)

        # **去重 + 去碎片**：OCR 会把一个名字读成两截，
        # 例如 `诡步与` / `诡步与重壁`，或者同一名字的两种间隔号
        # `「霸主侵蚀体·庞培」` / `「霸主侵蚀体・庞培」`。
        def _n(t: str) -> str:
            return re.sub(r"[\s「」『』·・]", "", t)

        keep: list[str] = []
        norms = [_n(x) for x in seen]
        for i, nm in enumerate(seen):
            ni = norms[i]
            if any(ni == norms[j] and j < i for j in range(len(seen))):
                continue                      # 规范化后重复
            if any(ni != norms[j] and ni in norms[j] for j in range(len(seen))):
                continue                      # 只是别人的一截
            keep.append(nm)
        for nm in keep:
            print(f"    {nm}")
        total += len(keep)
    print(f"\n  共 {total} 个目标。要真去某个："
          f"\n    python tools/zzz_agent_plan.py <角色> --go <目标名>")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="设置「特训目标」，让游戏自己路由到要刷的副本")
    ap.add_argument("agent", nargs="?", default="",
                    help="角色名，如 佩洛伊斯（--list 时可以不给）")
    ap.add_argument("--go", metavar="副本名", nargs="?", const="", default=None,
                    help="**不给值**：滚一遍面板，列出所有能去的副本（不点任何东西）。"
                         "**给值**：滚着找这个副本名，点它那一行的「前往」传送。"
                         "关键词是**副本/任务名**（代理人晋升、代理人技能、"
                         "恶名·杜拉罕…），不是材料名 —— 这个面板按副本组织")
    ap.add_argument("--list", action="store_true",
                    help="**把 4 个类别下的所有目标全列出来**，一下都不点。"
                         "用来自己查「有哪些副本可去」，不用猜")
    ap.add_argument("--dry-run", action="store_true",
                    help="只走到更换特训目标面板，不真的设置")
    args = ap.parse_args()

    if args.list:
        vs0, inp0 = Vision(), Input()
        ui0 = Ui(vs0, inp0)
        ui0.start()
        try:
            for _ in range(8):
                vs0.frame(force=True)
                if anchors.describe(vs0) == "世界":
                    break
                inp0.key("esc", wait=1.3)
            vs0.frame(force=True)
            if anchors.describe(vs0) != "世界":
                print(f"  ✘ 回不到大世界（当前 {anchors.describe(vs0)}）")
                return 4
            if not open_handbook(ui0):
                return 4
            if not open_train_tab(ui0):
                return 4
            return list_all(ui0)
        finally:
            ui0.stop()

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
                return go_to(ui, args.go, allow_click=True)
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
            return go_to(ui, args.go, allow_click=True)
        return 0
    finally:
        ui.stop()


if __name__ == "__main__":
    sys.exit(main())
