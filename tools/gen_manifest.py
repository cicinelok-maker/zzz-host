"""生成 tools.json —— 机器可读的能力清单。

## 为什么（用户问「别人的 agent 接进去就能跑吗」）

一个外部 agent 要接入，需要知道：
1. 有哪些工具（不用读 7000 行文档）
2. 每个怎么调（命令 + 参数）
3. 输出是什么（文件路径 + 字段）
4. 需要什么前置（游戏开着？先跑 status？）
5. 退出码什么意思

现在什么都没有，所以「接进去就能跑」不成立。

## 做法

**扫描实际代码生成**，不是手写 —— 手写的会和代码脱节。
从这个脚本能跑出真实的东西：argparse 的定义、--json 有没有、
return 的数字、写的文件。
"""
from __future__ import annotations

import ast
import json
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"

# 手写的元信息（这些代码里看不出来，只能人写）
META = {
    "zzz_status.py": {
        "purpose": "读角色当前状态：6 个位号的主词条/副词条/有效值 + 等级 + 技能",
        "outputs": ["state/status_<agent>.json"],
        "requires": ["game_running"],
        "idempotent": True,
        "produces_for": ["zzz_plan", "zzz_daily", "farm_gap"],
    },
    "zzz_plan.py": {
        "purpose": "算 4+2 最优换装方案（主词条错的盘会被排除）",
        "outputs": ["state/plan.json"],
        "requires": ["game_running", "status_<agent>.json"],
        "idempotent": True,
    },
    "zzz_daily.py": {
        "purpose": "角色养成一轮：盘点→缺口→电量→刷本→养成→记账→汇报",
        "outputs": ["state/disc_progress.json"],
        "requires": ["game_running"],
        "idempotent": False,
        "destructive": True,
        "note": "会真的花电量和材料",
    },
    "zzz_disc_daily.py": {
        "purpose": "只管驱动盘的每日养成（带电量规划和趋势）",
        "outputs": ["state/disc_progress.json"],
        "requires": ["game_running"],
        "idempotent": False,
        "destructive": True,
    },
    "zzz_grind.py": {
        "purpose": "多轮收敛：一直跑到目标条数或资源耗尽",
        "outputs": ["state/disc_progress.json"],
        "requires": ["game_running"],
        "idempotent": False,
        "destructive": True,
    },
    "zzz_launch.py": {
        # 7 是 _map_enter 映射出来的（enter_game 超时 → 等进入游戏超时），
        # 正则扫不到字面量 return 7，所以显式声明。
        "exit_codes": [0, 1, 2, 3, 5, 6, 7],
        "purpose": "启动游戏 + 等窗口 + 点「进入游戏」到世界；已在运行时也会确认可操作",
        "outputs": [],
        "requires": ["game_exe"],
        "idempotent": True,
    },
    "zzz_equip.py": {
        "purpose": "给某个位号装指定的盘",
        "outputs": [],
        "requires": ["game_running"],
        "idempotent": True,
        "destructive": True,
    },
    "od_material_farm.py": {
        "purpose": "刷本（区域巡防/专业挑战室/实战模拟室）",
        "outputs": [],
        "requires": ["game_running", "one_dragon"],
        "idempotent": False,
        "destructive": True,
        "note": "消耗电量",
    },
    "zzz_disc_v2.py": {
        "purpose": "读仓库里所有盘（逐位号 + 滚动采集）",
        "outputs": ["od_test/discs_v2.json"],
        "requires": ["game_running"],
        "idempotent": True,
        "slow": "5-40 分钟",
    },
    # **三个真破坏性工具**（BUG-009）
    #
    # 它们原来走默认值 `destructive=False, idempotent=True`，
    # 而实际都会不可逆地改游戏数据（拆解 / 升级消耗 / 标记弃置）。
    # AGENTS.md 的 destructive 清单当时也漏了它们。
    "run_dismantle.py": {
        "desc": "拆解已弃置驱动盘（不可逆）。不加 --run 只统计数量",
        "destructive": True,
        "idempotent": False,
    },
    "zzz_disc_cycle.py": {
        "desc": "驱动盘一轮：升级 + 判定 + 标记弃置 + 拆解（-recycle 时不可逆）",
        "destructive": True,
        "idempotent": False,
    },
    "zzz_disc_train.py": {
        "desc": "驱动盘训练：真花材料升级（不可逆）",
        "destructive": True,
        "idempotent": False,
    },
    "check_config.py": {
        "purpose": "检查路径/OneDragon OCR/角色配置/飞书",
        "outputs": [],
        "requires": [],
        "idempotent": True,
    },
    "smoke_test.py": {
        "purpose": "全部工具的语法和导入自检",
        "outputs": [],
        "requires": [],
        "idempotent": True,
    },
}

