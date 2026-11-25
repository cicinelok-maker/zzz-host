"""修 tune_plan：定向调律的母盘成本是 6，不是 1。

## 实测（2026-11-25 截图确认）

```
不定向：  调律 ×01   → 3 个母盘
          调律 ×02   → 6 个母盘

定向：    调律[N]区 ×01 → 6 个母盘     ← 翻倍
          调律[N]区 ×02 → 12 个母盘
```

**定向的成本是不定向的 2 倍**（因为可以指定分区）。

## 我的 bug

`plan_tune` 里写的是：
```python
"targets": verdicts[:mother_discs]   # 母盘 7 → 7 个目标
```
**按「1 母盘 = 1 次」算的。** 实际 7 母盘只够 **1 次**定向 ×01。

## 另一个实测结论：定向是单选

- 6 个分区都在（1~6），坐标见 RING
- 但**一次只能选一个**（点新的会取消旧的）
- 选中后：圆圈变黄色 +，左侧显示「分区[N]」，底部按钮变「调律[N]区×01」

所以「一次调律只出一个指定分区的盘」，不能一次出多个区。
"""
from __future__ import annotations

from core.disc_potential import potential_eff

# ---- 母盘成本（实测）
MOTHER_PER_TUNE_PLAIN = 3      # 不指定分区 ×01
MOTHER_PER_TUNE_DIRECTED = 6   # 指定分区 ×01（翻倍）

# ---- 调律产出期望
TUNE_EXPECT_LV0 = 0.9      # Lv0 新盘，3 条副词条各 ~30% 命中
TUNE_EXPECT_MAXED = 3.9    # 再升满

# ---- 判定线
from core.disc_cfg import THRESHOLDS as _TH
TUNE_FLOOR = _TH["tune_floor"]   # 当前值低于这个才值得赌

# ---- 1~3 号位主词条固定，定向改不了
FIXED_MAIN_SLOTS = (1, 2, 3)

# ---- 定向的分区坐标
# 注意：坐标的唯一真源是 tools/zzz_tune.py 的 RING（那里有实测注释）。
# 这里不重复定义，避免以后改坐标要改两遍。
def _ring():
    import sys
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from zzz_tune import RING as _R
    return dict(_R)


RING = _ring()


def max_tunes(mother_discs: int, directed: bool = True) -> int:
    """这些母盘够调几次。"""
    cost = MOTHER_PER_TUNE_DIRECTED if directed else MOTHER_PER_TUNE_PLAIN
    return max(0, mother_discs // cost)


def tune_verdict(slot: int, cur_eff: float, cur_level: int, cur_subs: list,
                 mother_discs: int, main_verdict: str) -> dict:
    """判断这个位号该不该花母盘去定向调律。"""
    if mother_discs < MOTHER_PER_TUNE_DIRECTED:
        return {"worth": False,
                "reason": f"母盘 {mother_discs} < {MOTHER_PER_TUNE_DIRECTED}"
                          f"（定向一次要 {MOTHER_PER_TUNE_DIRECTED} 个）",
                "expect": 0.0}

    cur_pot = potential_eff(cur_eff, cur_level, 15, cur_subs)

    if not cur_subs and cur_eff == 0:
        return {"worth": True,
                "reason": f"{slot}号位空着，定向能填上",
                "gain": "空位", "expect": 0.0}

    if main_verdict == "bad":
        if slot in FIXED_MAIN_SLOTS:
            return {"worth": False,
                    "reason": f"{slot}号位主词条固定，定向改不了",
                    "expect": cur_pot}
        return {"worth": True,
                "reason": f"{slot}号位主词条无效，定向可指定分区重出",
                "gain": "主词条", "expect": cur_pot}

    if cur_pot >= TUNE_FLOOR:
        return {"worth": False,
                "reason": (f"{slot}号位潜力 {cur_pot} ≥ {TUNE_FLOOR}，"
                           f"定向产出 Lv0 期望只有 {TUNE_EXPECT_LV0}，换上是降级"),
                "expect": cur_pot}

    return {"worth": True,
            "reason": (f"{slot}号位潜力 {cur_pot} 偏低，"
                       f"定向产出期望 {TUNE_EXPECT_LV0}（升满约 {TUNE_EXPECT_MAXED}）"),
            "expect": cur_pot,
            "caveat": "副词条随机，多数情况出不来好东西"}


def plan_tune(slots: list[dict], mother_discs: int) -> dict:
    """对 6 个位号整体给定向调律建议。"""
    verdicts = []
    for s in slots:
        slot = s.get("slot") or 0
        v = tune_verdict(slot, s.get("eff") or 0.0, s.get("level") or 0,
                         s.get("subs") or [], mother_discs,
                         s.get("main_verdict") or "")
        if v["worth"]:
            verdicts.append({"slot": slot, **v})

    def rank(x):
        g = x.get("gain", "")
        return {"主词条": 0, "空位": 1}.get(g, 2)

    verdicts.sort(key=rank)
    can = max_tunes(mother_discs, directed=True)
    return {
        "mother_discs": mother_discs,
        "can_afford": can,
        "cost_each": MOTHER_PER_TUNE_DIRECTED,
        "targets": verdicts[:can],
        "skipped": verdicts[can:],
        "verdict": (f"{len(verdicts)} 个位号值得定向调律，"
                    f"母盘 {mother_discs} 块 ÷ {MOTHER_PER_TUNE_DIRECTED}/次 "
                    f"= 能做 {can} 个"),
    }


def report(p: dict) -> str:
    lines = [f"调律：{p['verdict']}"]
    if p["targets"]:
        lines.append(f"  该调（每次 {p['cost_each']} 母盘，定向单选）：")
        for t in p["targets"]:
            lines.append(f"    {t['slot']}号位　{t['reason']}")
            if t.get("caveat"):
                lines.append(f"      ⚠ {t['caveat']}")
    else:
        lines.append("  没有值得调的位号")
    if p["skipped"]:
        lines.append(f"  母盘不够，先跳过：{[t['slot'] for t in p['skipped']]}")
    return "\n".join(lines)
