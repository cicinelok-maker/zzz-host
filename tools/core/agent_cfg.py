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
    """读 `tools/disc_meta.json`。

    ## **读不了 ≠ 没有配置**（E3）

    原来是：

    ```python
    try:
        _cache = json.loads(META.read_text(...))
    except Exception:
        _cache = {"角色": {}, "职业模板": {}}      # 静默变空
    ```

    空 dict 的后果是连锁的：

    · `role_of("丽娜")` -> 找不到 -> 回落 `DEFAULT_ROLE = "强攻"`
    · `cfg_of("丽娜")`  -> 用「强攻」模板补 -> 提示「**这个角色没配置**」

    而真实情况是**数据文件坏了**（手工改错 / 合并冲突留了 `<<<<<<<` /
    编辑器保存中断）。用户看到「这个角色没配置」会去 disc_meta 里
    加那个角色 —— **方向完全错了**，然后越改越乱。

    现在：读不了就**当场说清楚并 exit 2**（配置缺失），
    不要伪装成「角色级」的问题。
    """
    global _cache
    if _cache is None:
        if not META.exists():
            print("=" * 62)
            print(f"✘ 找不到角色配置：{META}")
            print("=" * 62)
            print("  这是工具的核心数据（角色套装 / 词条要求 / 职业模板）。")
            print("  缺了它，任何角色都会被当成「没配置」—— 那不是真的。")
            print("  恢复：git checkout tools/disc_meta.json")
            print("=" * 62)
            raise SystemExit(2)
        try:
            _cache = json.loads(META.read_text(encoding="utf-8"))
        except Exception as e:
            print("=" * 62)
            print(f"✘ {META.name} **读不了**：{type(e).__name__}")
            print(f"  {e}")
            print("=" * 62)
            print("  这不是「某个角色没配置」，是整个数据文件坏了。")
            print("  常见原因：手工改错 / 合并冲突留了 <<<<<<< / 编辑器保存中断")
            print(f"  文件：{META}")
            print("  恢复：git checkout tools/disc_meta.json")
            print("=" * 62)
            raise SystemExit(2) from None
        if not isinstance(_cache, dict):
            print(f"✘ {META.name} 的内容是 {type(_cache).__name__}，不是对象 —— 数据文件坏了")
            print(f"  恢复：git checkout tools/disc_meta.json")
            raise SystemExit(2)
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
    # **本地覆盖层优先** —— 用户自己的角色补充（state/characters.local.json）。
    # 不改发布集文件，pull 不会冲突。逐字段覆盖，不是整条替换。
    try:
        from core import characters as _chars
        _local = _chars.get(canon) or _chars.get(name) or {}
        if _local:
            own.update(_local)
    except Exception:
        pass
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


def _local_names() -> set[str]:
    """`state/characters.local.json` 里的角色名（F6）。

    `--add-agent` 写的是这个文件，而 `known()` 原来**只看 `disc_meta.json`** ——
    于是「加进去了但工具不认」，加完等于白加。

    读不了就当空集（本地层是可选增强，不该把整个工具弄挂）。
    """
    try:
        from core import characters as _chars
        return set(_chars.names())
    except Exception:
        return set()


def known() -> list[str]:
    """所有**认得**的角色名：`disc_meta.json` + 本地补充层。"""
    base = set((meta().get("角色") or {}).keys())
    return sorted(base | _local_names())


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

    def __str__(self) -> str:
        # **`KeyError` 的 `__str__` 是 `repr(args[0])`**（E17）——
        # 于是 `print(e)` 会多包一层引号，而且把 `\n` 打成**字面量**
        # `\n` 两个字符。实测输出：
        #
        #     '角色「（没指定角色）\n  用法：python tools/<工具>.py <角色名>\n ...」
        #
        # 报错信息本来就是给人读的，不该走 repr。
        return str(self.args[0]) if self.args else ""


