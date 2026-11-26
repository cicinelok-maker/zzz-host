"""精简审计：找出能删的、重复的、冲突的。

## 用户要求（2026-11-25）

「看看还有没有什么东西能精简一下，顺便深度体检bug，
 顺便再看看有什么冲突和重复的地方，需要精简和稳定」

## 查什么

1. **死代码** —— 定义了但从没被调用的函数
2. **同职责工具** —— 两个工具干同一件事
3. **重复实现** —— 同一逻辑写在多个地方
4. **没被引用的文件** —— 独立脚本，没人依赖
5. **超大文件** —— 太长不易维护
"""
from __future__ import annotations

import ast
import pathlib
import re
from collections import defaultdict
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"

SKIP_PREFIX = ("audit_", "selftest_", "_")
files = [f for f in sorted(T.glob("*.py"))
         if not f.name.startswith(SKIP_PREFIX)]
core_files = [f for f in sorted((T / "core").glob("*.py"))]

ALL = {f.stem: f for f in files + core_files}
ALL_TEXT = {n: f.read_text(encoding="utf-8", errors="replace")
            for n, f in ALL.items()}

print("=" * 80)
print("① 死代码：定义了但从没被外部调用的函数")
print("=" * 80)
dead_total = 0
for name, text in ALL_TEXT.items():
    if name in ("__init__", "live", "input", "vision"):
        pass
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    funcs = [n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not funcs:
        continue
    dead = []
    for fn in funcs:
        if fn.startswith("_") and not fn.startswith("__"):
            # 私有函数只看本文件内有没有用
            if len(re.findall(rf"\b{fn}\(", text)) <= 1:
                dead.append(fn)
            continue
        if fn in ("main", "apply", "handler"):
            continue
        # 全局搜
        used = 0
        for other_name, other_text in ALL_TEXT.items():
            used += len(re.findall(rf"\b{fn}\b", other_text))
        if used <= 1:
            dead.append(fn)
    if dead:
        print(f"  {name}: {', '.join(dead[:6])}"
              + (f" …共 {len(dead)}" if len(dead) > 6 else ""))
        dead_total += len(dead)
print(f"\n  合计 {dead_total} 个疑似死函数")

print()
print("=" * 80)
print("② 同职责工具（可能重复）")
print("=" * 80)
GROUPS = {
    "读盘/读状态": ["zzz_status", "zzz_disc_v2", "zzz_disc_train"],
    "换装决策": ["zzz_plan", "zzz_equip"],
    "盘训练/回收": ["zzz_disc_train", "zzz_disc_cycle"],
    "总控/日常": ["zzz_daily", "zzz_disc_daily", "zzz_auto", "zzz_grind", "zzz_next"],
    "等级": ["zzz_level", "zzz_skill_target"],
    "成本": ["zzz_cost"],
    "刷本": ["zzz_farm_plan", "od_material_farm"],
    "技能/核心": ["zzz_skill", "zzz_core"],
    "资源": ["zzz_resource"],
    "工具": ["zzz_launch", "zzz_mcp"],
}
for role, names in GROUPS.items():
    exist = [n for n in names if n in ALL]
    if len(exist) > 1:
        sizes = {n: len(ALL_TEXT[n].splitlines()) for n in exist}
        print(f"  ⚠ {role}: {len(exist)} 个")
        for n, s in sizes.items():
            print(f"      {n:<20} {s:>4} 行")

print()
print("=" * 80)
print("③ 重复实现（同一逻辑在多处）")
print("=" * 80)
PATTERNS = {
    "读电量": r"read_charge|电量：",
    "go_to 装备页": r'go_to\("装备页"\)',
    "open_custom": r"open_custom\(",
    "读盘详情": r"read_disc\(",
    "判有效": r"is_effective|eff_of|evaluate\(",
    "子进程跑 OneDragon": r"one_dragon_python\(\)",
    "写 state 文件": r'state\" / ',
    "解析等级": r"parse_level|等级\\s\*\(\\d",
}
for label, pat in PATTERNS.items():
    hits = {n: len(re.findall(pat, t)) for n, t in ALL_TEXT.items()
            if re.search(pat, t)}
    if len(hits) > 1:
        total = sum(hits.values())
        print(f"  {label:<20} {len(hits)} 个文件 共 {total} 处")
        top = sorted(hits.items(), key=lambda x: -x[1])[:4]
        print(f"      {top}")

print()
print("=" * 80)
print("④ 超大文件（>400 行，维护困难）")
print("=" * 80)
big = sorted(((n, len(t.splitlines())) for n, t in ALL_TEXT.items()),
             key=lambda x: -x[1])
for n, s in big[:10]:
    flag = "⚠" if s > 400 else " "
    print(f"  {flag} {n:<24} {s:>5} 行")

print()
print("=" * 80)
print("⑤ 没人引用的文件（孤立脚本）")
print("=" * 80)
orphan = []
for name in ALL_TEXT:
    if name in ("__init__", "live"):
        continue
    refs = 0
    for other, text in ALL_TEXT.items():
        if other == name:
            continue
        if re.search(rf"\b{name}\b", text):
            refs += 1
    if refs == 0:
        orphan.append((name, len(ALL_TEXT[name].splitlines())))
for n, s in sorted(orphan, key=lambda x: -x[1]):
    print(f"  {n:<24} {s:>4} 行（没人 import/调用）")
print(f"\n  合计 {len(orphan)} 个孤立文件")