# 输出文件的字段说明（从实际 JSON 读）
SCHEMA = {
    "state/status_<agent>.json": {
        "agent": "str 角色名",
        "main_set": "str 四件套",
        "total": "float 质量分（口径B：存在1+升级N）",
        "blue_total": "int 有效副词条个数（游戏标蓝的数量）",
        "slots": "[{slot:int, set:str, level:int, main:str, "
                 "eff:float, blue:int, main_verdict:good|weak|bad|unknown, "
                 "detail:[str]}]",
    },
    "state/plan.json": {
        "agent": "str",
        "main_set": "str",
        "sec_set": "str",
        "main_count": "int",
        "plan": "[{slot:int, from:str, to:str, eff:float, reason:str}]",
    },
    "state/disc_progress.json": {
        "_type": "list[记录]",
        "记录": "{ts:str, agent:str, 蓝条:int, 质量分:float, "
                "动作:[str], 位号:[{slot,set,eff,blue}]}",
    },
}

SKIP = {"audit_", "selftest_", "_", "gen_manifest", "cleanup_tools",
        "feishu", "feishu_img",
        "check_42", "check_main_sub", "check_target_28",
        "check_consistency", "check_main_formula"}


def scan_tool(p: pathlib.Path) -> dict | None:
    s = p.read_text(encoding="utf-8", errors="replace")
    name = p.stem

    # 从 docstring 拿第一行当说明
    first = ""
    m = re.match(r'"""(.*?)(?:\n|""")', s, re.S)
    if m:
        first = m.group(1).strip().split("。")[0][:80]

    # argparse 参数
    args = []
    for am in re.finditer(r'add_argument\(\s*"([^"]+)"', s):
        flag = am.group(1)
        if not flag.startswith("-"):
            args.append({"pos": flag})
        else:
            args.append({"flag": flag})

    # 有没有 --json
    has_json = '"--json"' in s or "'--json'" in s

    meta = META.get(p.name, {})

    # 退出码。
    # 默认靠正则扫 `return N`，但间接返回（比如 _map_enter(rc) 映射表里的 7）
    # 扫不出来。所以 META 可以显式覆盖。
    codes = meta.get("exit_codes")
    if not codes:
        codes = sorted({int(x) for x in re.findall(r"return (\d)\b", s)})
    return {
        "name": name,
        "cmd": f"python tools/{p.name}",
        "args": args,
        "json_output": has_json,
        "exit_codes": codes,
        "purpose": meta.get("purpose") or first,
        "outputs": meta.get("outputs", []),
        "requires": meta.get("requires", []),
        "idempotent": meta.get("idempotent", True),
        "destructive": meta.get("destructive", False),
        **({"note": meta["note"]} if meta.get("note") else {}),
        **({"slow": meta["slow"]} if meta.get("slow") else {}),
    }


tools = []
# 扫**发布集**，不是本地目录 ——
# 本地可能有 capture_fp_we.py 这种「有但不发布」的脚本，
# 扫本地会把它登记进 tools.json，别人机器上就悬空了（朋友报的第一个 bug）。
from publish_github import collect as _collect
_rel = {x.as_posix() for x in _collect(BASE)}
_names = sorted(pathlib.Path(x).name for x in _rel
                if x.startswith("tools/") and x.count("/") == 1
                and x.endswith(".py"))
for p in (T / n for n in _names):
    if any(p.stem.startswith(x) for x in SKIP):
        continue
    if p.stem in ("feishu", "feishu_img"):
        continue          # 本机可选，不进发布
    t = scan_tool(p)
    if t and t["purpose"]:
        tools.append(t)

manifest = {
    "schema_version": 1,
    "project": "zzz-host",
    "description": "绝区零角色养成托管：驱动盘判断 / 养成规划 / 电量分配",
    "prerequisites": {
        "one_dragon": {
            "required": True,
            "why": "OCR 和刷本",
            "check": "python tools/check_config.py",
        },
        "game_running": {
            "how": "python tools/zzz_launch.py",
        },
    },
    "quick_check": "python tools/check_config.py && python tools/smoke_test.py",
    "main_entry": {
        "tool": "zzz_daily",
        "cmd": "python tools/zzz_daily.py <agent> --run",
        "note": "产物会花电量和材料。先跑不带 --run 的看计划。",
    },
    "recommended_flow": [
        "python tools/check_config.py",
        "python tools/zzz_launch.py",
        "python tools/zzz_status.py <agent> --json",
        "python tools/zzz_disc_daily.py <agent>",
        "python tools/zzz_daily.py <agent> --run",
    ],
    "state_schema": SCHEMA,
    "exit_code_convention": {
        "0": "成功",
        "1": "一般失败",
        "2": "配置缺失或参数错误",
        "3": "选不中角色",
        "4": "到不了目标界面",
        "5": "等窗口/条件超时",
        "6": "需要人工登录",
        "7": "等进入游戏超时",
        "8": "读不到数据",
    },
    "tools": tools,
}

out = BASE / "tools.json"
out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
               encoding="utf-8")
print(f"已生成 tools.json")
print(f"  工具数：{len(tools)}")
print(f"  有 --json：{sum(1 for t in tools if t['json_output'])}")
print(f"  破坏性：{sum(1 for t in tools if t['destructive'])}")
print(f"  大小：{out.stat().st_size // 1024} KB")