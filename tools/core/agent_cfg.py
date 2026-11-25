"""角色配置的统一入口：具体角色数据 → 职业模板回退。

## 问题（用户 2026-11-25）

> 当前的大闭环只是基于我们的角色库编写的，把所有角色都整进去吧

查出来的两个真问题：

**1 `职业模板` 是躺着的**
`disc_meta.json` 里有「职业模板」（强攻/异常/击破…的默认配置），
但**没有任何代码读它**。搜 5 个主要文件，`职业模板` 全是 False。

**2 角色没数据时，工具拿到空集**
`zzz_status` / `zzz_plan` / `zzz_disc_train` 都是直接
`cfg.get("有效副词条") or []` —— 角色没配就是空集，
于是**所有词条都被判成无效**，质量分恒为 0。

`disc_meta.json` 里 14 个角色有 **7 个缺「定位」**，就是这个状态。

## 修法

统一入口 `cfg_of(name)`：

```
具体角色有「有效副词条」 → 直接用
只有「定位」           → 职业模板[定位] + 角色自己的字段（角色优先）
什么都没有             → 职业模板["强攻"] + 警告
```

**这样任意角色都能跑**，哪怕没手工配过。

## 为什么按「定位」回退而不是瞎猜

ZZZ 的驱动盘副词条优先级**主要由定位决定**：
- 强攻 → 双暴
- 异常 → 异常精通
- 击破 → 冲击力
- 支援 → 能量回复 / 攻击
- 防护 → 防御 / 生命

同定位的角色，副词条优先级基本一致。**所以模板回退是有依据的，不是瞎猜。**
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent
META = HERE.parent / "disc_meta.json"

DEFAULT_ROLE = "强攻"

# 定位别名 → 模板键
ROLE_ALIAS = {
    "强攻": "强攻", "攻击": "强攻", "attack": "强攻", "强攻型": "强攻",
    "异常": "异常", "anomaly": "异常",
    "击破": "击破", "stun": "击破", "震撼": "击破",
    "支援": "支援", "support": "支援", "辅助": "支援",
    "防护": "防护", "defense": "防护", "坦克": "防护",
}

_cache: dict | None = None


def meta() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(META.read_text(encoding="utf-8"))
        except Exception:
            _cache = {"角色": {}, "职业模板": {}}
    return _cache


def role_of(name: str) -> str:
    """这个角色是什么定位。找不到返回默认。"""
    from core.agent_name import canonical_agent
    c = (meta().get("角色") or {}).get(canonical_agent(name)) or {}
    raw = c.get("定位") or c.get("岗位") or ""
    return ROLE_ALIAS.get(raw, raw or DEFAULT_ROLE)


def cfg_of(name: str, warn: bool = False, strict: bool = False) -> dict:
    """取角色配置，缺失字段用职业模板补。

    返回的 dict 一定有：定位/有效副词条/次选副词条/主词条/四件套

    角色名会先归一化（去书名号 / 繁转简 / 查别名），
    所以「蕾米埃爾」「「11号」」这些写法都能命中。
    """
    from core.agent_name import canonical_agent
    canon = canonical_agent(name)

    if strict:
        chars_ = meta().get("角色") or {}
        if canon not in chars_:
            raise UnknownAgent(str(name), suggest(name))

    m = meta()
    chars = m.get("角色") or {}
    tpls = m.get("职业模板") or {}

    own = dict(chars.get(canon) or chars.get(name) or {})
    role = role_of(name)
    tpl = dict(tpls.get(role) or tpls.get(DEFAULT_ROLE) or {})

    # 模板打底，角色自己的字段覆盖
    out = {}
    for k in ("定位", "有效副词条", "次选副词条", "主词条"):
        if own.get(k):
            out[k] = own[k]
        elif tpl.get(k):
            out[k] = tpl[k]

    # 角色独有的字段原样带上
    for k, v in own.items():
        if k not in out:
            out[k] = v

    out["定位"] = own.get("定位") or own.get("岗位") or role
    out["_来源"] = "角色" if own.get("有效副词条") else "职业模板"

    if warn and out["_来源"] == "职业模板":
        print(f"  ⚠ 「{name}」没有专门配置，用职业模板「{out['定位']}」推断")
        print(f"     要精确的话在 tools/disc_meta.json 里补「{name}」")

    return out


def element_of(name: str) -> str:
    """属性（物理/火/冰/电/以太）。优先 disc_meta，其次 state/agent_elements.json。"""
    # 1) disc_meta 自己写的
    from core.agent_name import canonical_agent
    c = (meta().get("角色") or {}).get(canonical_agent(name)) or {}
    e = c.get("属性") or c.get("元素") or ""
    if e:
        return e
    # 2) game_cfg.AGENT_ELEMENT（23 个，最完整的手工表）
    try:
        from core.game_cfg import element_of as _go
        e = _go(name)
        if e:
            return e
    except Exception:
        pass
    # 3) state/agent_elements.json（从游戏读的，可能不全）
    p = BASE / "state" / "agent_elements.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return (d.get(name) or {}).get("属性") or ""
        except Exception:
            pass
    return ""


def known() -> list[str]:
    return sorted((meta().get("角色") or {}).keys())


def report(name: str | None = None) -> str:
    m = meta()
    chars = m.get("角色") or {}
    if name:
        c = cfg_of(name, warn=True)
        lines = [f"「{name}」配置来源：{c['_来源']}",
                 f"  定位     {c['定位']}",
                 f"  四件套   {c.get('四件套') or '（未配）'}",
                 f"  主词条   {c.get('主词条')}",
                 f"  有效副词条 {c['有效副词条']}",
                 f"  次选副词条 {c['次选副词条']}"]
        return "\n".join(lines)

    lines = [f"角色库：{len(chars)} 个"]
    from collections import Counter
    src = Counter()
    for n in chars:
        src[cfg_of(n)["_来源"]] += 1
    lines.append(f"  有专门配置：{src['角色']} 个")
    lines.append(f"  靠模板推断：{src['职业模板']} 个")
    return "\n".join(lines)


# ============================================================ 严格校验

class UnknownAgent(KeyError):
    """角色不在库里。"""

    def __init__(self, name: str, suggestions: list[str]):
        self.agent = name
        self.suggestions = suggestions
        msg = f"角色「{name}」不在角色库里"
        if suggestions:
            msg += f"，你是不是想输：{suggestions}"
        else:
            msg += f"。可用角色见 tools/disc_meta.json（共 {len(known())} 个）"
        super().__init__(msg)


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein 距离（只用于短名字，不需要优化）。"""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if not la:
        return lb
    if not lb:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,        # 删除
                           cur[j - 1] + 1,     # 插入
                           prev[j - 1] + (ca != cb)))  # 替换
        prev = cur
    return prev[-1]


