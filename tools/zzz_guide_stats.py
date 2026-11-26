"""读养成指南「属性&等级」页 —— 每个关键属性的「当前 → 目标」进度条。

## 这一页为什么最有用（截图看出来的）

```
属性&等级
  穿透率        17.3% →  70.4%   ★★★
  能量自动回复   1.2  →   2.1    ★★★
  异常精通      92    →  155     ★★★

驱动盘
  当前装备驱动盘：尚未装备驱动盘
```

**这是整份养成指南里最可执行的一页** —— 它把「还差多少」量化成了数字：

· 当前值、目标值都在
· 星级表示这个属性的重要程度（★★★ = 核心）
· 右边的「当前装备驱动盘」顺便告诉你有没有装盘

之前我只用了「养成材料计算」那一个子页（算材料），
**完全没用到这一页 —— 而它直接给出「属性差多少」，比材料更接近目标。**

## 读取布局（实测）

每行是：`属性名` + `当前值(蓝色)` + `目标值(白/灰)` + `星级`
· 属性名 x ≈ 490
· 当前值 x ≈ 640，蓝色进度条的左端
· 目标值 x ≈ 800
· 星级 x ≈ 870

按 y 聚类成行，每行取「最左的中文」「两个数值」。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

BASE = HERE.parent

# 左竖排标签的位置（实测）
TAB_REGION = (150, 180, 420, 760)


def open_tab(ui, name: str) -> bool:
    """点左边的标签。"""
    import time
    vs, inp = ui.vs, ui.inp
    vs.frame(force=True)
    hit = vs.find(name, TAB_REGION)
    if not hit:
        return False
    inp.move(hit["cx"], hit["cy"])
    time.sleep(0.25)
    inp.click(hit["cx"], hit["cy"], wait=2.2)
    try:
        vs.wait_still(quiet=0.5, timeout=3.0)
    except Exception:
        time.sleep(0.4)
    vs.frame(force=True)
    return True


def read_stat_gaps(ui) -> list[dict]:
    """读「属性&等级」页的属性进度条。

    Returns `[{"属性": "穿透率", "当前": "17.3%", "目标": "70.4%"}, ...]`
    """
    vs = ui.vs
    vs.frame(force=True)
    items = vs.items((420, 180, 1500, 420))

    def t(it):
        return (it.get("text") or "").strip()

    def cx(it):
        return int(it.get("cx") or 0)

    def cy(it):
        return int(it.get("cy") or 0)

    # 按 y 聚类成行
    rows: dict[int, list] = {}
    for it in items:
        if not t(it):
            continue
        y = cy(it)
        k = next((kk for kk in rows if abs(kk - y) <= 20), y)
        rows.setdefault(k, []).append(it)

    NUM = re.compile(r"^[\d.]+%?$")
    out = []
    for y in sorted(rows):
        line = sorted(rows[y], key=cx)
        name = next((t(x) for x in line
                     if re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", t(x))
                     and "属性" not in t(x)), "")
        nums = [t(x) for x in line if NUM.fullmatch(t(x))]
        if name and len(nums) >= 2:
            out.append({"属性": name, "当前": nums[0], "目标": nums[1]})
        elif name and len(nums) == 1:
            out.append({"属性": name, "当前": nums[0], "目标": ""})
    return out


def read_disc_equipped(ui) -> str:
    """读「当前装备驱动盘」那一块的状态。

    实测：没装盘时显示「尚未装备驱动盘」。
    """
    vs = ui.vs
    vs.frame(force=True)
    txt = vs.text((900, 420, 1600, 1080))
    if "尚未装备驱动盘" in txt:
        return "尚未装备驱动盘"
    if "当前装备驱动盘" in txt:
        return "有装备（具体盘面要另读）"
    return ""


def main() -> int:
    import json
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

    if not open_tab(ui, "属性&等级"):
        print("找不到「属性&等级」标签")
        return 4

    gaps = read_stat_gaps(ui)
    discs = read_disc_equipped(ui)

    print(f"角色：{zzz_guide.current_agent(ui) or '?'}")
    print()
    print("属性缺口：")
    for g in gaps:
        print(f"  {g['属性']:<10} {g['当前']:>8} → {g['目标']:>8}")
    print()
    print(f"驱动盘：{discs or '?'}")

    out = BASE / "state" / "guide_stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"角色": zzz_guide.current_agent(ui),
                               "属性": gaps, "驱动盘": discs},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
