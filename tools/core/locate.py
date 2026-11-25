"""按 OCR 定位可点元素，代替写死坐标。

## 为什么

同一批坐标在不同上下文里会漂：
    技能格标签实测在 1007/1181/1353/1527/1699，我写死的是 984/1158/...
    （偏 23px，格子宽所以点中了，但这是运气不是正确）

凡是 OCR 能读到的元素，就不该写死坐标。

## 提供的能力

    find_above(vs, text, dy)       某个文字上方 dy 像素的元素中心
    find_all_above(vs, pred, dy)   批量版，按 x 排序
    skill_cells(vs)                技能页五个格子（按「xx12」标签推）
    core_nodes(vs)                 核心技 A~F 六个圈
    tune_ring(vs)                  调律定向的六个分区

找不到时返回 None / 空，调用方自己决定是退回坐标还是报错。
"""
from __future__ import annotations

import re

# 代理人技能页：底部五个格子，标签形如「1012」（OCR 把「10 12」粘起来）
R_SKILL_ROW = (900, 690, 1800, 800)
SKILL_LABEL_DY = -58          # 格子图标中心相对标签

# 核心技 A~F
R_CORE = (950, 180, 1750, 560)
CORE_LABEL_DY = 0             # 字母本身就在圈中央

# 调律定向分区
R_RING = (1250, 300, 1800, 750)
RING_LABEL_DY = 0             # 数字本身就在分区上


def find_above(vs, text: str, dy: int, region=(0, 0, 1920, 1080)):
    """找到文字，返回它上方 dy 像素处的坐标"""
    hit = vs.find(text, region)
    if not hit:
        return None
    return (hit["cx"], hit["cy"] + dy)


def find_all_above(vs, pattern: str, dy: int, region=(0, 0, 1920, 1080)):
    """按正则找一批文字，返回 [(x, y)]，按 x 排序"""
    out = []
    for it in vs.items(region):
        if re.search(pattern, it["text"]):
            out.append((it["cx"], it["cy"] + dy))
    out.sort()
    return out


def skill_cells(vs) -> list[tuple[int, int]]:
    """技能页五个格子。

    标签是「当前/上限」粘在一起的形式（1012、0812、0612），
    所以按 `\\d{2}12` 匹配，取前五个，按 x 排序。
    """
    vs.frame(force=True)
    cells = []
    for it in vs.items(R_SKILL_ROW):
        if re.fullmatch(r"\d{2}12", it["text"].strip()):
            cells.append((it["cx"], it["cy"] + SKILL_LABEL_DY))
    cells.sort()
    return cells[:5]


def core_nodes(vs) -> dict[str, tuple[int, int]]:
    """核心技 A~F 六个圈。

    圈里印着字母 A~F，OCR 能读到（虽然常被过滤成单字符）。
    读不到就返回空，调用方退回坐标。
    """
    vs.frame(force=True)
    out = {}
    for it in vs.items(R_CORE):
        t = it["text"].strip()
        if re.fullmatch(r"[ABCDEF]", t):
            out[t] = (it["cx"], it["cy"] + CORE_LABEL_DY)
    return out


def tune_ring(vs) -> dict[int, tuple[int, int]]:
    """调律定向的六个分区（数字 1~6 印在分区上）"""
    vs.frame(force=True)
    out = {}
    for it in vs.items(R_RING):
        t = it["text"].strip()
        if re.fullmatch(r"[1-6]", t):
            out[int(t)] = (it["cx"], it["cy"] + RING_LABEL_DY)
    return out


def click_first(ui, candidates, label: str = "") -> bool:
    """依次尝试候选坐标，点第一个不为 None 的"""
    inp = ui.inp
    for c in candidates:
        if c:
            inp.click(c[0], c[1], wait=1.5)
            if label:
                print(f"  点「{label}」@ {c}")
            return True
    return False
