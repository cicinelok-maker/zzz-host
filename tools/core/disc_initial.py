"""驱动盘的「初始判定」：升不升，在升之前就决定。

## 用户指出的问题（2026-11-25）

> 就比如说之前那个啄木鸟1号位，你应该是先判断主词条是否正确的，
> 然后再根据它产出的初始副词条是不是全部都命中，再决定升级，懂我意思吧？
> 然后再根据情况来调整4+2的位置，反正就是好的盘先升级装着再根据后面来刷本调整，
> 而且驱动盘可能初始三条或者初始四条，我不太确定你得查查

## 实测确认（仓库 52 块 Lv0 盘）

```
初始 3 条：37 块   ← S级主流
初始 4 条：13 块   ← S级少数
初始 2 条： 2 块   ← A级紫盘
```

**所以 S 级盘是 3 或 4 条起。**

## 关键机制（决定策略的核心）

```
升级节点    Lv3 / Lv6 / Lv9 / Lv12 / Lv15  共 5 次
```

**4 条初始的盘**：5 次强化全部落在已有副词条上 → 最多 5 次命中
**3 条初始的盘**：第 1 次升级（Lv0→Lv3）**解锁第 4 条，不给强化**
                 剩下 4 次才真强化 → 最多 4 次命中

**所以 4 条初始严格优于 3 条初始**（多一次强化机会）。

## 决策流程（用户要的）

```
① 主词条对吗？
   不对 → 丢，不升（主词条错 = 这条主属性白丢，副词条再好也没用）

② 初始副词条命中几条？
   4 条全中       → 神盘，升满
   3 条中          → 好盘，升满
   2 条中          → 看主词条稀缺度：主词条对就赌，不对就丢
   0~1 条中        → 丢

③ 3 条初始的盘要单独处理：
   3 条全中 → 升到 Lv3 看第 4 条
     第 4 条也中 → 4/4 继续升
     第 4 条不中 → 3/4，还能接受，继续
   2 条中   → 升到 Lv3 看第 4 条
     第 4 条中 → 3/4 可以
     第 4 条不中 → 2/4 丢

④ 升满后根据结果调整 4+2
```

## 为什么「先判再升」比「升满再看」好

一块盘升满要 ~100+ 镀剂 + 信用点。
仓库 52 块 Lv0，如果全升满再判：
```
52 块 × 100 镀剂 = 5200 镀剂
```
按初始判，能砍掉 70% 以上 → 只升 ~15 块。

**省下的镀剂可以多升几个好盘。**
"""
from __future__ import annotations


# ---- 决策线（按「初始命中条数 / 初始总条数」）
# 注：S级3或4条、A级2或3条，实测见 explain_mechanics()
TIERS = {
    # (命中, 总数): (动作, 说明)
    (4, 4): ("max",   "4条全中，神盘，直接升满"),
    (3, 4): ("max",   "4条中3，好盘，升满"),
    (2, 4): ("maybe", "4条中2，看主词条稀缺度"),
    (1, 4): ("drop",  "4条中1，丢"),
    (0, 4): ("drop",  "4条全歪，丢"),

    (3, 3): ("probe", "3条全中，升到Lv3看第4条（值得赌）"),
    (2, 3): ("probe", "3条中2，升到Lv3看第4条"),
    (1, 3): ("drop",  "3条中1，丢"),
    (0, 3): ("drop",  "3条全歪，丢"),

    (2, 2): ("drop",  "2条中2，但只有2条，上限太低"),
    # **BUG-014：2 条盘的另外两种组合原来是缺的。**
    #
    # 缺 key 会落到 `.get(key, ("probe", …))`，也就是「花钱升到 Lv3」。
    # 结果：
    #   2 条全中 → drop（丢好盘）
    #   2 条全歪 → probe（花钱升废盘）
    # **决策完全倒挂。**
    (1, 2): ("drop",  "2条中1，只有2条，上限太低，丢"),
    (0, 2): ("drop",  "2条全歪，丢"),
}


