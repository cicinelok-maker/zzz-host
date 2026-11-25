"""升级节点止损：每个 Lv3/6/9/12/15 判断该不该继续。

## 用户指出的问题（2026-11-25）

> 他初始3条的话，后面升级不是还会再加一条新的吗？
> 有个极端的案例就是，那些后面的强化全部落到那个新加的第四条上了，
> 但是那个第四条是废的

## 数学

3 条初始、3 条全有效、第 4 条是废的：
```
存在分   3.0
Lv3      新第4条，无强化
剩余 4 次，命中率 3/4 = 0.75
期望     +3.0
合计     6.0

最坏（4次全砸废第4条）：
存在分   3.0 + 0 = 3.0   ← 低于 keep 线 5.0，白升
```

概率 (1/4)^4 = 0.39%，乘「第4条废」50% → 约 0.2%。

## 止损规则（用「期望最终值」判，不用「已命中数」）

```
期望最终 = 当前有效 + 剩余次数 × (有效条数 / 4)

如果 期望最终 < keep 线（5.0）→ 停
```

**为什么用期望而不是「已用几次没中」**：
因为「有效条数」不同，命中率不同，同样的未命中次数意义不一样。
- 4 条全有效、用 2 次没中 → 命中率还有 1.0，剩 3 次 → 期望 +3.0，该继续
- 4 条只有 1 条有效、用 2 次没中 → 命中率 0.25，剩 3 次 → 期望 +0.75，该停

## 实例（3条全中 + 第4条废）

```
Lv3   存在3.0  剩余4次  期望 3.0 + 4×0.75 = 6.0   ≥5.0 继续
Lv6   命中0    剩余3次  期望 3.0 + 3×0.75 = 5.25  ≥5.0 继续
Lv9   命中0    剩余2次  期望 3.0 + 2×0.75 = 4.5   <5.0 **停**
```

**在 Lv9 停，省下 Lv12 和 Lv15 的镀剂。**
"""
from __future__ import annotations

# 升级节点
MILESTONES = (3, 6, 9, 12, 15)

# 4 条副词的盘有 5 次强化，3 条的只有 4 次（Lv3 那次用来生成第 4 条）
ROLLS_4SUB = 5
ROLLS_3SUB = 4


def rolls_used(level: int, initial_subs: int) -> int:
    """到这个等级为止，已经发生了几次真正的数值强化。"""
    n = sum(1 for m in MILESTONES if level >= m)
    if initial_subs <= 3:
        n = max(0, n - 1)      # 3 条初始的第一次只解锁第 4 条，不算强化
    return n


def rolls_remaining(level: int, initial_subs: int) -> int:
    total = ROLLS_4SUB if initial_subs >= 4 else ROLLS_3SUB
    return max(0, total - rolls_used(level, initial_subs))


def expected_final(cur_eff: float, n_eff_subs: int, initial_subs: int,
                   level: int) -> float:
    """按当前状态估，升满后的期望有效值。

    cur_eff      当前已累计的有效值（口径B）
    n_eff_subs   4 条副词条里有几条是有效的
    total_subs   副词条总数（3 或 4）
    level        当前等级
    """
    rate = n_eff_subs / 4.0
    return cur_eff + rolls_remaining(level, initial_subs) * rate


def should_stop(cur_eff: float, n_eff_subs: int, initial_subs: int,
                level: int, keep_line: float = 5.0) -> dict:
    """该不该继续升级。

    返回 {"stop": bool, "reason": str, "expect": float}
    """
    if initial_subs < 4 and level < 3:
        # 还没到 Lv3，第 4 条没出来，判不了
        return {"stop": False, "reason": "还没到 Lv3，第4条未出", "expect": 0.0}

    if level >= 15:
        return {"stop": True, "reason": "已满级", "expect": cur_eff}

    exp = expected_final(cur_eff, n_eff_subs, initial_subs, level)
    left = rolls_remaining(level, initial_subs)
    used = rolls_used(level, initial_subs)

    if left == 0:
        return {"stop": True, "reason": "没有剩余强化", "expect": exp}

    if exp < keep_line:
        return {
            "stop": True,
            "reason": (f"Lv{level} 已用 {used} 次强化，期望最终 {exp:.1f} "
                       f"< {keep_line} 线 → 停，省镀剂"),
            "expect": exp,
        }

    return {
        "stop": False,
        "reason": (f"Lv{level} 已用 {used}/{used + left} 次，"
                   f"期望最终 {exp:.1f} ≥ {keep_line} → 继续"),
        "expect": exp,
    }


def report(v: dict) -> str:
    return ("■ 停　" if v["stop"] else "▶ 继续　") + v["reason"]
