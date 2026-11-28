"""实战模拟室 / 专业挑战室 / 恶名狩猎 的**子任务名**（来自 OneDragon 的 compendium）。

## 数据来源

`<OneDragon>/assets/game_data/compendium_data.yml`
（OneDragon 用来生成副本选择界面的**权威清单**，不是猜的）

## 为什么需要它

`od_material_farm` 的 `ChargePlanItem` 是：

    category_name     实战模拟室 / 专业挑战室 / 恶名狩猎
    mission_type_name 代理人技能 / 代理人晋升 / 音擎改装 / 基础材料
    mission_name      **具体的子任务名**（这里这张表）

而 `od_material_farm` 对这三类**强制要求** `--mission`：

    _NEED_MISSION = {"实战模拟室", "专业挑战室", "恶名狩猎"}
    if _miss and not args.mission:  -> exit 2

`farm_cmd` 原来**从来不传** `--mission` —— 于是**所有**实战模拟室的
刷本调用都会 exit 2，一个都刷不了。

## 我之前还判错过一次

审计 E23 说「OneDragon 用 `升温测试`/`电流测试`/`共鸣测试`」，
我当时只 grep 了 `*.py` 就说「本版没有这三个名字」—— **判错了**。
它们就在 `compendium_data.yml` 里。

所以芯片的任务名是**元素测试名**（`电流测试` 而不是 `电击测试`），
不是「角色名」。`od_material_farm` 那句「--mission 要传角色名」也是错的。
"""
from __future__ import annotations

#: 代理人技能：元素 -> 测试任务名
CHIP_TEST = {
    "物理": "刚性测试",
    "火": "升温测试",
    "冰": "冰结测试",
    "电": "电流测试",
    "风": "风切测试",
    "以太": "共鸣测试",
    "流明": "琢光测试",
    # 变体属性归到同族
    "烈霜": "冰结测试",
    "玄墨": "共鸣测试",
    "凛刃": "刚性测试",
}

#: 代理人晋升：职业 -> 演练任务名（规律：{职业}演练）
ASCEND_DRILL = {
    "锋御": "锋御演练",
    "命破": "命破演练",
    "强攻": "强攻演练",
    "击破": "击破演练",
    "异常": "异常演练",
    "支援": "支援演练",
    "防护": "防护演练",
}

#: 音擎改装：职业 -> 试验任务名（**中间词不统一**，只能列表）
WENGINE_TEST = {
    "锋御": "锋御耦合试验",
    "命破": "命破共鸣试验",
    "强攻": "强攻极片试验",
    "击破": "击破振膜试验",
    "异常": "异常磁体试验",
    "支援": "支援分频试验",
    "防护": "防护音圈试验",
}

#: 基础材料：材料 -> 专项任务名
BASE_MATERIAL = {
    "角色经验": "调查专项",
    "音擎经验": "音擎专项",
    "丁尼": "赏金专项",
    "驱动盘经验": "镀剂专项",
    # 材料名直接命中
    "调查员记录": "调查专项",
    "资深调查员记录": "调查专项",
    "音擎组件": "音擎专项",
    "镀剂": "镀剂专项",
}


def mission_for(training: str, role: str = "", attr: str = "",
                material: str = "") -> str:
    """给一个训练类型 + 角色信息，返回 `--mission` 该传什么。

    拿不准就返回空串 —— **空着会被 `od_material_farm` 明确拒绝**，
    比传一个错的名字去刷错本好。
    """
    t = (training or "").strip()
    r = (role or "").strip().split("/")[0]
    a = (attr or "").strip()

    if t == "代理人技能":
        return CHIP_TEST.get(a, "")
    if t == "代理人晋升":
        return ASCEND_DRILL.get(r, "")
    if t == "音擎改装":
        return WENGINE_TEST.get(r, "")
    if t == "基础材料":
        if material in BASE_MATERIAL:
            return BASE_MATERIAL[material]
        for k, v in BASE_MATERIAL.items():
            if k and k in (material or ""):
                return v
        return ""
    return ""
