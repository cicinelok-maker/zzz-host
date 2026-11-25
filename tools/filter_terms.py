"""驱动盘筛选面板的词条选项地图。

用户提醒：查完副词条数值表后，「词条筛选」也要跟着更新。

关键点：筛选面板里 **「攻击力」和「攻击力百分比」是两个独立选项**，
所以佩洛伊斯的有效词条必须勾「攻击力百分比」，不能勾「攻击力」。

实测面板（拆解页漏斗打开）：
    稀有度        S / A / B
    驱动盘状态    已弃置 / 已装备 / 已锁定 / 其他
    分区          分区[1] ~ 分区[6]
    主属性词条    点击展开 → 属性列表
    副词条词条    点击展开 → 属性列表（同一份）
    词条数量      2 / 3 / 4
    排除筛选      开关
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "state" / "filter_options.json"

# 副词条/主词条选项（第一次展开时 OCR 到的坐标，实际使用时通过 OCR 重新定位）
STAT_OPTIONS_HINT = [
    "生命值", "攻击力", "防御力",
    "攻击力百分比", "生命值百分比", "防御力百分比",
    "暴击率", "暴击伤害",
    "异常精通", "穿透率",
    "物理伤害加成", "火属性伤害加成", "电属性伤害加成",
    "以太伤害加成", "风属性伤害加成", "属性伤害加成",
    "异常掌控", "冲击力", "能量自动回复",
]

# 易混 OCR 别名 -> 标准名
ALIAS = {
    "勿理伤害加成": "物理伤害加成",
    "物里伤害加成": "物理伤害加成",
    "以太伤害加成": "以太伤害加成",
    "以太伤害": "以太伤害加成",
    "攻击力百分": "攻击力百分比",
    "攻击力百分比加成": "攻击力百分比",
}

# 角色有效词条 -> 筛选面板要勾的选项
def filter_terms(cfg: dict) -> tuple[list[str], list[str]]:
    """返回 (要勾的有效词条, 次选词条)，已按面板命名规范"""
    good = []
    for s in (cfg.get("有效副词条") or []):
        good.append(ALIAS.get(s, s))
    half = []
    for s in (cfg.get("次选副词条") or []):
        n = ALIAS.get(s, s)
        if n not in good:
            half.append(n)
    return good, half


def main() -> int:
    if not (BASE / "tools" / "disc_meta.json").exists():
        print("✘ 还没有「state/filter_options.json」——还没跑过，先跑：")
        print(f"     filter_terms.py 自己会生成（先跑一次本工具，或先跑换装流程）")
        raise SystemExit(2)
    meta = json.loads((BASE / "tools" / "disc_meta.json").read_text(encoding="utf-8"))
    chars = meta.get("角色") or {}
    out = {}

    for name, cfg in chars.items():
        good, half = filter_terms(cfg)
        # 面板里没有的选项要标出来
        missing = [s for s in good + half if s not in STAT_OPTIONS_HINT]
        out[name] = {
            "有效勾选": good,
            "次选勾选": half,
            "面板里没有的": missing,
            "四件套": cfg.get("四件套"),
            "两件套候选": cfg.get("两件套候选") or cfg.get("二件套候选") or [],
        }
        flag = f"  ⚠ 面板无 {missing}" if missing else ""
        print(f"{name}")
        print(f"  有效勾选：{' / '.join(good)}{flag}")
        print(f"  次选勾选：{' / '.join(half) or '（无）'}")

    OUT.write_text(json.dumps({
        "面板选项": STAT_OPTIONS_HINT,
        "别名": ALIAS,
        "角色": out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())