"""全工具冲突分析：功能重叠、重复实现、默认值不一致、跨工具调用同一操作。

与 audit_all.py 的区别：
    audit_all  查常量/口径层面
    这个查「功能层面」—— 同一件事有几个工具能做，参数默认值一致吗
"""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TOOLS = BASE / "tools"

# ---- 功能类别 → 关键词（在 docstring / 参数名里出现就算沾边）
OPS = {
    "读状态": ["status", "read", "check"],
    "刷本": ["farm", "patrol", "training", "challenge", "hunt", "刷本"],
    "装备": ["equip", "装", "换装"],
    "升级": ["upgrade", "up", "强化", "升级"],
    "拆解/回收": ["dismantle", "recycle", "回收", "拆解", "弃置"],
    "调律": ["tune", "调律", "forge"],
    "读盘": ["disc", "盘"],
    "转化": ["convert", "转化"],
    "总控": ["orchestrat", "总控", "daily", "grind", "next", "auto"],
    "体检": ["audit", "check", "smoke"],
}

print("=" * 78)
print("一、可能的功能重叠（多个工具都能做同一件事）")
print("=" * 78)

files = {p.name: p for p in TOOLS.glob("*.py")}
info = {}
for name, p in files.items():
    t = p.read_text(encoding="utf-8", errors="replace")
    try:
        doc = ast.get_docstring(ast.parse(t)) or ""
    except SyntaxError:
        doc = ""
    subs = re.findall(r'add_parser\(\s*["\'](\w+)["\']', t)
    flags = re.findall(r'add_argument\(\s*["\'](--[\w-]+)["\']', t)
    info[name] = {"doc": doc[:200], "subs": subs, "flags": flags,
                  "lines": len(t.splitlines())}

for op, kws in OPS.items():
    hits = []
    for name, d in info.items():
        blob = (d["doc"] + " " + " ".join(d["subs"]) + " " + " ".join(d["flags"])).lower()
        if any(k.lower() in blob for k in kws):
            hits.append(name)
    if len(hits) >= 3:
        print(f"\n{op}：{len(hits)} 个工具沾边")
        for h in sorted(hits):
            print(f"    {h:<26} {info[h]['lines']:>4} 行  "
                  f"子命令={info[h]['subs'][:3]}")

print()
print("=" * 78)
print("二、同一参数在不同工具的默认值")
print("=" * 78)
DEFAULTS = defaultdict(list)
for name, p in files.items():
    t = p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'add_argument\(\s*["\'](--[\w-]+)["\'][^)]*?default\s*=\s*([^,)\n]+)', t):
        DEFAULTS[m.group(1)].append((name, m.group(2).strip()))
for flag, rows in sorted(DEFAULTS.items()):
    vals = {v for _, v in rows}
    if len(rows) > 1 and len(vals) > 1:
        print(f"\n{flag}  ⚠ {len(vals)} 种默认值")
        for n, v in rows:
            print(f"    {n:<26} {v}")

print()
print("=" * 78)
print("三、总控之间是否重复实现同一步骤")
print("=" * 78)
ORCH = ["zzz_daily.py", "zzz_auto.py", "zzz_next.py", "zzz_grind.py"]
for o in ORCH:
    p = TOOLS / o
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8", errors="replace")
    called = sorted({m for m in re.findall(r"[\"']([a-z_]+\.py)[\"']", t)
                     if (TOOLS / m).exists() and m != o})
    print(f"\n{o} → {len(called)} 个工具")
    print(f"    {', '.join(called) if called else '（没直接调）'}")

# 互相覆盖的步骤
print()
print("步骤覆盖矩阵（谁做了哪步）：")
STEPS = {
    "音擎": ["zzz_wengine.py"],
    "等级": ["zzz_level.py"],
    "转化": ["zzz_convert.py"],
    "技能": ["zzz_skill.py"],
    "核心技": ["zzz_core.py"],
    "盘决策": ["zzz_plan.py"],
    "盘训练回收": ["zzz_disc_cycle.py"],
    "刷本": ["od_material_farm.py", "zzz_farm_plan.py", "od_farm.py"],
    "状态": ["zzz_status.py"],
    "资源": ["zzz_resource.py"],
}
hdr = "步骤".ljust(12) + "".join(o.replace("zzz_", "").replace(".py", "").ljust(9)
                              for o in ORCH)
print(hdr)
for step, tools in STEPS.items():
    row = step.ljust(12)
    for o in ORCH:
        p = TOOLS / o
        t = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        row += ("✓".ljust(9) if any(x in t for x in tools) else "·".ljust(9))
    print(row)
