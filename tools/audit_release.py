"""检查「发布集里的每个文件，依赖都在发布集里」。

## 为什么需要这个

朋友的 agent 一装就报：
```
tools.json 登记了不存在的 capture_fp_we    ← gen_manifest 扫本地，不扫发布集
status.py 崩溃（import zzz_host）          ← status.py 发布了，依赖没发布
```

**我的 11 个 audit 工具一个都没抓到。** 因为它们全在本地跑 ——
本地有 `zzz_host.py`、有 `capture_fp_we.py`、有 `E:\\OneDragon\\...`，
**所以「在本地能跑」这件事本身没有信息量。**

这个工具做的事：**只看发布集**，不看本地独有文件。

```
python tools/audit_release.py
```

查五件事：
1. 发布集里每个 .py 的 import，是否都能在发布集或标准库/requirements 里找到
2. tools.json 里登记的工具，文件是否真在发布集里
3. 发布集里有没有硬编码的本机路径
4. 发布集里有没有引用「本地独有的脚本」
5. 关键文件是否齐全

**必须能在「只有发布集」的环境下跑通**，所以它自己也不能依赖本地独有文件。
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "tools"))

from publish_github import collect  # noqa: E402
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

# 第三方依赖（requirements.txt 里的 + 标准库不在这里）
THIRD_PARTY = {
    "numpy", "PIL", "cv2", "vgamepad", "lark_oapi",
    "one_dragon", "zzz_od",           # 来自 OneDragon（运行时注入 sys.path）
} | set(sys.stdlib_module_names)

# 项目内部的顶层包/模块（相对发布集）
INTERNAL_PREFIX = ("core", "tests")

problems = []


def add(kind: str, where: str, what: str) -> None:
    problems.append((kind, where, what))


files = collect(BASE)
rel_set = {f.as_posix() for f in files}
print(f"发布集：{len(files)} 个文件")
print()

# ============================================================ 1 import 解析
print("=" * 74)
print("① 发布集内的 import 是否都能解析")
print("=" * 74)

# 发布集里的模块名（不含路径）
module_names = set()
for rel in rel_set:
    if rel.endswith(".py"):
        name = Path(rel).name[:-3]
        module_names.add(name)
        # tools/core/xxx.py → core.xxx
        parts = Path(rel).with_suffix("").parts
        if "core" in parts:
            i = parts.index("core")
            module_names.add(".".join(parts[i:]))

bad_imports = []
for rel in sorted(rel_set):
    if not rel.endswith(".py"):
        continue
    p = BASE / rel
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        continue
    # 收集「在 try: 里且 except ImportError」的 import 节点 —— 那些是软引用，跳过
    soft = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            has_import_error = any(
                h.type is None or
                (isinstance(h.type, ast.Name) and h.type.id == "ImportError") or
                (isinstance(h.type, ast.Attribute) and
                 getattr(h.type.value, "id", "") == "ImportError")
                for h in node.handlers)
            if has_import_error:
                for sub in node.body:
                    for x in ast.walk(sub):
                        if isinstance(x, (ast.Import, ast.ImportFrom)):
                            soft.add(id(x))

    for node in ast.walk(tree):
        if id(node) in soft:
            continue
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:            # 相对导入，跳过
                continue
            if node.module:
                mods = [node.module.split(".")[0]]
        for m in mods:
            if m in THIRD_PARTY or m in INTERNAL_PREFIX:
                continue
            if m in module_names:
                continue
            # 发布集里没有这个模块
            bad_imports.append((rel, m))

if bad_imports:
    for rel, m in bad_imports[:20]:
        add("import 缺失", rel, m)
        print(f"  ⚠ {rel:<42} → {m}")
    if len(bad_imports) > 20:
        print(f"  …还有 {len(bad_imports) - 20} 处")
else:
    print("  ✔ 全部能解析")

# ============================================================ 2 tools.json 一致性
print()
print("=" * 74)
print("② tools.json 登记的工具，文件是否在发布集里")
print("=" * 74)

tj = BASE / "tools.json"
if tj.exists():
    d = json.loads(tj.read_text(encoding="utf-8"))
    tools = d.get("tools") or []
    missing = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        cmd = t.get("cmd") or ""
        m = re.search(r"tools/([\w_]+)\.py", cmd)
        if m:
            want = f"tools/{m.group(1)}.py"
            if want not in rel_set:
                missing.append((t.get("name"), want))
    if missing:
        for name, want in missing:
            add("tools.json 悬空", "tools.json", f"{name} → {want}")
            print(f"  ⚠ {name:<24} → {want}（不在发布集）")
    else:
        print(f"  ✔ {len(tools)} 个工具全部对得上")
else:
    print("  ✘ 没有 tools.json")
    add("缺文件", "tools.json", "不存在")

# ============================================================ 3 硬编码路径
print()
print("=" * 74)
print("③ 发布集里的硬编码本机路径")
print("=" * 74)

PAT = re.compile(r'(?:[A-Z]:\\\\?Users\\\\?\w+|[A-Z]:\\\\?OneDragon|'
                 r'[A-Z]:\\\\?miHoYo|E:\\\\deepseek)')
hits = []
for rel in sorted(rel_set):
    # .md 是文档，里面的路径是「你要填成什么」的示例，不算硬编码
    if not rel.endswith((".py", ".json", ".ps1")):
        continue
    p = BASE / rel
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    for i, line in enumerate(t.splitlines(), 1):
        if PAT.search(line):
            # 这些是「猜 OneDragon 装在哪」的列表，故意写常见路径
            GUESS_FILES = {
                "tools/core/paths.py",      # ONE_DRAGON_GUESSES
                "tools/zzz_launch.py",      # GAME_GUESSES
                "daily.ps1",                # PowerShell 里的同一份猜测
                "admin.ps1",                # 同上（提权脚本也要找 OneDragon）
                "paths.example.json",       # 填法示例
                "tools/audit_release.py",   # 本文件（docstring 里举了例子）
            }
            if rel in GUESS_FILES:
                continue
            hits.append((rel, i, line.strip()[:60]))

if hits:
    for rel, i, what in hits[:15]:
        add("硬编码路径", rel, f"L{i} {what}")
        print(f"  ⚠ {rel:<40} L{i}: {what}")
    if len(hits) > 15:
        print(f"  …还有 {len(hits) - 15} 处")
else:
    print("  ✔ 没有（paths.py 的猜测列表除外，那是故意的）")

# ============================================================ 4 关键文件
print()
print("=" * 74)
print("④ 关键文件是否齐全")
print("=" * 74)
KEY = ["README.md", "INSTALL.md", "AGENTS.md", "LICENSE", "requirements.txt",
       "tools.json", "paths.example.json", "daily.ps1",
       "tools/check_config.py", "tools/zzz_who.py", "tools/zzz_daily.py",
       "tools/disc_meta.json", "tools/run_tests.py",
       ".github/workflows/release.yml"]
miss = [k for k in KEY if k not in rel_set]
if miss:
    for k in miss:
        add("缺关键文件", k, "不在发布集")
        print(f"  ⚠ {k}")
else:
    print(f"  ✔ {len(KEY)} 个都在")

# ============================================================ 5 不该有的
print()
print("=" * 74)
print("⑤ 敏感文件是否被排除")
print("=" * 74)
MUST_NOT = ["paths.json", "feishu_conf.json", "roster.json", "status.py",
            "zzz_host.py", "graduate.py", "od_bridge.py",
            "tools/feishu.py", "tools/capture_fp_we.py"]
leak = [m for m in MUST_NOT if m in rel_set]
if leak:
    for m in leak:
        add("敏感文件泄漏", m, "不该在发布集")
        print(f"  ⚠ {m}")
else:
    print(f"  ✔ {len(MUST_NOT)} 个都被排除了")

# ============================================================ 汇总
print()
print("=" * 74)
if problems:
    print(f"✘ {len(problems)} 个问题")
    kinds = {}
    for k, _, _ in problems:
        kinds[k] = kinds.get(k, 0) + 1
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}")
    print()
    print("  这些都是「本地能跑但发布版跑不了」的问题 ——")
    print("  本地有那个文件/路径，所以测不出来。")
    sys.exit(1)
print("✔ 发布集自洽（所有依赖都在发布集内）")
print("=" * 74)
sys.exit(0)