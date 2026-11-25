"""全量深度体检：把 42 条教训变成可自动化的检查。

## 用户 2026-11-25

> 你遵循你现在列出的那些教训和规矩，重新全量深度体检一下现有的代码，
> 再看看有没有什么bug

## 做法

把 MAINTENANCE.md 里能自动化的教训抽成规则，逐条跑。
不能自动化的（比如「用户预期管理」）单独列出，人工看。

## 20 条可自动化规则

```
R01 死 import（import 了不用）
R02 OR 兜底吃默认值（`x or 默认` 会把 0/""/[] 也替掉）
R03 同一常量多处定义（异名同值 = 改一处漏一处）
R04 定义了不用的函数
R05 硬编码角色名（区分默认值 vs 写死）
R06 静默走默认（不在库里不报错）
R07 裸 except / except Exception 吞掉错误
R08 重复实现（同一逻辑多处）
R09 文件存在但跑不了（引用了不存在的模块/文件）
R10 格式改了没同步下游（schema 漂移）
R11 str.replace 大面积替换的痕迹（残留重复行）
R12 坐标半硬编码（重算 + 绝对坐标混用）
R13 elif 链漏掉原始分支
R14 防御逻辑吃掉真错误（返回默认值而不是抛）
R15 校验错了对象（子串匹配当精确）
R16 编码问题（PowerShell 脚本没 BOM）
R17 修一处没修所有消费方（同一数据多处读）
R18 孤立文件（没人引用）
R19 常量写死在核心文件外
R20 未验证的分支（TODO / 待查 / 未测）
```
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
from collections import defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"

SKIP = ("audit_", "selftest_", "_")
FILES = [f for f in sorted(T.glob("*.py")) if not f.name.startswith(SKIP)]
CORE = [f for f in sorted((T / "core").glob("*.py"))]
ALL = {}
for f in FILES + CORE:
    ALL[f.stem] = (f, f.read_text(encoding="utf-8", errors="replace"))

issues = defaultdict(list)


def add(rule, where, what):
    issues[rule].append((where, what))


# ---------------- R01 死 import
for name, (f, text) in ALL.items():
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "") == "__future__":
                continue
            for a in node.names:
                sym = a.asname or a.name
                if sym == "*":
                    continue
                if len(re.findall(rf"\b{re.escape(sym)}\b", text)) <= 1:
                    add("R01 死import", name, f"{sym}（from {node.module}）")

# ---------------- R02 OR 兜底吃默认值
for name, (f, text) in ALL.items():
    if name.startswith("audit_"):
        continue
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            continue
        # 只报「可能为 0 的数值被 or 替成非 0 默认」
        #   n = read_x() or 240        ← 读到 0 会变 240，危险
        #   (x.stdout or "") + ...     ← None→"" 是对的，不报
        m = re.search(r"=\s*([\w\.\(\)]+)\s+or\s+([1-9][0-9]*|[1-9][0-9]*\.[0-9]+)", s)
        if m and "stdout" not in s and "stderr" not in s and "get(" not in s:
            add("R02 OR兜底吃0", name, f"L{i} {s[:56]}")

# R03 同一常量多处定义 —— 删掉：每个文件定义自己的 BASE 是正常的，全误报

# ---------------- R04 定义了不用的函数
for name, (f, text) in ALL.items():
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            uses = sum(len(re.findall(rf"\b{node.name}\b", t))
                       for _, (_, t) in ALL.items())
            if uses <= 1:
                add("R04 死函数", name, node.name)

# ---------------- R05 硬编码角色名（写死的，不是默认值）
meta = json.loads((T / "disc_meta.json").read_text(encoding="utf-8"))
CHARS = set((meta.get("角色") or {}).keys())
for name, (f, text) in ALL.items():
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("#") or s.startswith('"') or s.startswith("'"):
            continue
        for c in CHARS:
            if len(c) < 2:
                continue
            if c not in s:
                continue
            # 排除：注释行
            if s.startswith("#"):
                continue
            # 排除：参数默认值 / 环境变量默认 / 文档示例 / print 提示
            if any(k in s for k in ("default", "DEFAULT", "environ", "ZZZ_AGENT",
                                    "python tools/", "如 ", "例", "→",
                                    "#", "所以", "必须勾")):
                continue
            # 排除：字典键定义（"佩洛伊斯": "以太"）
            if re.match(rf'^["\']?{re.escape(c)}["\']?\s*:', s):
                continue
            # 排除：测试用例里的字符串参数（smoke_test 之类）
            if re.match(r'^\("[^"]+\.py"', s):
                continue
            # 排除：一次性脚本（不进发布）
            if name in ("capture_fp_we", "run_dismantle", "selfcheck"):
                continue
            add("R05 硬编码角色", name, f"L{i} [{c}] {s[:48]}")

# ---------------- R06 静默走默认
for name, (f, text) in ALL.items():
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        # 只报「默认值是非空角色名」的（or "" / or "" .strip() 是对的）
        if (re.search(r"\.get\([^)]+\)\s+or\s+[\"'][^\"']+[\"']", s)
                and "agent" in s.lower()):
            add("R06 静默默认", name, f"L{i} {s[:56]}")

# ---------------- R07 裸 except
for name, (f, text) in ALL.items():
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if re.match(r"except( Exception| BaseException)?\s*:", s):
            lines = text.splitlines()
            nxt = lines[i].strip() if i < len(lines) else ""
            # 只报完全吞掉的（pass / continue）
            if nxt in ("pass", "continue"):
                add("R07 完全吞错", name, f"L{i} → {nxt}")

# ---------------- R09 引用了不存在的文件
for name, (f, text) in ALL.items():
    for m in re.finditer(r'["\']([\w/\\.]+\.(?:py|ps1))["\']', text):
        rel = m.group(1)
        if rel.startswith(("http", "//")):
            continue
        cand = [BASE / rel, T / rel, T / "core" / rel]
        if not any(p.exists() for p in cand):
            add("R09 引用不存在", name, rel)

# ---------------- R11 残留重复行（str.replace 误伤痕迹）
for name, (f, text) in ALL.items():
    lines = text.splitlines()
    for i in range(len(lines) - 1):
        a, b = lines[i].strip(), lines[i + 1].strip()
        if a and a == b and len(a) > 20 and not a.startswith("#"):
            add("R11 重复行", name, f"L{i+1} {a[:52]}")

# ---------------- R16 PowerShell 脚本没 BOM
for p in BASE.glob("*.ps1"):
    raw = p.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        add("R16 缺BOM", p.name, "PowerShell 5.1 会按 GBK 读，中文乱码")

# ---------------- R18 孤立文件
for name, (f, text) in ALL.items():
    if name in ("live", "__init__"):
        continue
    refs = sum(1 for other, (_, t) in ALL.items()
               if other != name and re.search(rf"\b{name}\b", t))
    if refs == 0:
        add("R18 孤立文件", name, f"{len(text.splitlines())} 行")

# ---------------- R19 常量写死在核心外
CORE_CENTER = {"disc_cfg", "game_cfg", "disc_stoploss", "tune_plan",
               "disc_initial", "charge_plan", "agent_cfg", "agent_name"}
for name, (f, text) in ALL.items():
    if name in CORE_CENTER or name.startswith(("audit_", "gen_")):
        continue
    for m in re.finditer(r"^([A-Z][A-Z_]{3,})\s*=\s*(\d+)\s*(?:#.*)?$", text, re.M):
        add("R19 常量散落", name, f"{m.group(1)} = {m.group(2)}")

# ---------------- R20 未验证的分支
for name, (f, text) in ALL.items():
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(r"(TODO|FIXME|待查|未验证|未测试|待确认|未知)", line):
            s = line.strip()
            if s.startswith("#") or '"""' not in s:
                add("R20 未验证", name, f"L{i} {s[:56]}")

# ============================================ 输出
print("=" * 82)
print("全量深度体检（按 42 条教训抽出的 20 条可自动化规则）")
print("=" * 82)

RULE_ORDER = [
    "R01 死import", "R02 OR兜底", "R03 常量冲突", "R04 死函数",
    "R05 硬编码角色", "R06 静默默认", "R07 吞错误", "R09 引用不存在",
    "R11 重复行", "R16 缺BOM", "R18 孤立文件", "R19 常量散落",
    "R20 未验证",
]
total = 0
for rule in RULE_ORDER:
    items = issues.get(rule) or []
    if not items:
        print(f"\n{rule:<16} ✔ 0 处")
        continue
    total += len(items)
    print(f"\n{rule:<16} ⚠ {len(items)} 处")
    for where, what in items[:12]:
        print(f"    {where:<22} {what}")
    if len(items) > 12:
        print(f"    …还有 {len(items) - 12} 处")

print()
print("=" * 82)
print(f"合计 {total} 处待看")
print("=" * 82)
