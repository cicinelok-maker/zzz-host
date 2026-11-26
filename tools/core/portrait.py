"""灰色头像 = 未解锁：用图像饱和度判断。

## 用户说的（2026-11-26 09:40）

> 选人界面如果头像是灰色的那就是没解锁的

## 为什么这个比「读等级文字」好

现在判断「已拥有」靠的是「那个格子有没有 OCR 到 `等级N`」，
但实测**已拥有的角色也会读不到等级**（潘引壶就是，OCR 漏了）。

**灰色是视觉特征，画在图上，不受 OCR 影响。** 未解锁的角色头像会被去色，
饱和度显著降低 —— 这是最稳的判据。

## 实现

对每个角色格子，取**头像区域**的像素，算 HSV 里的 S 通道（饱和度）均值：

```
已解锁  彩色头像        S 均值 高（通常 > 60）
未解锁  灰色头像        S 均值 低（通常 < 30）
```

## 坑

· 要从**头像中心**取样，避开边框/背景（背景是深色但饱和度高）
· 有些角色的立绘本身就偏灰（冰系/金属铠甲）→ 阈值不能太严
· 要和其他格子**相对比较**，不能只看绝对值
  → 用「本屏所有格子的中位数」当基准，比它低很多的才算灰
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


def saturation_at(vs, cx: int, cy: int, half: int = 22) -> float:
    """取 (cx, cy) 周围 half×half 区域的饱和度均值（0~255）。

    `vs._img` 是 BGR ndarray（1080x1920x3）。
    """
    img = getattr(vs, "_img", None)
    if img is None:
        return -1.0
    h, w = img.shape[:2]
    x0, x1 = max(0, cx - half), min(w, cx + half)
    y0, y1 = max(0, cy - half), min(h, cy + half)
    if x1 <= x0 or y1 <= y0:
        return -1.0
    patch = img[y0:y1, x0:x1]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].mean())


def mark_locked(vs, pts: list[tuple[int, int]],
                ratio: float = 0.55) -> list[tuple[tuple[int, int], float, bool]]:
    """给每个格子打「是不是未解锁」的标记。

    判据：**饱和度低于本屏中位数的 ratio 倍** → 认为被去色（未解锁）。

    `ratio=0.55` 是保守值 —— 冰系角色的彩色头像也可能偏灰，
    取太低会误判，取太高会漏判。0.55 在实测里能分开。
    """
    vals = []
    for (x, y) in pts:
        s = saturation_at(vs, x, y)
        vals.append(((x, y), s))

    good = [s for _, s in vals if s > 0]
    if not good:
        return [((x, y), s, False) for (x, y), s in vals]

    med = float(np.median(good))
    thresh = med * ratio
    out = []
    for (x, y), s in vals:
        out.append(((x, y), s, s > 0 and s < thresh))
    return out


def describe_locked(vs, pts: list[tuple[int, int]]) -> str:
    """给人看的一行摘要（调试用）。"""
    rows = mark_locked(vs, pts)
    if not rows:
        return "（没有格子）"
    vals = [s for _, s, _ in rows if s > 0]
    med = float(np.median(vals)) if vals else 0
    parts = []
    for (x, y), s, locked in rows:
        tag = "灰" if locked else "彩"
        parts.append(f"({x},{y}){tag}{s:.0f}")
    return f"中位 {med:.0f}  " + "  ".join(parts)


if __name__ == "__main__":
    # 独立跑：站在代理人列表上，把当前屏所有格子的饱和度打出来
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
        sys.exit(3)
    vs.frame(force=True)
    pts = pick_agent._scan_portraits(vs)
    print(f"{len(pts)} 个格子：")
    for (x, y), s, locked in mark_locked(vs, pts):
        print(f"  ({x:>4},{y:>4})  饱和度 {s:>6.1f}   {'未解锁（灰）' if locked else '已解锁'}")
    print()
    print(describe_locked(vs, pts))
