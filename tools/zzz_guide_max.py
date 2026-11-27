"""把所有技能滑块拉到最右（满级）。

## 实测出来的关键行为

拖动滑块到**超过右侧标签的位置**，上限会变：

```
拖之前：普通攻击 Lv.1 ──●────── Lv.7      上限 7
拖之后：普通攻击 Lv.1 ──────────● Lv.12   上限 12  ← 拉满
```

**所以「拉满」靠的就是「拖到比标签更右」**，不是点标签。

## 怎么找拇指

在轨道区间 `x ∈ [900, 1320]`（避开左右两侧的 `Lv.N` 文字）里，
逐列取灰度均值，**最亮的那一列就是拇指**（实测 亮度 85 vs 轨道中位 58）。

## 怎么拖

从拇指位置拖到 `x = 1315`（轨道最右）。
`Input.drag` 已经实现「按下 → 分段移动 → 抬起」，分段是为了不丢鼠标移动事件。

**实测 2/3 成功**，支援技那次没动（可能抓的时候拇指还在动画中）。
所以每个滑块拖完要**重新测拇指位置**确认变了，没变就重试。

## 滚动

面板一屏放不下 6 个技能 + 核心技 + 音擎，要滚动。
**一次滚 2~3 格**（滚太多会把内容滚出视野 —— 用户提醒过）。
## 【结论：这个工具不是必需的，别接进主流程】

实测拖动**能生效**（普通攻击从 `Lv.7` 变 `Lv.12`），但：

**1 拇指检测不稳**
轨道左边是 `Lv.1` 文字、右边是 `Lv.7` 标签，拇指是中间那个亮点。
灰度最亮法会在「标签变宽」之后把文字误当拇指（实测把 862 的 `Lv.1` 认成拇指）。
放宽区间反而更差：3/5 → 1/5。

**2 更重要的是：「拉满」在语义上是错的**
游戏给的默认值是它**推荐**的培养目标：
```
普通攻击 Lv.7     特殊技 Lv.12    核心技 Lv.7
闪避     Lv.7     连携技 Lv.9
支援技   Lv.7
```
**它并不要求每个技能都满级。** 强行拉满会多算一堆用不上的材料，
刷完就是浪费电量。

**所以主流程应该「直接点确定，用游戏推荐值」，不用拖滑块。**

这个工具留着是因为拖动能力（`Input.drag`）本身有用（以后别的地方可能要拖），
但 `zzz_gap` 不该调 `maximize_all()`。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# 轨道区间（避开两侧 Lv 文字）
# **轨道区间要够宽** —— 拖动之后右侧标签从 `Lv.7` 变 `Lv.12`（更宽），
# 轨道起点会跟着右移，拇指可能落在 900 左边。实测支援技的拇指就在 928 附近，
# 而它属于「拇指在最左」的状态 —— 说明真实位置还要更左。
TRACK_X0, TRACK_X1 = 900, 1320
# 拖到最右的目标
DRAG_TO = 1315
# 拇指亮度要比轨道中位高这么多才算找到
BRIGHT_MIN = 15


def thumb_x(vs, y: int) -> tuple[int, float, float]:
    """在 y 那一行找滑块拇指的 x。返回 (x, 亮度, 轨道中位)。"""
    img = getattr(vs, "_img", None)
    if img is None:
        return -1, 0.0, 0.0
    h, w = img.shape[:2]
    y0, y1 = max(0, y - 16), min(h, y + 16)
    x0, x1 = max(0, TRACK_X0), min(w, TRACK_X1)
    if y1 <= y0 or x1 <= x0:
        return -1, 0.0, 0.0
    patch = img[y0:y1, x0:x1]
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
    col = gray.mean(axis=0)
    idx = int(np.argmax(col))
    return x0 + idx, float(col.max()), float(np.median(col))


def find_slider_rows(vs) -> list[tuple[int, str]]:
    """在当前屏找所有滑块行。返回 [(y, 项目名)]。"""
    NAMES = ("普通攻击", "闪避", "支援技", "特殊技", "连携技", "核心技", "音擎")
    rows = []
    for it in vs.items((450, 500, 750, 1050)):
        t = (it.get("text") or "").strip()
        if t in NAMES:
            rows.append((int(it.get("cy") or 0), t))
    rows.sort()
    return rows


def drag_one(ui, y: int, retries: int = 3) -> bool:
    """把 y 那一行的滑块拖到最右。返回是否确认变了。"""
    import time
    vs, inp = ui.vs, ui.inp
    for k in range(retries):
        tx, tv, tm = thumb_x(vs, y)
        if tx < 0 or (tv - tm) < BRIGHT_MIN:
            print(f"      y={y} 找不到拇指（亮度差 {tv - tm:.0f}）")
            return False
        if tx >= DRAG_TO - 15:
            return True                      # 已经在最右
        if k > 0:
            print(f"      重试 {k}：拇指在 {tx}")
        inp.move(tx, y)
        time.sleep(0.35)
        inp.drag(tx, y, DRAG_TO, y, wait=1.0, hold=0.25, steps=30)
        vs.frame(force=True)
        tx2, _, _ = thumb_x(vs, y)

        # **必须是「往右动了」**，不是「动了」（E33）。
        #
        # 原来是 `if abs(tx2 - tx) > 8: return True` —— 方向反了也算成功。
        # 拖动失败时拇指常常会**弹回**一点，`abs()` 把那个也当成成功，
        # 于是工具以为「已拉满」，实际技能等级没动，后面的判断全建立在假前提上。
        #
        # 现在：向右动超过 8px 才算；否则打印方向，让下一次重试看得见。
        if tx2 > tx + 8:
            return True
        if tx2 >= DRAG_TO - 15:
            return True                      # 已经到达最右（窄幅也算成）
        print(f"      y={y} 拖了但没往右走：{tx} -> {tx2}"
              f"（{'+' if tx2 >= tx else ''}{tx2 - tx}px）")
    return False


def maximize_all(ui, max_scroll: int = 10) -> dict:
    """把所有技能的滑块拉到最右。返回 {项目名: 是否成功}。"""
    import time
    vs, inp = ui.vs, ui.inp
    result: dict = {}

    # 滚到顶
    inp.move(900, 600)
    time.sleep(0.2)
    for _ in range(12):
        inp.wheel(6, wait=0.25)
    vs.frame(force=True)

    for step in range(max_scroll + 1):
        if step > 0:
            inp.move(900, 600)
            inp.wheel(-3, wait=1.0)          # 小步滚
            vs.frame(force=True)

        rows = find_slider_rows(vs)
        new_this_round = 0
        for y, name in rows:
            if name in result:
                continue
            new_this_round += 1
            ok = drag_one(ui, y)
            result[name] = ok
            print(f"    {name}: {'✔ 拉满' if ok else '✘'}")

        # **不管这一屏有没有新行都要继续往下滚** ——
        # 原来写的是「没有新行就 break」，但滚到底之前
        # 下面还有 特殊技 / 连携技 / 核心技 没出现在视野里。
        # 现在靠「画面文本没变」判断到底。
        if new_this_round == 0 and step > 0:
            _sig = vs.text((450, 480, 1500, 1050))
            if _sig == getattr(maximize_all, "_last_sig", ""):
                break
            maximize_all._last_sig = _sig
    return result


def main() -> int:
    from core import Vision, Input, Ui, anchors
    import zzz_guide

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()

    for _ in range(4):
        inp.key("esc", wait=1.4)
        vs.frame(force=True)
        if anchors.describe(vs) == "世界":
            break
    if not zzz_guide.open_guide(ui):
        print("进不去养成指南")
        return 3

    # 打开材料计算面板
    vs.frame(force=True)
    hit = vs.find("养成材料计算", (800, 190, 1100, 280))
    if not hit:
        print("找不到「养成材料计算」按钮（要先在方案概览视图）")
        return 4
    inp.move(hit["cx"], hit["cy"])
    inp.click(hit["cx"], hit["cy"], wait=2.5)

    print("拉满所有技能滑块…")
    res = maximize_all(ui)
    ok = sum(1 for v in res.values() if v)
    print(f"\n{ok}/{len(res)} 拉满")

    # 确定
    vs.frame(force=True)
    okb = vs.find("确定", (900, 880, 1450, 980))
    if okb:
        inp.move(okb["cx"], okb["cy"])
        inp.click(okb["cx"], okb["cy"], wait=3.0)
        print("已点「确定」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
