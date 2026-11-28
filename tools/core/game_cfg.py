"""跨系统的游戏常量：电量、卡片、刷本成本。**唯一权威来源**。

驱动盘专用的常量在 `core/disc_cfg.py`，这里放的是所有系统都要用的。

## 体检发现（2026-11-24）

`FARM_COST = 60` 在 4 个文件里各写一遍：
    zzz_daily.py / zzz_grind.py / zzz_resource.py
改一次要改四处，漏一处就出错。

## 实测数据

    电量上限            240（主菜单可见）
    区域巡防一次          60 电  ← 驱动盘主要来源
    实战模拟室（1 卡）     20 电  ← 技能芯片
    实战模拟室（2 卡）     40 电
    专业挑战室            40 电  ← 核心技高维数据
    怪物卡上限            5 张   ← 每张 +20 电消耗
    储蓄电量             单独池（会随时间补到主电量）

公式（来自 OneDragon 源码）：
    estimated_charge_power = card_num * 20

## 注意：电量只在主菜单可见

大世界读不到电量（返回 -1）。`zzz_resource.py` 会先导航到主菜单再读。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 电量
CHARGE_MAX = 240          # 上限
CHARGE_PER_CARD = 20      # 每张怪物卡折算的电量
MAX_CARDS = 5             # 一次最多带几张卡

# ---------------------------------------------------------------- 刷本成本（电）
COST_PATROL = 60          # 区域巡防（驱动盘）
COST_CHALLENGE = 40       # 专业挑战室（核心技）
COST_SIM = 20             # 实战模拟室 1 卡（技能芯片）

# 兼容旧名字
FARM_COST = COST_PATROL

# ---------------------------------------------------------------- 默认值
CARDS_DEFAULT = MAX_CARDS
def _default_agent() -> str:
    """没指定角色时用谁。

    ## 原来这里写死了一个角色名

    ```python
    DEFAULT_AGENT = "佩洛伊斯"
    ```

    而 **17 个工具**把它当参数的默认值 —— 包括 `zzz_equip upgrade`、
    `zzz_disc_daily`、`zzz_wengine` 这些**会花材料**的。

    对作者本人没问题，但**这份工具是给别人用的**：
    朋友不带参数跑 `python tools/zzz_equip.py upgrade`，
    它会去操作「佩洛伊斯」—— 一个他账号上根本没有的角色。

    ## 现在按这个顺序查

    1. 环境变量 `ZZZ_DEFAULT_AGENT`
    2. `state/config.json` 的 `default_agent`
    3. **空** —— 然后 `resolve_agent("")` 会明确报「没指定角色」，
       让用户知道该传什么，而不是默默去操作别人的角色
    """
    import os as _os
    v = (_os.environ.get("ZZZ_DEFAULT_AGENT") or "").strip()
    if v:
        return v
    try:
        import json as _j
        from pathlib import Path as _P
        p = _P(__file__).resolve().parent.parent.parent / "state" / "config.json"
        if p.exists():
            d = _j.loads(p.read_text(encoding="utf-8"))
            v = str(d.get("default_agent") or "").strip()
            if v:
                return v
    except Exception:
        pass
    return ""


DEFAULT_AGENT = _default_agent()

# ---------------------------------------------------------------- 电量恢复
CHARGE_REGEN_SECONDS = 360        # 6 分钟回 1 点
CHARGE_REGEN_PER = 1


# ---------------------------------------------------------------- 材料转化
# 用户 2026-11-24 指出：强化材料可以双向转化
#   低级 → 高级（合成）
#   高级 → 低级（分解）
# 所以刷本只需刷**最高级**副本，缺什么用转化补。

CONVERT_STRATEGY = {
    "原则": "刷本只刷最高级，缺什么用转化补",
    "技能芯片": "实战模拟室·代理人技能，5 卡满（每卡 8 个芯片）",
    "音擎蓄电池": "区域巡防最高级",
    "核心技高维": "专业挑战室最高级",
    "注意": "转化必须在刷本之后跑，否则素材还没到手",
}

# 转化在流程里的正确位置
CONVERT_AFTER_FARM = True


# ---------------------------------------------------------------- 4+2 刷本策略
# 用户 2026-11-24 指出：
#   「4+2 不是固定盘位的，你可以两个副本一起刷，哪个盘子好用哪个，
#     但是 4 的那个套装主效果还是要凑的，别让 2 的变成 4 了」
#
# 所以：主套的副本 + 副套的副本都要刷，产出哪边好就用哪边。
# 但最终必须保证「主套恰好 4 件」——副套不能凑到 4 件（那样主套的 4 件套就没了）。

FARM_BOTH_DUNGEONS = True

SET_SLOT_RULES = {
    "主套": 4,    # 必须恰好 4 件，多一件少一件都不行
    "副套": 2,    # 恰好 2 件；超过 2 件会挤掉主套的位号
    "校验": "主套 4 件 + 副套 2 件 = 6 格，缺一不可；"
            "如果主套只有 3 件，优先补主套而不是堆副套",
}


# ---------------------------------------------------------------- 角色属性
# 用来判断主词条里的「属性伤害加成」对不对。
# 5 号位出「火属性伤害加成」时，以太角色拿到等于没有主词条。
AGENT_ELEMENT = {
    "11号": "火",
    "丽娜": "电",
    "佩洛伊斯": "以太",
    "凯撒": "物理",
    "可琳": "物理",
    "妮可": "以太",
    "安比": "电",
    "本": "火",
    "朱鸢": "以太",
    "柳": "电",
    "格莉丝": "电",
    "派派": "物理",
    "潘引壶": "物理",
    "猫又": "物理",
    "珂蕾妲": "火",
    "真斗": "火",
    "简": "物理",
    "维琳娜": "风",
    "苍角": "冰",
    "莱卡恩": "冰",
    "莱特": "火",
    "蕾米埃尔": "特殊",
    "雅": "冰",
}


# 伤害属性会变的角色：「属性流变」使伤害跟随队伍
# 对这类角色，5 号位任何属性伤害都算「能用但不确定」
ANY_ELEMENT_AGENTS = {"蕾米埃尔"}


def element_of(agent: str) -> str:
    """角色的属性伤害类型。查不到返回空串（不做属性判定）。

    ## 查找顺序（2026-11-28 修正）

    1. **`characters.local.json`** —— 用户自己的角色，不改发布集
    2. **`disc_meta.json` 的 `属性` 字段** —— **64 个角色全都有**
    3. `AGENT_ELEMENT` —— 只有 23 个的手工表，**只当兜底**

    ## 为什么要把 disc_meta 提到前面来

    原来只有 1 和 3 —— 于是**只有 23 个角色能拿到属性**，另外 41 个
    （露西 / 青衣 / 席德 / 扳机 / 雨果 …）一律返回空串。

    属性为空会静默地毁掉三件事：

    · `core/farm_gap.py`：芯片任务名算不出来 -> `--mission` 空 ->
      实战模拟室 exit 2，**一个都刷不了**
    · `zzz_plan`：主词条「属性伤害加成」判不了对错 -> 可能留着错的主词条
    · `zzz_status`：同上，盘点评分失真

    而 `disc_meta.json` 的 `属性` **64/64 都有**，而且比手工表**更准**：

        蕾米埃尔   AGENT_ELEMENT="特殊"   disc_meta="流明"   （流明是真实属性）
        雅         AGENT_ELEMENT="冰"     disc_meta="烈霜"   （烈霜是冰的变体）

    所以手工表不只是「不全」，它还有两条是**错的** —— 现在被 disc_meta 盖住。

    注：`AGENT_ELEMENT` 留着是为了「角色库还没收录、但手工表里有」的极端情况，
    不再承担主力。
    """
    # 1) 本地覆盖层优先（用户自己的角色，不改发布集）
    try:
        from core import characters as _chars
        _loc = _chars.get(str(agent))
        if _loc.get("属性"):
            return _loc["属性"]
    except Exception:
        pass

    # 2) **disc_meta 的「属性」字段**（64/64 都有，且更准）
    #
    # 懒加载：`agent_cfg` 在函数里 import `game_cfg`，这里反过来 import
    # `agent_cfg` 会不会循环？—— 都在函数体内，import 时才解析，没问题。
    try:
        from core.agent_cfg import meta as _meta
        from core.agent_name import canonical_agent as _canon
        _c = (_meta().get("角色") or {}).get(_canon(str(agent))) or {}
        e = _c.get("属性") or _c.get("元素") or ""
        if e:
            return e
    except Exception:
        pass

    # 3) 手工表兜底
    return AGENT_ELEMENT.get(agent, "")