"""灰色头像 → 改成「看徽章」：S/A = 已拥有，锁 = 未解锁。

## 用户的确认（2026-11-26 10:43）

> 全都是已拥有的，看到那个带锁的图标了吗，那个就是未解锁的角色，
> 如果显示 s/a 就是解锁的

## 我前面两版都错了

**第一版**：用 HSV 饱和度判「灰」→ **错**。深色/白毛角色饱和度本来就低（33~41），
和「被去色」分不开。

**第二版**：用通道差判「去色」→ **也错**。68 个格子里
「深色角色 67%」和「疑似去色 80%」中间没有空隙，阈值定不下来。

**两版都是「猜图像特征」。真正的判据用户一句话就说了：看徽章。**

## 徽章在哪、长什么样（实测坐标）

截图 `roster_top.png`（1920x1080），11 个格子在
**「`等级N` 标签左侧 95px、同一行」**那块取样：

```
点                亮饱和像素占比   色相   饱和   亮度
(1585, 201)         41.9%        21    242   238
(1202, 202)         45.7%        22    245   235
(1428, 320)         46.3%        21    242   236
(1283, 470)         40.2%        20    247   238
… 全部一致
```

**色相 20~22 = 橙色 = S 级徽章。饱和 241+ / 亮度 232+ = 非常鲜明的色块。**

而锁图标是**白灰色**（饱和低、亮度中），和这个特征完全不同。

## 判据

```
在 (标签x - 95, 标签y) 取 ±22 的方形
  → 统计「饱和 > 150 且 亮度 > 150」的像素占比
  → 占比 > 5%  = 有彩色徽章 = S/A 级 = **已拥有**
  → 占比 ≤ 5%  = 没有彩色徽章 = 锁 = **未解锁**
```

**这是「正向检测」**（找到一个明确的东西就判定），
不是「阈值切分」（在两个挨着的值之间画线）—— 后者才是我前两版失败的原因。

## 还没验证的

**未解锁的卡片我这张截图里一个都没有**（用户说全是已拥有的）。
所以「锁的占比到底是多少」还没有实测样本。

但正向逻辑是对的：**找到彩色徽章 = 拥有**，找不到 = 未解锁（或者这个格子根本不是卡）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
# **自己在 core/ 里**，要把 tools/ 加进路径才能 `from core import ...`
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

# 徽章位置：`等级N` 标签左侧多少个像素
BADGE_DX = -95
# 取样窗口半宽
HALF = 22
# 「亮且饱和」的阈值
SAT_MIN = 150
VAL_MIN = 150
# 占比超过这个就算有徽章
FRAC_MIN = 0.05


def badge_frac(vs, label_pt: tuple[int, int]) -> float:
    """在 `等级N` 标签左侧取样，返回「亮饱和像素」占比。

    `label_pt` 是 `_scan_portraits` 返回的点，那个点等于「标签位置 - 40px」，
    所以真实标签位置是 `(x, y + 40)`。

    返回 -1 = 取不到。
    """
    img = getattr(vs, "_img", None)
    if img is None:
        return -1.0
    import cv2
    h, w = img.shape[:2]
    cx = label_pt[0] + BADGE_DX
    cy = label_pt[1] + 40            # 标签真实 y
    x0, x1 = max(0, cx - HALF), min(w, cx + HALF)
    y0, y1 = max(0, cy - HALF), min(h, cy + HALF)
    if x1 <= x0 or y1 <= y0:
        return -1.0
    patch = img[y0:y1, x0:x1]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    S = hsv[:, :, 1]
    V = hsv[:, :, 2]
    m = (S > SAT_MIN) & (V > VAL_MIN)
    return float(m.mean())


def is_owned(vs, label_pt: tuple[int, int]) -> bool | None:
    """S/A 徽章在 → 已拥有；不然 → 未解锁。

    返回 None = 取不到（没帧/越界），调用方别当 False 用。
    """
    f = badge_frac(vs, label_pt)
    if f < 0:
        return None
    return f > FRAC_MIN


def scan(vs, pts: list[tuple[int, int]]) -> list[dict]:
    """给每个格子打「徽章占比 / 是否拥有」。"""
    out = []
    for (x, y) in pts:
        f = badge_frac(vs, (x, y))
        out.append({
            "x": x, "y": y,
            "badge": f,
            "owned": (f > FRAC_MIN) if f >= 0 else None,
        })
    return out


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
    print("判据：`等级N` 左侧 95px 有彩色徽章（S/A）→ 已拥有；没徽章 → 未解锁")
    print()

    pts = pick_agent._scan_portraits(vs)
    rows = scan(vs, pts)
    owned = sum(1 for r in rows if r["owned"])
    for r in rows:
        b = r["badge"]
        tag = "已拥有" if r["owned"] else ("未解锁?" if r["owned"] is False else "取不到")
        print(f"  ({r['x']:>4},{r['y']:>4})  徽章占比 {b * 100 if b >= 0 else -1:>6.1f}%   {tag}")
    print()
    print(f"{len(rows)} 个格子里 {owned} 个有徽章（已拥有）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
