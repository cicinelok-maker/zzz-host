"""主词条校验：这个位号的主词条适不适合这个角色。

## 为什么需要（2026-11-25 用户追问后查证发现）

社区攻略写得很明确：「**主词条错就丢，连副词条都不必看**」。

但我的整套判断链从来没检查过主词条：
- `zzz_status` 只读主词条**显示**出来，不判断对不对
- `zzz_plan` / `zzz_disc_cycle` / `zzz_disc_daily` 全只比副词条有效值
- `core/disc_stats.check_main` 只校验「数值和名字是否匹配」，
  不校验「这个主词条适合这个角色吗」

结果：佩洛伊斯 5 号位出「火属性伤害加成」（她是**以太**属性），
6 号位出「能量自动回复」（应该要攻击力%），
两个位号的主词条**完全无效**，但所有工具都报「正常」。

## 判定规则

`disc_meta.json` 里每个角色有：
```json
"主词条": {"4": ["暴击率", "暴击伤害"], "5": ["属性伤害", "攻击力"], "6": ["攻击力"]}
```

判定分三档：
- `good`   主词条在推荐列表里
- `weak`   不在推荐里但能用（比如 5 号位的穿透率——有减防队友时更好）
- `bad`    完全无效（比如以太角色的火伤）

**「属性伤害」要展开成具体属性**：以太角色只认「以太伤害加成」，
火伤对她是 `bad`。

## 输出

```python
verdict("火属性伤害加成", 5, want, element="以太")
# → ("bad", "火属性伤害对以太角色无效")
```
"""
from __future__ import annotations

# 属性伤害 → 对应的属性名
ELEM_DMG = {
    "火": "火属性伤害加成",
    "冰": "冰属性伤害加成",
    "电": "电属性伤害加成",
    "物理": "物理伤害加成",
    "以太": "以太伤害加成",
}

# 「属性伤害」这类泛称要按角色属性展开
GENERIC_ELEM = ("属性伤害", "属性伤害加成")

# 这些主词条对任何输出角色都基本能用（弱但不废）
WEAK_OK = {
    4: ["攻击力百分比", "攻击力"],
    5: ["穿透率", "攻击力百分比", "攻击力"],
    6: ["攻击力百分比", "攻击力"],
}


def _norm(name: str) -> str:
    """去掉空格和百分号写法差异。"""
    return (name or "").replace(" ", "").replace("％", "%").strip()


def expand_want(slot: int, want: dict, element: str = "") -> list[str]:
    """把配置里的泛称展开成具体词条名。

    want 形如 {"5": ["属性伤害", "攻击力"]}
    element = "以太" 时，「属性伤害」→「以太伤害加成」
    """
    out = []
    for w in (want.get(str(slot)) or want.get(slot) or []):
        w = _norm(w)
        if w in GENERIC_ELEM:
            for e, full in ELEM_DMG.items():
                if e == element:
                    out.append(full)
        elif w == "攻击力":
            # 攻击力 既可以指实数也可以指百分比，两个都认
            out.extend(["攻击力百分比", "攻击力"])
        else:
            out.append(w)
    return out


def verdict(main: str, slot: int, want: dict, element: str = "") -> tuple[str, str]:
    """判定主词条。

    返回 (等级, 说明)：
        ("good", "在推荐列表里")
        ("weak", "不在推荐里但能用")
        ("bad",  "对这个角色无效")
        ("unknown", "读不到主词条")
    """
    m = _norm(main)
    if not m:
        return "unknown", "读不到主词条"

    # 1~3 号位主词条固定，不用判
    if slot <= 3:
        return "good", "1~3号位主词条固定"

    wants = [_norm(x) for x in expand_want(slot, want, element)]
    if any(w == m or w in m or m in w for w in wants):
        return "good", "在推荐列表里"

    # 伤害属性会变的角色（蕾米埃尔「属性流变」）：
    # 任何属性伤害都可能有用，但不确定 → weak
    if element == "特殊":
        for e, full in ELEM_DMG.items():
            if full == m:
                return "weak", "该角色伤害属性随队伍变化，这条可能有用"

    # 属性伤害但属性不对 → 完全废
    for e, full in ELEM_DMG.items():
        if full == m and element and e != element:
            return "bad", f"{e}属性伤害对{element}角色无效"

    if any(_norm(w) in m or m in _norm(w) for w in WEAK_OK.get(slot, [])):
        return "weak", "不在推荐里，但还能用"

    return "bad", "对这个角色没用"


def report(results: list[dict]) -> str:
    """给人看的一段话。"""
    lines = []
    for r in results:
        mark = {"good": "✔", "weak": "~", "bad": "✘", "unknown": "?"}[r["verdict"]]
        lines.append(f"  {mark} {r['slot']}号位 {r['main'] or '?':<14} {r['note']}")
    s = summarize(results)
    if s["bad_slots"]:
        lines.append(f"  → **{len(s['bad_slots'])} 个位号主词条无效：{s['bad_slots']}**")
    return "\n".join(lines)