def initial_verdict(main_ok: bool, hits: int, total: int,
                    main_is_rare: bool = False) -> dict:
    """升不升的判定。

    main_ok      主词条是否在角色推荐列表里
    hits         初始副词条里命中「有效词条」的条数
    total        初始副词条总数（3 或 4）
    main_is_rare 主词条是否稀缺（如暴击率），影响 2/4 的判定
    """
    if not main_ok:
        return {
            "action": "drop",
            "reason": "主词条不对，先丢（主属性白丢，副词条再好也补不回来）",
            "why": "main",
            "hits": hits,
            "total": total,
        }

    key = (hits, total)
    act, why = TIERS.get(key, ("probe", f"{hits}/{total}，按保守处理"))

    # 4条中2：主词条稀缺就赌
    if key == (2, 4) and main_is_rare:
        act = "probe"
        why = "4条中2，但主词条稀缺（如暴击率），值得升到Lv3看"

    return {"action": act, "reason": why, "why": "subs",
            "hits": hits, "total": total}


def report(v: dict) -> str:
    icon = {"max": "★升满", "probe": "△试探", "maybe": "?看你",
            "drop": "✘丢"}[v["action"]]
    return f"{icon}　{v['reason']}"


def explain_mechanics() -> str:
    return """驱动盘初始与升级机制（实测 + 仓库统计）

初始副词条条数：
  S 级（金）  3 条 或 4 条
  A 级（紫）  2 条 或 3 条

强化节点：Lv3 / Lv6 / Lv9 / Lv12 / Lv15　共 5 次

4 条初始：5 次强化全落在已有副词条 → 最多 5 次命中
3 条初始：Lv0→Lv3 那次**解锁第 4 条，不算强化**
          剩下 4 次才真强化（Lv6/9/12/15）→ 最多 4 次命中

结论：**4 条初始严格优于 3 条初始**（多一次强化机会）

仓库实测（52 块 Lv0）：
  3 条  37 块（71%）
  4 条  13 块（25%）
  2 条   2 块（4%，A级）
"""


def count_hits(subs: list, good: list, half: list) -> tuple[int, int, list]:
    """数初始副词条里命中几条有效词条。

    subs: discs_v2.json 里的 [{"name","value","rolls"}]，
          或 [[name, value], ...]，或字符串化的 "[name, value]"
    返回 (命中条数, 总条数, 明细)
    """
    from core import disc_stats as _ds

    good_set = set(good)
    half_set = set(half)
    hits = 0
    detail = []

    for item in subs or []:
        # 归一成 (name, value)
        name, value = "", ""
        if isinstance(item, dict):
            name = item.get("name") or ""
            value = item.get("value") or ""
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            name, value = str(item[0]), str(item[1])
        else:
            # "['攻击力', '3%']" 这种
            t = str(item).strip().strip("[]")
            parts = [x.strip().strip("'\"") for x in t.split(",")]
            if len(parts) >= 2:
                name, value = parts[0], parts[1]
            else:
                name = parts[0] if parts else ""

        # parse_value 返回 (数值, 是否百分比) 元组，不是裸数字
        parsed = _ds.parse_value(value)
        real = name
        if parsed and len(parsed) == 2:
            vnum, is_pct = parsed
            try:
                real, _rolls = _ds.resolve(name, vnum, is_pct)
            except Exception:
                real = name

        w = _ds.is_effective(real, good_set, half_set)
        if w >= 1.0:
            hits += 1
        detail.append(f"{real}={value}{'★' if w >= 1.0 else ('☆' if w > 0 else '')}")

    return hits, len(subs or []), detail


def judge_disc(subs, good, half, main_ok: bool = True,
               main_is_rare: bool = False) -> dict:
    """一块 Lv0 盘的完整判定（含命中统计）。"""
    hits, total, detail = count_hits(subs, good, half)
    v = initial_verdict(main_ok, hits, total, main_is_rare)
    v["detail"] = detail
    return v