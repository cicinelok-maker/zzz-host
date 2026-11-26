"""驱动盘词条识别：用「数值」反推属性名和等级，不靠 OCR 文字。

## 为什么这么做

OCR 会把「攻击力百分比」读成「攻击力」，会把噪音（'E'、'曲'、'套韭加里'）当成词条。
但**副词条的数值是固定值、不随机的**，所以可以用数值精确反推：

    生命值    112 × (1+N)      112 224 336 448 560 672
    攻击力     19 × (1+N)       19  38  57  76  95 114
    防御力     15 × (1+N)       15  30  45  60  75  90
    生命值%     3% × (1+N)      3%  6%  9% 12% 15% 18%
    攻击力%     3% × (1+N)      3%  6%  9% 12% 15% 18%
    防御力%   4.8% × (1+N)    4.8% 9.6% 14.4% 19.2%
    异常精通     9 × (1+N)       9  18  27  36  45  54
    穿透值       9 × (1+N)       9  18  27  36  45  54
    暴击率    2.4% × (1+N)    2.4% 4.8% 7.2% 9.6% 12%
    暴击伤害  4.8% × (1+N)    4.8% 9.6% 14.4% 19.2%
    穿透率    2.4% × (1+N)    2.4% 4.8% 7.2% 9.6%
    冲击力      6% × (1+N)      6% 12% 18%
    能量自动回复 3.6% × (1+N)  3.6% 7.2% 10.8%

数值只有 1-2 个候选属性时，再结合 OCR 的名字消歧。

## 主词条

    1号位 固定 生命值（2200 满级）
    2号位 固定 攻击力（316 满级）
    3号位 固定 防御力（184 满级）
    4号位 生命值%/攻击力%/防御力%/异常精通/暴击率/暴击伤害
    5号位 各属性伤害/穿透率/攻击力%
    6号位 攻击力%/生命值%/防御力%/异常掌控/冲击力/能量自动回复
"""
from __future__ import annotations

import re

# 副词条基础值（1 次 roll 的量）
SUB_BASE = {
    "生命值": 112.0,
    "攻击力": 19.0,
    "防御力": 15.0,
    "生命值百分比": 3.0,
    "攻击力百分比": 3.0,
    "防御力百分比": 4.8,
    "异常精通": 9.0,
    "穿透值": 9.0,
    "暴击率": 2.4,
    "暴击伤害": 4.8,
    "穿透率": 2.4,
    "冲击力": 6.0,
    "能量自动回复": 3.6,
    "异常掌控": 2.4,
}

# 主词条满级值（15 级）
MAIN_MAX = {
    "生命值": 2200.0,
    "攻击力": 316.0,
    "防御力": 184.0,
    "生命值百分比": 30.0,
    "攻击力百分比": 30.0,
    "防御力百分比": 48.0,
    "异常精通": 92.0,
    "暴击率": 24.0,
    "暴击伤害": 48.0,
    "穿透率": 24.0,
    "属性伤害": 60.0,
    "冲击力": 18.0,
    "能量自动回复": 60.0,
    "异常掌控": 24.0,
}

# 4/5/6 号位可选主词条
SLOT_MAIN = {
    1: ["生命值"],
    2: ["攻击力"],
    3: ["防御力"],
    4: ["生命值百分比", "攻击力百分比", "防御力百分比",
        "异常精通", "暴击率", "暴击伤害"],
    5: ["属性伤害", "穿透率", "攻击力百分比", "生命值百分比", "防御力百分比"],
    6: ["攻击力百分比", "生命值百分比", "防御力百分比",
        "异常掌控", "冲击力", "能量自动回复"],
}


