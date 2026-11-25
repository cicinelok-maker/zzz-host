"""装备页盘位几何：从屏幕上的等级标签反推六个盘位的图标中心。

盘位是环形排布（实测坐标）：
        1            6
    2       音擎       5
        3            4

标签在图标下方约 62px。

**关键**：不能按「每档必须两个」来配对——某一边空着时那档只有一个标签，
会被误判成无效档。改成按环形中心分区：先看 y 落在上/中/下哪一档，
再看 x 在中心左边还是右边。
"""
from __future__ import annotations

import re

R_SLOTS = (900, 280, 1850, 970)
DISC_LABEL_DY = -62                      # 图标中心相对标签的偏移

# 环形中心（音擎位置），实测
CX, CY = 1345, 620

# 空盘位没有等级标签 → 用环形固定坐标兜底（实测）
# 用实测到的四个位号反推对称位置：
#   已知 6=(1570,340) 2=(1150,561) 3=(1252,782) 4=(1570,782)
#   环形中心约 (1360,561)
#   1 与 6 左右对称 -> x≈1150
#   5 与 2 左右对称 -> x≈1570
RING_FALLBACK = {
    1: (1231, 309),   # 截图量出来的空位圆圈中心
    2: (1150, 561),
    3: (1252, 782),
    4: (1570, 782),
    5: (1663, 534),   # 截图量出来的空位圆圈中心
    6: (1570, 340),
}
ROW_UP_Y = 500                      # y < 500 → 上档
ROW_LOW_Y = 760                     # y > 760 → 下档


def slot_map(vs) -> dict[int, tuple[int, int]]:
    """返回 {位号: (图标中心 x, y)}；空盘位没有标签，所以可能不全。"""
    labels = []
    for it in vs.items(R_SLOTS):
        t = it["text"]
        if not re.match(r"等级\d", t):
            continue
        if "60/60" in t:            # 音擎，不是驱动盘
            continue
        labels.append((it["cx"], it["cy"]))
    out: dict[int, tuple[int, int]] = {}
    for x, y in labels:
        if y < ROW_UP_Y:
            slot = 1 if x < CX else 6
        elif y > ROW_LOW_Y:
            slot = 3 if x < CX else 4
        else:
            slot = 2 if x < CX else 5
        out[slot] = (x, y + DISC_LABEL_DY)
    return out


def slot_xy(vs, slot: int) -> tuple[int, int] | None:
    """位号中心坐标。空位没有等级标签，用环形固定坐标兜底。"""
    got = slot_map(vs).get(slot)
    if got:
        return got
    return RING_FALLBACK.get(slot)