class AgentNotSpecified(UnknownAgent):
    """**没指定角色** —— 不是「这个名字不在库里」（E17）。

    原来这两种情况共用 `UnknownAgent`，而「没指定」时把整段帮助文本
    当成**角色名**塞进了 `角色「{name}」不在角色库里`：

        角色「（没指定角色）
          用法：python tools/<工具>.py <角色名>
          或者设一次默认值，之后就不用每次写：
            set ZZZ_DEFAULT_AGENT=你的角色名
          可用角色：python tools/zzz_who.py --menu」不在角色库里。可用角色见 ...

    一句话被拆成「角色名」和「后缀」两半，中间还插了句「不在角色库里」——
    读起来就是乱码。

    单独立一个异常：消息自己就是完整的帮助，不再二次包装。
    """

    def __init__(self):
        self.agent = ""
        self.suggestions = []
        KeyError.__init__(
            self,
            "没指定角色。\n"
            "  用法：python tools/<工具>.py <角色名>\n"
            "  或者设一次默认值，之后就不用每次写：\n"
            "    set ZZZ_DEFAULT_AGENT=你的角色名\n"
            "  可用角色：python tools/zzz_who.py --menu")


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
    # **单字输入不能走编辑距离**（D23 / E20）。
    #
    # `_edit_distance('2', '本') == 1` —— **任何**一个汉字/字符和**任何**
    # 一个单字名字的距离都是 1。实测：
    #
    #     suggest('2')  -> ['本', '柳', '照']      ← 纯垃圾
    #     suggest('?')  -> ['本', '柳', '照']
    #
    # 垃圾候选有两个后果（就是 D23 和 E20 说的那两头）：
    #
    # · **D23**：某个残字恰好只剩 **1** 个候选时，`resolve_agent` 会
    #   直接把它当成那个角色 —— **认错人**，而且不报错
    # · **E20**：真正该命中的（`'露'` ⊂ `'露西'`）被 3 个垃圾挤出了 `limit`
    #
    # 现在：单字只认「**包含**」关系（残字是名字的一部分），不算编辑距离。
    # 这是唯一对单字有意义的判据。
    _single = len(n) == 1
    scored = []
    for k in known():
        kn = normalize_name(k)
        contains = (n in kn) or (kn in n)
        if _single:
            if not contains:
                continue          # 单字且不包含 -> 不是候选，别拿距离凑
            scored.append((0, k))
            continue
        d = _edit_distance(n, kn)
        # 也考虑「包含」关系（输「洛伊斯」应该能想到「佩洛伊斯」）
        if contains:
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
        # **空名字要说清是「没指定」，不是「这个名字不在库里」**。
        # 原来报 `角色「」不在角色库里` —— 用户看到空引号完全不知道该怎么办。
        #
        # 现在「未指定」是一个正常会发生的场景：
        # `DEFAULT_AGENT` 默认是空（见 `core/game_cfg._default_agent`），
        # 目的是不让工具默默去操作作者自己的角色。
        raise AgentNotSpecified()
    canon = canonical_agent(name)
    chars = meta().get("角色") or {}
    if canon in chars:
        return canon
    # **本地层加的角色也要认**（F6）
    if canon in _local_names():
        return canon
    # 归一化后还不在 → 模糊找
    sug = suggest(name)
    # **单字不自动纠正，只提示**（D23）。
    #
    # `suggest('露')` 现在能正确给出 `['露西']` —— 但那是**建议**，
    # 不是「用户说的是露西」。把单字静默换成某个角色，
    # 万一用户真想说的是别的（或者 OCR 把某个名字读成了这一个字），
    # 就变成**认错人**，而且不报错。
    #
    # 实测的坏例子：OCR 把「11号」读成 `'2'`，以前
    # `suggest('2')` 给 `['本','柳','照']` —— 三个候选所以没自动纠正；
    # 要是那天恰好只剩一个候选，就会被悄悄换成别人。
    #
    # 现在：单字一律走「报错 + 给建议」那条路，让用户确认。
    if len(sug) == 1 and len(str(name).strip()) >= 2:
        return sug[0]          # 只有一个候选，且够长，直接用
    if allow_unknown:
        # 显式允许未知角色：返回归一化名，让调用方自己警告
        from core.agent_name import normalize_name
        return normalize_name(name) or str(name).strip()
    raise UnknownAgent(str(name), sug)


def is_known(name: str) -> bool:
    """这个角色有没有配装知识（发布集库 或 本地覆盖层，任一有就算）。"""
    from core.agent_name import canonical_agent
    canon = canonical_agent(name)
    if canon in (meta().get("角色") or {}):
        return True
    # 本地覆盖层里也算「认识」—— 用户自己补的角色
    try:
        from core import characters as _chars
        return _chars.has(canon) or _chars.has(name)
    except Exception:
        return False