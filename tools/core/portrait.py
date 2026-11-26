"""灰色头像 = 未解锁：**用通道差，不用饱和度**。

## 用户说的（2026-11-26 09:40）

> 选人界面如果头像是灰色的那就是没解锁的

## 第一版错在哪（重要）

我第一版用 **HSV 的 S 通道（饱和度）**，结果完全分不开：

```
粉发角色   饱和度 147
金发角色   饱和度 138
白发角色   饱和度  41      ← 和「灰色」一个水平
黑发角色   饱和度  33      ← 和「灰色」一个水平
```

**因为「饱和度低」和「被去色」是两件事** ——
深色系/白毛角色本来饱和度就低，但它们不是灰色的。

## 正确的度量：通道差

去色的图像每个像素 **R≈G≈B** → `max(R,G,B) - min(R,G,B)` 接近 0。
而黑发角色虽然暗，R/G/B 的差别还在（偏蓝/偏暖），差值不是 0。

实测（同一张截图，12 个格子）：

```
            灰像素占比   平均通道差
粉发角色        4%        68.9
金发角色       26%        66.4
白发角色       51%        12.7
深色角色       67%        12.1
疑似去色       80%         7.5     ← 这个真的像未解锁
（背景，不是卡）100%         0.0
```

**灰像素占比 = 通道差 < 12 的像素比例。**

## 现在的状态：能用来看，但阈值还没定死

「疑似去色 80%」和「深色角色 67%」挨得太近（80 vs 67），
**没有 ground truth 就定不了阈值**。

所以：`portrait.py` 提供 **`rank()` 排序输出**，让人眼确认哪个是灰的，
而不是直接给一个「灰/不灰」的判断。

**在确认之前，`list_agents` 不调用它。**
（判错了会把「已拥有」标成「未解锁」，比现在靠「有没有等级文字」更糟。）

## 用法

```powershell
python tools/core/portrait.py            # 站在代理人列表上，按「最像灰」排序
```

输出形如：
```
按「灰像素占比」排序（越高越像未解锁）：
  (1439,1004)   80%   通道差  7.5   ← 最像
  (1283, 470)   67%   通道差 12.1
  ...
```
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
# **自己在 core/ 里**，要把 tools/ 加进路径才能 `from core import ...`
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

# 通道差低于这个值算「灰像素」
GREY_DIFF = 12


def grey_stats(vs, cx: int, cy: int,
               up: int = 95, down: int = 15, half: int = 38) -> tuple[float, float]:
    """取「标签上方那块头像区域」的 (灰像素占比, 平均通道差)。

    ## 为什么 up=95 / down=15

    实测 `_scan_portraits` 返回的点是「`等级N` 标签位置 - 40px」，
    而**标签在卡片的底部**。头像主体在标签上方约 20~110px。
    所以取 `[cy-up, cy-down]` = 标签上方 95px 到 15px 这一段。

    ## 为什么 half=38

    卡片宽度约 110~150px，取中心 ±38px 能盖住脸和头发的主要色块，
    又不会吃到左右相邻的卡片。

    Returns (-1, -1) = 取不到（越界或没有帧）。
    """
    img = getattr(vs, "_img", None)
    if img is None:
        return -1.0, -1.0
    h, w = img.shape[:2]
    y0, y1 = max(0, cy - up), min(h, cy - down)
    x0, x1 = max(0, cx - half), min(w, cx + half)
    if y1 <= y0 or x1 <= x0:
        return -1.0, -1.0
    patch = img[y0:y1, x0:x1].astype(np.int16)
    diff = patch.max(axis=2) - patch.min(axis=2)
    return float((diff < GREY_DIFF).mean()), float(diff.mean())


def rank(vs, pts: list[tuple[int, int]]) -> list[dict]:
    """给每个格子打「灰像素占比」，按从高到低排序。

    **不做「灰/不灰」的结论** —— 只给排序，让人眼判断。
    等有了 ground truth 再加阈值。
    """
    rows = []
    for (x, y) in pts:
        frac, d = grey_stats(vs, x, y)
        rows.append({"x": x, "y": y, "grey_frac": frac, "chan_diff": d})
    rows.sort(key=lambda r: -r["grey_frac"])
    return rows


def main() -> int:
    from core import Vision, Input, Ui, anchors  # noqa: E402
    from core.machine import Machine  # noqa: E402
    import live  # noqa: E402
    import pick_agent  # noqa: E402

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)
    pick_agent.reset_to_world(ui)
    if not m.go_to("代理人列表"):
        print("到不了代理人列表")
        return 3
    vs.frame(force=True)
    print(f"当前：{anchors.describe(vs)}")

    pts = pick_agent._scan_portraits(vs)
    print(f"{len(pts)} 个格子")
    print()
    print("按「灰像素占比」排序（越高越像未解锁）：")
    print(f"  {'坐标':<16}{'灰占比':>8}{'通道差':>9}")
    for r in rank(vs, pts):
        print(f"  ({r['x']:>4},{r['y']:>4})    {r['grey_frac'] * 100:>6.0f}%"
              f"{r['chan_diff']:>9.1f}")

    print()
    print("注意：这是**排序**，不是结论。")
    print("  「深色系角色」和「被去色」的占比挨得很近（实测 67% vs 80%），")
    print("  要定阈值必须先知道哪个格子确实是未解锁的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