def parse_value(txt: str) -> tuple[float, bool] | None:
    """从文本里取数值，返回 (数值, 是否百分比)"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(%)?", txt)
    if not m:
        return None
    return float(m.group(1)), bool(m.group(2))


def rolls_from_value(value: float, is_pct: bool) -> dict[str, int]:
    """给定数值，返回 {可能的属性名: roll 次数}"""
    out = {}
    for name, base in SUB_BASE.items():
        # BUG-013：真实上限是「1 次初始 + 5 次强化」= 基础值的 6 倍，
        # 即 n ∈ {0..5}。原来 `range(0, 8)` 允许 n=6,7，
        # 把 24%（= 2.4 × 10）解析成 rolls=7，单条被抬到 8 分。
        for n in range(0, 6):
            target = base * (1 + n)
            if abs(value - target) < 0.06 * max(1.0, target * 0.02):
                out[name] = n
                break
    return out


def resolve(name_hint: str, value: float, is_pct: bool) -> tuple[str, int]:
    """综合 OCR 名字和数值，定出 (属性名, 升级次数)"""
    cands = rolls_from_value(value, is_pct)
    if not cands:
        return (name_hint or "?", 0)

    # 名字里可能带 +N（OCR 常把「攻击力+1」当整体），先剥掉
    hint = re.sub(r"\+\d+", "", (name_hint or "")).strip()
    # 名字直接命中候选
    for c in cands:
        if c == hint or c.startswith(hint) or hint.startswith(c):
            return c, cands[c]
    # 百分比/平A 消歧：带 % 的优先取百分比类
    if is_pct:
        pct = [c for c in cands if c.endswith("百分比") or c.endswith("率")
               or c.endswith("伤害") or "%" in c]
        if len(pct) == 1:
            return pct[0], cands[pct[0]]
        if hint in ("攻击力", "生命值", "防御力"):
            for c in pct:
                if c.startswith(hint):
                    return c, cands[c]
    else:
        flat = [c for c in cands if not c.endswith("百分比")]
        if len(flat) == 1:
            return flat[0], cands[flat[0]]
        if hint in ("攻击力", "生命值", "防御力") and hint in flat:
            return hint, cands[hint]
    # **名字是已知属性时，以名字为准，不要换属性。**
    #
    # 走到这里说明「名字和数值对不上」。属性名是固定词表，
    # OCR 读错名字的概率远低于读错数字 —— 所以相信名字，rolls 记 0。
    #
    # 原来的兜底是 `k = list(cands)[0]`，随便挑一个候选：
    # 实测 `resolve('防御力百分比', 7.2, True)` → `('暴击率', 2)`，
    # 于是防护角色的防御词条被按暴击率算分，等于白算。
    if hint in SUB_BASE:
        base = SUB_BASE[hint] or 1.0
        n_exact = value / base - 1.0
        n_round = round(n_exact)
        if abs(n_exact - n_round) < 0.08 and 0 <= n_round <= 5:
            return hint, n_round
        # 数值明显对不上这个名字 → 保留名字，rolls 记 0（可信度低）
        return hint, 0

    # 名字不在词表里（OCR 读残）才退回按数值挑
    k = list(cands)[0]
    return k, cands[k]


def is_effective(name: str, good: set[str], half: set[str]) -> float:
    """返回该词条的有效权重（1.0 / 0.5 / 0）"""
    if name in good:
        return 1.0
    if name in half:
        return 0.5
    return 0.0


def main_value_at(name: str, level: int, cap: int = 15) -> float | None:
    """某等级下主词条应有的数值。

    实测反推的公式（9 个样本全部吻合）：
        value = max/4 + (max*3/4) * (level / cap)

    Lv0 时是满级的 1/4，逐级线性增长到满级。
    """
    mx = MAIN_MAX.get(name)
    if mx is None:
        return None
    return mx / 4 + (mx * 3 / 4) * (min(level, cap) / max(1, cap))


def check_main(name: str, value: float, level: int, cap: int = 15,
               tol: float = 0.05) -> bool:
    """校验一个主词条数值在指定等级下是否合理"""
    expect = main_value_at(name, level, cap)
    if expect is None:
        return False
    return abs(value - expect) <= max(0.4, expect * tol)