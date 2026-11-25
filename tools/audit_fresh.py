"""审计最近新增/改动的代码：是否遵守规矩、有没有新冲突和重复。

## 用户 2026-11-25

「你这一堆新增的东西，还有改的那些bug，有严格遵守你之前写的规矩吗，
而且这之间都有冲突和重复吗」

## 查什么

**A. 常量冲突**（同一个数在多个文件里各自定义）
**B. 重复实现**（同一逻辑多处）
**C. 规矩合规**（MAINTENANCE.md 里定的规则）
**D. 躺着的**（新代码里定义了但没用的）
"""
from __future__ import annotations

import ast
import pathlib
import re
from collections import defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"

NEW_FILES = [
    "core/jsonout.py", "core/tune_plan.py", "core/disc_initial.py",
    "core/disc_stoploss.py", "zzz_mcp.py", "gen_manifest.py",
    "audit_slim.py", "audit_wiring.py", "audit_agent_ready.py",
]

ALL = {}
for f in list(T.glob("*.py")) + list((T / "core").glob("*.py")):
    ALL[f.stem] = (f, f.read_text(encoding="utf-8", errors="replace"))

print("=" * 78)
print("A. 常量冲突：同一个概念在多处定义，值可能不一致")
print("=" * 78)

# 找所有「阈值/常量」定义
CONCEPTS = {
    "keep 线": r"KEEP_MIN|[\"']keep[\"']\s*:|\bkeep_line\s*=",
    "junk 线": r"[\"']junk[\"']\s*:",
    "调律门槛": r"TUNE_FLOOR",
    "升级节点": r"MILESTONES|_milestones|\b3, 6, 9, 12, 15\b|\(3, 6, 9|\[3, 6, 9",
    "母盘单价": r"MOTHER_PER_TUNE",
    "初始条数": r"INITIAL_SUBS|ROLLS_4SUB|ROLLS_3SUB",
    "定向分区坐标": r"\bRING\s*=",
    "电量上限": r"CHARGE_MAX|240",
    "区域巡防成本": r"COST_PATROL|FARM_COST",
}
for label, pat in CONCEPTS.items():
    hits = []
    for name, (f, text) in ALL.items():
        if re.search(pat, text):
            # 取实际值
            vals = re.findall(rf"({pat})\s*[=:]\s*([^\n#,;)]+)", text)
            hits.append((name, [v[1].strip()[:28] for v in vals][:3]))
    if len(hits) > 1:
        print(f"  ⚠ {label}: {len(hits)} 个文件")
        for n, v in hits:
            print(f"      {n:<22} {v}")

print()
print("=" * 78)
print("B. 重复实现：同一逻辑在多处")
print("=" * 78)
LOGICS = {
    "算有效值": r"def evaluate|def effective|eff \+= ",
    "升级节点枚举": r"3, 6, 9, 12, 15|for m in MILESTONES",
    "3条/4条判断": r"len\(.*subs.*\)\s*[<>=]=?\s*[34]|ROLLS_3SUB|ROLLS_4SUB",
    "取 keep 线": r"THRESHOLDS\[\"keep\"\]|KEEP_MIN",
}
for label, pat in LOGICS.items():
    hits = [n for n, (f, t) in ALL.items() if re.search(pat, t)]
    if len(hits) > 1:
        print(f"  ⚠ {label}: {hits}")

print()
print("=" * 78)
print("C. 新文件里的「躺着的」（定义了不用）")
print("=" * 78)
for rel in NEW_FILES:
    p = T / rel
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    dead = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.Assign)):
            if isinstance(node, ast.FunctionDef):
                name = node.name
                if name.startswith("_"):
                    continue
                uses = sum(len(re.findall(rf"\b{name}\b", t))
                           for n, (f, t) in ALL.items())
                if uses <= 1:
                    dead.append(name)
    if dead:
        print(f"  ⚠ {rel}: {dead}")

print()
print("=" * 78)
print("D. 规矩合规：MAINTENANCE.md 里的硬规则")
print("=" * 78)
mt = (BASE / "MAINTENANCE.md").read_text(encoding="utf-8")
# 提取所有「教训」标题
lessons = re.findall(r"^### 教训（第[^）]+）\s*$", mt, re.M)
print(f"  MAINTENANCE.md 里记了 {len(lessons)} 条教训")

# 检查几条可自动化的
CHECKS = []

# 规矩：常量不要写死在核心文件外
core_cfg = (T / "core" / "disc_cfg.py").read_text(encoding="utf-8")
hard = []
for name, (f, text) in ALL.items():
    if name in ("disc_cfg", "game_cfg", "disc_stoploss", "tune_plan",
                "disc_initial", "charge_plan", "audit_slim", "audit_wiring",
                "gen_manifest", "check_config", "smoke_test"):
        continue
    for m in re.finditer(r"^([A-Z][A-Z_]{3,})\s*=\s*(\d+)", text, re.M):
        hard.append((name, m.group(1), m.group(2)))
if hard:
    print(f"  ⚠ 模块级数字常量写死在 {len(set(h[0] for h in hard))} 个文件：")
    for n, k, v in hard[:8]:
        print(f"      {n}.{k} = {v}")

# 规矩：破坏性动作不能做 or 兜底
bad_or = []
for name, (f, text) in ALL.items():
    for m in re.finditer(r"(click|equip|upgrade|dismantle)[^\n]*\bor\b[^\n]*", text):
        bad_or.append((name, m.group(0).strip()[:60]))
if bad_or:
    print(f"  ⚠ or 兜底: {bad_or[:5]}")
else:
    print("  ✔ 没有 or 兜底")

# 规矩：导航类点击后要验证
nav = []
for name, (f, text) in ALL.items():
    for m in re.finditer(r"go_to\([^)]+\)\s*$", text, re.M):
        nav.append(name)
        break

print()
print("=" * 78)
print("E. 新文件是否在 MAINTENANCE.md 登记")
print("=" * 78)
for rel in NEW_FILES:
    stem = pathlib.Path(rel).stem
    if stem in ("__init__",):
        continue
    reg = f"`{stem}.py`" in mt or f"{stem}.py" in mt
    print(f"  {'✔' if reg else '✘'} {rel}")