def suggest(name: str, limit: int = 3) -> list[str]:
    """给出最接近的几个角色名。"""
    from core.agent_name import normalize_name
    n = normalize_name(name)
    if not n:
        return []
    scored = []
    for k in known():
        d = _edit_distance(n, normalize_name(k))
        # 也考虑「包含」关系（输「洛伊斯」应该能想到「佩洛伊斯」）
        if n in normalize_name(k) or normalize_name(k) in n:
            d = min(d, 1)
        scored.append((d, k))
    scored.sort()
    # 只建议「真的很像」的：距离 <= 1（差一个字）。
    # 距离 >= 2 的建议没意义 —— 会把「佩洛依斯」的候选拖成 3 个，
    # 导致本可以自动纠正的变成报错。
    return [k for d, k in scored if d <= 1][:limit]


def resolve_agent(name: str, allow_unknown: bool = False) -> str:
    """把用户输入解析成库里的正式角色名。

    找不到就抛 UnknownAgent（带建议）。
    **不返回默认值** —— 静默走默认是最糟的失败方式。

    allow_unknown=True 时，认不出就返回归一化后的名字
    （调用方要在输出里明确警告「判定可能不准」）。
    """
    from core.agent_name import canonical_agent
    if not name or not str(name).strip():
        raise UnknownAgent(str(name or ""), [])
    canon = canonical_agent(name)
    chars = meta().get("角色") or {}
    if canon in chars:
        return canon
    # 归一化后还不在 → 模糊找
    sug = suggest(name)
    if len(sug) == 1:
        return sug[0]          # 只有一个候选，直接用
    if allow_unknown:
        # 显式允许未知角色：返回归一化名，让调用方自己警告
        from core.agent_name import normalize_name
        return normalize_name(name) or str(name).strip()
    raise UnknownAgent(str(name), sug)


def is_known(name: str) -> bool:
    from core.agent_name import canonical_agent
    return canonical_agent(name) in (meta().get("角色") or {})