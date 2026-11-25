"""全量扫描：躺着的模块 + 断开的链路。

## 用户要求（2026-11-25）

「你全量扫描一下看有没有跟这个一样是躺着的和链路断开的吧」

参考案例：
1. **躺着的**：`disc_potential` 被 `zzz_disc_daily` 只 import 不用
2. **链路断开**：`zzz_tune` 没有任何工具调用，完全孤立

## 查四类问题

**A. import 了不用的符号**
```python
from core.disc_potential import potential_eff   # 但全文没调用 potential_eff
```

**B. 孤立工具**（没人调用它，它也不调别人）
每个工具应该要么被某处调用，要么是明确的入口。

**C. 数据断流**
- 写了 `state/X.json` 但没人读 → 白写
- 读了 `state/Y.json` 但没人写 → 永远读不到

**D. 判断不落地**
函数算出了结论（返回 dict/bool），但调用方没有基于它行动。
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
from collections import defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"

SKIP_PREFIX = ("audit_", "selftest_", "_")
FILES = [f for f in sorted(T.glob("*.py")) if not f.name.startswith(SKIP_PREFIX)]
CORE = [f for f in sorted((T / "core").glob("*.py"))]

TEXT = {}
for f in FILES + CORE:
    TEXT[f.stem] = f.read_text(encoding="utf-8", errors="replace")

CORE_NAMES = {f.stem for f in CORE}
TOOL_NAMES = {f.stem for f in FILES}

# 明确入口（不要求有调用者）
ENTRY = {"zzz_daily", "zzz_disc_daily", "zzz_grind", "zzz_mcp", "zzz_launch",
         "check_config", "smoke_test", "gen_manifest", "gen_tools_doc",
         "cleanup_tools", "selfcheck", "live", "pick_agent", "capture_fp_we"}

# ============================================================ A. 没用到的 import
print("=" * 78)
print("A. import 了但没用的符号（躺着的代码）")
print("=" * 78)
dead_imports = []
for name, text in TEXT.items():
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                sym = a.asname or a.name
                if sym == "*":
                    continue
                # __future__ 是编译指令，不算「用了」
                if (node.module or "") == "__future__":
                    continue
                # 全文出现次数（排除 import 行本身）
                uses = len(re.findall(rf"\b{re.escape(sym)}\b", text))
                # import 行本身算 1 次
                if uses <= 1:
                    dead_imports.append((name, sym, node.module or ""))
        elif isinstance(node, ast.Import):
            for a in node.names:
                sym = (a.asname or a.name).split(".")[0]
                uses = len(re.findall(rf"\b{re.escape(sym)}\b", text))
                if uses <= 1:
                    dead_imports.append((name, sym, a.name))

if dead_imports:
    by_file = defaultdict(list)
    for f, s, m in dead_imports:
        by_file[f].append(f"{s}（from {m}）" if m else s)
    for f, syms in sorted(by_file.items()):
        print(f"  ⚠ {f}: {', '.join(syms[:5])}")
        if len(syms) > 5:
            print(f"      …共 {len(syms)} 个")
    print(f"\n  合计 {len(dead_imports)} 个无用 import")
else:
    print("  ✔ 没有")

# ============================================================ B. 孤立工具
print()
print("=" * 78)
print("B. 孤立工具（没人调 + 不调别人 + 不是入口）")
print("=" * 78)
callers = defaultdict(set)     # 谁调我
calls = defaultdict(set)       # 我调谁

for name, text in TEXT.items():
    # 通过子进程调其他工具：run([... "xxx.py" ...]) 或 run("xxx.py", ...)
    for m in re.finditer(r'["\'](\w+)\.py["\']', text):
        target = m.group(1)
        if target in TOOL_NAMES and target != name:
            callers[target].add(name)
            calls[name].add(target)
    # 通过 import 调 core
    for m in re.finditer(r"from core\.(\w+) import|from core import (\w+)", text):
        target = m.group(1) or m.group(2)
        if target in CORE_NAMES:
            calls[name].add("core." + target)
            callers["core." + target].add(name)

orphans = []
for name in sorted(TOOL_NAMES):
    if name in ENTRY:
        continue
    if not callers.get(name):
        orphans.append(name)

if orphans:
    for n in orphans:
        out_n = len(calls.get(n, ()))
        lines = len(TEXT[n].splitlines())
        print(f"  ⚠ {n:<22} {lines:>4} 行　调用 {out_n} 个别人，但没人调它")
    print(f"\n  合计 {len(orphans)} 个孤立工具")
else:
    print("  ✔ 没有孤立工具")

# ============================================================ C. 数据断流
print()
print("=" * 78)
print("C. 数据断流（写的人有、读的人没有）")
print("=" * 78)

# 谁写 state/X.json
writers = defaultdict(set)
readers = defaultdict(set)
for name, text in TEXT.items():
    # 写：(BASE / "state" / "xxx.json")
    for m in re.finditer(r'state["\s/]+[",\s]*([\w\u4e00-\u9fa5_]+\.json)', text):
        key = m.group(1)
        if re.search(rf'(write_text|dump)', text):
            writers[key].add(name)
    # 更宽松：找所有 state/xxx.json 提及
    for m in re.finditer(r'f?["\']([\w\u4e00-\u9fa5_<>{}]+\.json)["\']', text):
        key = m.group(1)
        if any(k in text for k in ["state"]) and key not in ("package.json",):
            if "write_text" in text or "json.dump" in text:
                writers[key].add(name)
            if "read_text" in text or "json.load" in text:
                readers[key].add(name)

# 合并：只看 state 里的
STATE = BASE / "state"
if STATE.exists():
    actual = {p.name for p in STATE.glob("*.json")}
else:
    actual = set()

print("  state/ 里的文件：")
for fn in sorted(actual):
    # 精确点：谁真的读
    rd = [n for n, t in TEXT.items() if fn in t and ("read_text" in t or "json.load" in t)]
    wr = [n for n, t in TEXT.items() if fn in t and ("write_text" in t or "json.dump" in t)]
    if not rd and wr:
        print(f"    ⚠ {fn:<24} 只有写({wr[:2]})，没人读")
    elif rd and not wr:
        print(f"    · {fn:<24} 只有读({rd[:2]})，没人生成")
    elif rd and wr:
        print(f"    ✔ {fn:<24} 写={wr[:2]} 读={rd[:2]}")
    else:
        print(f"    ? {fn:<24} 没找到引用")

print()
print("  代码里提到但 state/ 里不存在的：")
for fn in sorted(set(readers) | set(writers)):
    if fn.endswith(".json") and fn not in actual and "<" not in fn and "{" not in fn:
        rd = [n for n, t in TEXT.items() if fn in t and ("read_text" in t or "json.load" in t)]
        if rd:
            print(f"    ⚠ {fn:<24} 被 {rd[:2]} 读，但文件不存在")

# ============================================================ D. 判断不落地
print()
print("=" * 78)
print("D. 判断不落地（算出结论但没人用）")
print("=" * 78)
# 找 core 里返回 dict 且带 "worth"/"verdict"/"should" 的函数
for name in sorted(CORE_NAMES):
    text = TEXT[name]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        fn = node.name
        uses = 0
        for other, t in TEXT.items():
            if f"{name}" not in t:
                continue
            uses += len(re.findall(rf"\b{fn}\b", t))
        # 排除定义处
        if uses <= 1:
            print(f"  ⚠ core.{name}.{fn}　没人调用")
