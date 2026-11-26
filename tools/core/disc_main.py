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
#
# **BUG-010**：原来只有 5 项（火/冰/电/物理/以太），而 `disc_meta.json` 里
# 实际出现的伤害词条有 8 种写法（含 `风属性伤害加成`，以及
# `以太伤害加成` 和 `以太属性伤害加成` 两种写法并存）。
#
# 更要命的是**变体属性**：烈霜 / 玄墨 / 凛刃。
# 它们不是「另一个属性」，而是冰/以太/物理的变体 ——
# 烈霜角色装「冰属性伤害加成」是**对的**。
# 原来用 `e != element` 直接比较，`冰 != 烈霜` 恒真 → 判 bad，
# 于是**正确的主词条被当成废条**，那块盘会被换掉。
#
# 现在按「同族」判定：属性 → 能用的属性名集合。
ELEM_FAMILY = {
    "火": ("火",),
    "冰": ("冰", "烈霜"),
    "电": ("电",),
    "物理": ("物理", "凛刃"),
    "以太": ("以太", "玄墨"),
    "风": ("风",),
    "流明": ("流明",),
    # 反向也认：拿变体名当角色属性时，也接受基属性的词条
    "烈霜": ("冰", "烈霜"),
    "玄墨": ("以太", "玄墨"),
    "凛刃": ("物理", "凛刃"),
}


def elem_terms(element: str) -> set[str]:
    """该角色属性**能用**的所有伤害词条写法（含同族变体 + 泛称）。

    同时覆盖游戏里并存的两种写法：
    · `X伤害加成`（以太伤害加成）
    · `X属性伤害加成`（冰属性伤害加成）
    """
    fams = ELEM_FAMILY.get(element, (element,))
    # **不要把裸「属性伤害」放进来**：它是配置里的模板词，
    # 而且作为子串会匹配到所有 `X属性伤害加成`（实测让冰角色认下风伤害）。
    out = set()
    for f in fams:
        out.add(f"{f}伤害加成")
        out.add(f"{f}属性伤害加成")
    return {_norm(x) for x in out}


def elem_family(element: str) -> tuple[str, ...]:
    return ELEM_FAMILY.get(element, (element,))


# 所有出现过的伤害词条写法（用来判断「这是不是一条属性伤害词条」）
ALL_ELEM_TERMS = set()
for _fams in ELEM_FAMILY.values():
    for _f in _fams:
        ALL_ELEM_TERMS.add(f"{_f}伤害加成")
        ALL_ELEM_TERMS.add(f"{_f}属性伤害加成")
# 注意：归一化要在 `_norm` 定义之后做（见文件下方），这里不能算。

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



# 属性伤害词条的归一化集合（必须在 `_norm` 之后才算）
_ALL_ELEM_NORM = {_norm(x) for x in ALL_ELEM_TERMS}
def expand_want(slot: int, want: dict, element: str = "") -> list[str]:
    """把配置里的泛称展开成具体词条名。

    want 形如 {"5": ["属性伤害", "攻击力"]}
    element = "以太" 时，「属性伤害」→「以太伤害加成」
    """
    out = []
    for w in (want.get(str(slot)) or want.get(slot) or []):
        w = _norm(w)
        if w in GENERIC_ELEM:
            # **「属性伤害」这类泛称要按角色的属性族展开**（BUG-010）。
            # 原来只按 `e == element` 精确匹配，于是：
            #   · 烈霜角色 → 匹配不到「冰」，泛称一条都不展开
            #   · 风角色   → ELEM_DMG 里根本没有「风」，同样展开不出
            # 结果这些角色的「属性伤害」主词条永远判不到 good。
            for term in sorted(elem_terms(element)):
                out.append(term)
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

    # **属性伤害词条优先、精确判定**（BUG-010）
    #
    # 必须放在下面的子串匹配之前 —— 否则 `属性伤害` 作为子串
    # 会匹配到所有 `X属性伤害加成`，冰角色会把风伤害认成 good。
    if m in _ALL_ELEM_NORM:
        if element == "特殊":
            return "weak", "该角色伤害属性随队伍变化，这条可能有用"
        if not element:
            return "unknown", "读不到角色属性，无法判断这条属性伤害"
        if m in elem_terms(element):
            fam = "/".join(elem_family(element))
            return "good", f"{fam} 族的属性伤害，对{element}角色有效"
        return "bad", f"这条属性伤害不在{element}的同族里"

    wants = [_norm(x) for x in expand_want(slot, want, element)]
    if any(w == m or w in m or m in w for w in wants):
        return "good", "在推荐列表里"

    # 伤害属性会变的角色（蕾米埃尔「属性流变」）：
    # 任何属性伤害都可能有用，但不确定 → weak
    if element == "特殊":
        if m in _ALL_ELEM_NORM:
            return "weak", "该角色伤害属性随队伍变化，这条可能有用"

    if any(_norm(w) in m or m in _norm(w) for w in WEAK_OK.get(slot, [])):
        return "weak", "不在推荐里，但还能用"

    return "bad", "对这个角色没用"


def report(results: list[dict]) -> str:
    """给人看的一段话。"""
    lines = []
    for r in results:
        mark = {"good": "✔", "weak": "~", "bad": "✘", "unknown": "?"}[r["verdict"]]
        lines.append(f"  {mark} {r['slot']}号位 {r['main'] or '?':<14} {r['note']}")
    # BUG-070：summarize() 全文件没有定义 —— 调用就 NameError。
    # 这里只需要「哪些位号主词条无效」，直接算，不引入新函数。
    bad_slots = [r["slot"] for r in results if r.get("verdict") == "bad"]
    if bad_slots:
        lines.append(f"  → **{len(bad_slots)} 个位号主词条无效：{bad_slots}**")
    return "\n".join(lines)