"""刷本按缺口：根据当前状态算「今天该刷哪个本、刷几次」。

## 为什么需要（用户 2026-11-25）

「刷本按缺口你也继续」

现在的 `zzz_disc_daily` 固定刷 `both_dungeons()[0]`，
不考虑当前最缺什么。

## 缺口模型

对驱动盘来说，缺口的三个来源：

1. **主词条错** —— 某些位号的主词条对这个角色无效，必须换
   → 需要「该套装 + 该位号 + 正确主词条」的盘
2. **空位** —— 4 件套可能没激活
   → 需要该套装任意主词条对的盘
3. **弱位号** —— 已装但有效值低（< 2.0）
   → 需要更好的盘替换，或升级现有盘

对材料来说：
4. **技能材料缺** —— 实战模拟室
5. **核心技高维数据缺** —— 专业挑战室

## 副本 → 套装映射

`zzz_farm_plan.DUNGEON` 里已有：
```
机师与叛甲   → 呼啸沙龙、拂晓行纪
高塔与巨炮   → 啄木鸟电音、...
迅脊与裂爪   → 谶羽之誓、荆棘玫瑰
...
```

**注意每个本掉两个套装，所以期望只有一半。**

## 输出

```python
plan(agent, status, battery) -> {
    "farms": [{"dungeon","set","times","cost","why"}],
    "materials": [{"kind","times","cost","why"}],
    "left": 剩余电量,
}
```
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
META = BASE / "tools" / "disc_meta.json"

from core.game_cfg import (  # noqa: E402
    COST_PATROL, COST_CHALLENGE, COST_SIM, MAX_CARDS,
)
from core.disc_main import verdict as main_verdict  # noqa: E402
from core.game_cfg import element_of  # noqa: E402


def load_sets() -> dict:
    """套装 → 副本。

    用 zzz_farm_plan.PATROL_BY_SET（唯一权威来源），不是 DUNGEON
    （DUNGEON 是「材料 → 命令」，不是「套装 → 副本」）。

    一个副本固定掉两个套装，例如：
        机师与叛甲 → 拂晓行纪 + 呼啸沙龙
        高塔与巨炮 → 啄木鸟电音 + 灵魂摇滚/雷暴重金属/极地重金属
    所以单刷一个本，目标套装的期望只有一半。
    """
    import sys
    sys.path.insert(0, str(BASE / "tools"))
    from zzz_farm_plan import PATROL_BY_SET
    return PATROL_BY_SET


def sets_of_dungeon() -> dict:
    """副本 → 它掉的套装列表（反查，用来算掉率）。"""
    out = {}
    for st, dg in load_sets().items():
        out.setdefault(dg, []).append(st)
    return out


def analyze(agent: str, slots: list[dict]) -> list[dict]:
    """从当前 6 个位号状态里找缺口。

    slots: [{"slot","set","level","main","eff","main_verdict"}]
    返回按优先级排的缺口列表。
    """
    meta = json.loads(META.read_text(encoding="utf-8"))
    cfg = (meta.get("角色") or {}).get(agent) or {}
    want = cfg.get("主词条") or {}
    elem = element_of(agent)
    main_set = cfg.get("四件套") or ""
    alt_sets = cfg.get("两件套候选") or cfg.get("二件套候选") or []

    gaps = []
    for s in slots:
        slot = s.get("slot") or 0
        if not slot:
            continue
        main = s.get("main") or ""
        v = s.get("main_verdict") or main_verdict(main, slot, want, elem)[0]
        eff = s.get("eff") or 0.0
        cur_set = s.get("set") or ""

        if v == "bad":
            gaps.append({
                "slot": slot, "kind": "主词条错", "priority": 1,
                "set": main_set, "why": f"{slot}号位主：{main} 无效，要换",
            })
        elif not cur_set:
            gaps.append({
                "slot": slot, "kind": "空位", "priority": 2,
                "set": main_set, "why": f"{slot}号位空着，4件套可能没激活",
            })
        elif eff < 2.0:
            gaps.append({
                "slot": slot, "kind": "弱位号", "priority": 3,
                "set": cur_set, "why": f"{slot}号位有效 {eff}，偏低",
            })
    gaps.sort(key=lambda g: g["priority"])
    return gaps[:4]


def plan(agent: str, slots: list[dict], battery: int,
         need_skill: bool = False, need_core: bool = False) -> dict:
    """生成今天的刷本/材料计划。"""
    dungeons = load_sets()
    gaps = analyze(agent, slots)
    left = battery
    farms, mats = [], []

    # ---- 按缺口分配驱动盘副本
    for g in gaps:
        if left < COST_PATROL:
            break
        set_name = g["set"]
        dungeon = dungeons.get(set_name)
        if not dungeon:
            continue
        # 这个本还掉哪些别的套装（算期望用）
        others = [x for x in sets_of_dungeon().get(dungeon, []) if x != set_name]
        hit = 1.0 / (1 + len(others)) if others else 1.0
        farms.append({
            "dungeon": dungeon, "set": set_name, "times": 1,
            "cost": COST_PATROL, "why": g["why"],
            "hit_rate": hit, "also": others,
        })
        left -= COST_PATROL

    # ---- 材料缺口
    if need_skill and left >= COST_SIM * MAX_CARDS:
        n = min(left // (COST_SIM * MAX_CARDS), 3)
        mats.append({"kind": "代理人技能·共鸣测试", "cards": MAX_CARDS,
                     "times": n, "cost": n * COST_SIM * MAX_CARDS,
                     "why": "技能材料不足"})
        left -= n * COST_SIM * MAX_CARDS
    if need_core and left >= COST_CHALLENGE:
        n = min(left // COST_CHALLENGE, 3)
        mats.append({"kind": "专业挑战室·空域戒戍者", "times": n,
                     "cost": n * COST_CHALLENGE, "why": "核心技材料不足"})
        left -= n * COST_CHALLENGE

    # 同一副本的多条合并（5 号和 6 号位都要拂晓 → 一次刷 2 次同一个本）
    merged = {}
    for f in farms:
        k = f["dungeon"]
        if k in merged:
            merged[k]["times"] += 1
            merged[k]["cost"] += f["cost"]
            if f["why"] not in merged[k]["why"]:
                merged[k]["why"] += "；" + f["why"]
        else:
            merged[k] = dict(f)
    farms = list(merged.values())

    return {"farms": farms, "materials": mats, "left": left, "gaps": gaps}


def report(p: dict) -> str:
    lines = []
    if p["farms"]:
        lines.append("  驱动盘：")
        for f in p["farms"]:
            hr = f.get("hit_rate")
            hs = f"（掉率约 {hr:.0%}）" if hr else ""
            lines.append(f"    {f['dungeon']} × {f['times']}"
                         f"（{f['cost']} 电）　{f['set']}{hs}　{f['why']}")
    if p["materials"]:
        lines.append("  材料：")
        for m in p["materials"]:
            lines.append(f"    {m['kind']} × {m['times']}"
                         f"（{m['cost']} 电）　{m['why']}")
    if not p["farms"] and not p["materials"]:
        lines.append("  没有需要刷的（缺口已清或电量不足）")
    lines.append(f"  剩余电量 {p['left']}")
    return "\n".join(lines)
