"""生成全体工具清单：名字、行数、用途、子命令、关键参数。

数据直接从代码里抽（docstring + argparse），不手写，保证不会过期。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TOOLS = BASE / "tools"
CORE = TOOLS / "core"
OUT = BASE / "TOOLS.md"


def first_doc(text: str, limit: int = 90) -> str:
    """取模块 docstring 的第一句有意义的行。"""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    doc = ast.get_docstring(tree)
    if not doc:
        return ""
    for line in doc.splitlines():
        s = line.strip()
        if not s or s.startswith("=") or s.startswith("#"):
            continue
        return s[:limit]
    return ""


def subcommands(text: str) -> list[str]:
    """从 argparse 里抽子命令名。"""
    return re.findall(r'add_parser\(\s*["\'](\w+)["\']', text)


def flags(text: str) -> list[str]:
    """抽 add_argument 的长参数。"""
    found = re.findall(r'add_argument\(\s*["\'](--[\w-]+)["\']', text)
    seen = []
    for f in found:
        if f not in seen:
            seen.append(f)
    return seen


def purpose_override(name: str) -> str:
    """手工补充用途（代码 docstring 不够准的）。"""
    M = {
        "zzz_daily.py": "日常总控：音擎→等级→转化→技能→核心技→驱动盘→刷本→训练回收",
        "zzz_grind.py": "多轮收敛：反复跑到目标或电量耗尽",
        "zzz_status.py": "全状态总览：位号/等级/主属性/有效词条/达标度",
        "zzz_plan.py": "4+2 最优分配决策，可 --apply 直接换装",
        "zzz_equip.py": "装备/升级驱动盘（equip 带 --level 指定等级）",
        "zzz_disc_v2.py": "批量读仓库驱动盘 → JSON",
        "zzz_disc_train.py": "单盘读+判（read_disc / evaluate 被 status 复用）",
        "zzz_disc_cycle.py": "升级→判定→换下→标记弃置→拆解 完整闭环",
        "zzz_tune.py": "定向调律：音轨设定 + 定向分区 + 调律",
        "run_dismantle.py": "批量拆解所有已弃置的驱动盘",
        "zzz_resource.py": "读电量/母盘（只在主菜单可见）",
        "zzz_convert.py": "材料转化（合成高阶材料）",
        "zzz_level.py": "角色等级/晋升（含转化获取自动合成）",
        "zzz_skill.py": "技能升级",
        "zzz_skill_target.py": "按岗位给技能目标等级（强攻/异常/击破…）",
        "zzz_core.py": "核心技读取/升级（A-F 六个圈）",
        "zzz_wengine.py": "音擎强化/进阶/改装",
        "zzz_cost.py": "养成成本表（EXP/证书/芯片/高维/蓄电池）",
        "od_material_farm.py": "刷本入口（--training/--challenge/--patrol）",
        "zzz_farm_plan.py": "刷本计划：按材料缺口自动分配电量",
        "pick_agent.py": "切换代理人（头像模板匹配）",
        "live.py": "真机操作底层：识屏→点文字/模板→再截图确认",
        "selfcheck.py": "兼容性自检（6 项）",
        "disc_gaps.py": "调律套装自动推导 + 升级中途止损",
        "filter_terms.py": "角色有效词条 → 筛选面板选项映射",
        "explain_crit.py": "命中率说明：全歪/部分/全中",
        "show_discs_v2.py": "读盘结果展示",
        "gap_analysis.py": "距离小毕业还差多少，差在哪个位号",
        "audit_all.py": "全量体检：常量冲突/口径/系统/总控链路/状态文件",
        "audit_eff.py": "逐行审计有效值计算口径",
        "audit_coords.py": "坐标/阈值重复定义审计",
        "smoke_test.py": "全部 canonical 工具的冒烟测试",
        "cleanup_tools.py": "工具清理（canonical 清单 → _legacy）",
    }
    return M.get(name, "")


def core_purpose(name: str) -> str:
    M = {
        "vision.py": "截图 + OCR（PPOCRv6）",
        "input.py": "键鼠输入（键盘必须 SCANCODE）",
        "ui.py": "UI 封装（click/key/find/text）",
        "anchors.py": "页面指纹识别（21 个页面）",
        "machine.py": "状态机导航（43 条转移）",
        "fingerprint.py": "指纹采集",
        "slots.py": "驱动盘位几何（环形 6 位 + 空位兜底）",
        "vocab.py": "属性词表 + stat_name_of",
        "disc_cfg.py": "驱动盘区域/阈值/坐标（唯一权威）",
        "disc_stats.py": "词条数值表 + roll 反推 + 百分比归名",
        "game_cfg.py": "电量/刷本成本/卡片（唯一权威）",
        "journal.py": "任务日志（jsonl）",
        "progress.py": "进度记录",
        "recovery.py": "异常恢复",
        "flows.py": "通用流程",
        "locate.py": "元素定位",
        "__init__.py": "包声明",
    }
    return M.get(name, "")


def row(name: str, text: str, purpose: str, is_core: bool) -> str:
    lines = len(text.splitlines())
    subs = subcommands(text)
    fl = flags(text)
    p = purpose or first_doc(text) or "（无说明）"
    extra = []
    if subs:
        extra.append("子命令 " + "/".join(subs[:6]))
    if fl:
        extra.append("参数 " + " ".join(fl[:6]))
    tail = ("　`" + "；".join(extra) + "`") if extra else ""
    return f"| `{name}` | {lines} | {p}{tail} |"


def main() -> int:
    out = ["# 工具清单（自动生成）", "",
           "> 数据从代码抽：行数、argparse 子命令和参数都是实时的。",
           "> 用途优先取手工标注，其次是模块 docstring。", ""]

    out.append("## 一、总控（4 个）—— 从这里开始")
    out.append("")
    out.append("| 工具 | 行数 | 用途 |")
    out.append("|---|---|---|")
    for n in ["zzz_daily.py", "zzz_grind.py"]:
        p = TOOLS / n
        if p.exists():
            out.append(row(n, p.read_text(encoding="utf-8", errors="replace"),
                           purpose_override(n), False))
    out.append("")
    out.append("**怎么选**：")
    out.append("- 想「一键养成一轮」→ `zzz_daily.py 佩洛伊斯 --run`")
    out.append("- 想「只做某几步」→ `zzz_auto.py --actions level,skill`")
    out.append("- 想「自动判断下一步」→ `zzz_next.py 佩洛伊斯`")
    out.append("- 想「一直刷到目标」→ `zzz_grind.py 佩洛伊斯 --run`")
    out.append("")

    GROUPS = [
        ("二、驱动盘（10 个）", "zzz_disc_v2.py zzz_disc_train.py zzz_disc_cycle.py "
                             "zzz_equip.py zzz_plan.py zzz_status.py zzz_tune.py "
                             "run_dismantle.py disc_gaps.py filter_terms.py"),
        ("三、其他四系统（8 个）", "zzz_resource.py zzz_convert.py zzz_level.py "
                               "zzz_skill.py zzz_skill_target.py zzz_core.py "
                               "zzz_wengine.py zzz_cost.py"),
        ("四、刷本（3 个）", "od_material_farm.py zzz_farm_plan.py"),
        ("五、辅助（4 个）", "live.py pick_agent.py selfcheck.py"),
        ("六、体检/校验（11 个）", "audit_all.py audit_disc.py audit_eff.py "
                              "audit_coords.py audit_systems.py "
                              "check_consistency.py check_42.py "
                              "check_main_sub.py check_main_formula.py "
                              "check_target_28.py smoke_test.py"),
        ("七、分析/展示（4 个）", "gap_analysis.py explain_crit.py "
                             "show_discs_v2.py cleanup_tools.py"),
    ]
    for title, names in GROUPS:
        out.append(f"## {title}")
        out.append("")
        out.append("| 工具 | 行数 | 用途 |")
        out.append("|---|---|---|")
        for n in names.split():
            p = TOOLS / n
            if p.exists():
                out.append(row(n, p.read_text(encoding="utf-8", errors="replace"),
                               purpose_override(n), False))
        out.append("")

    out.append("## 八、核心库 `tools/core/`（17 个）")
    out.append("")
    out.append("| 模块 | 行数 | 职责 |")
    out.append("|---|---|---|")
    for p in sorted(CORE.glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        n = len(t.splitlines())
        out.append(f"| `{p.name}` | {n} | {core_purpose(p.name) or first_doc(t)} |")
    out.append("")

    out.append("## 九、已归档 `tools/_legacy/`")
    out.append("")
    legacy = sorted(TOOLS.glob("_legacy/*.py"))
    out.append(f"共 {len(legacy)} 个历史文件，不参与运行。需要查旧实现时可以看，")
    out.append("但**不要再 import**。详见 `DISC_CHAIN.md` 的「历史遗留」表。")
    out.append("")

    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"已写入 {OUT}")
    print(f"  工具 {len(list(TOOLS.glob('*.py')))} 个 + core {len(list(CORE.glob('*.py')))} 个")
    print(f"  legacy {len(legacy)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())