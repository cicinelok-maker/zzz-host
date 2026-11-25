"""彻底修正 disc_potential：命中率要用「解锁后」的词条构成。

## 完整模型（用户 2026-11-24 指出「只有三条副词条」后重做）

一块 S 级盘从 Lv0 升到 Lv15 有 5 次强化（每 3 级一次）。

### 情况 A：初始 4 条副词条
```
5 次强化全部落在已有 4 条里
每次命中概率 = 有效条数 / 4
期望增量 = 5 × (有效/4)
```

### 情况 B：初始 3 条副词条
```
第 1 次强化（Lv0→Lv3）：解锁第 4 条。
    这一次**不增加任何已有词条的数值**，而且没有数值增益。
第 2~5 次强化（Lv3→Lv15）：落在 4 条里。
    每次命中概率 = 有效条数 / 4
    ← 注意分母是 4，因为已经解锁了第 4 条
期望增量 = 4 × (有效/4)
```

### 关键：第 4 条词条不可能是有效词条

佩洛伊斯有效 = 攻击力% / 暴击率 / 暴击伤害。

一块「3 条全有效」的盘，这三条已占满，
第 4 条**只能是非有效词条**（同名词条不能重复）。

所以解锁后：有效 3 条 / 总共 4 条 = 75%。

## 啄木鸟电音[1] 的正确期望

```
当前值    3.0（3 条全有效，都没升级）
有效升级  4 次（5 次里第 1 次解锁第 4 条）
命中率    3/4 = 75%
增量      4 × 0.75 = 3.0
升满期望  3.0 + 3.0 = **6.0**
```
"""
from __future__ import annotations


# 强化里程碑：每 3 级一次，到 cap 为止
def _milestones(cap: int) -> list[int]:
    out = []
    k = 3
    while k <= cap:
        out.append(k)
        k += 3
    return out


def remain_rolls(level: int, cap: int = 15) -> int:
    """这块盘升满还能升几次（含解锁第 4 条那一次）。

    里程碑是 3/6/9/12/15，不是 (cap-level)//3。
    Lv13 → 还剩 Lv15 这一次，但 (15-13)//3 = 0 会算成 0。
    """
    if cap <= 0 or level >= cap:
        return 0
    return len([m for m in _milestones(cap) if m > level])


def needs_unlock(level: int, subs) -> bool:
    """是不是还要花一次升级解锁第 4 条副词条。"""
    n = len([s for s in subs if s.get("name")])
    return n < 4 and level < 3


def effective_rolls(level: int, cap: int, subs) -> int:
    """真正可能落在「已有词条」上的升级次数（3 条盘要扣掉解锁那一次）。"""
    r = remain_rolls(level, cap)
    if needs_unlock(level, subs):
        r = max(0, r - 1)
    return r


def hit_ratio(level: int, subs) -> float:
    """解锁后的每次命中概率 = 有效条数 / 4。

    分母固定 4：不管现在显示 3 条还是 4 条，
    升到 Lv15 时一定会有 4 条。
    """
    eff = len([s for s in subs if s.get("weight", 0) > 0])
    return eff / 4.0


def potential_eff(eff: float, level: int, cap: int, subs) -> float:
    """当前有效值 + 升满的期望增量。"""
    r = effective_rolls(level, cap, subs)
    if r == 0:
        return eff
    return round(eff + r * hit_ratio(level, subs), 2)