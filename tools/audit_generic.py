"""审计：整套闭环对「换角色」的泛化程度。

用户 2026-11-25：「你这一整个闭环是基于佩洛伊斯这个角色开发的吗，
假如我换一个角色呢」

要查的硬编码：
1. 角色名写死在代码里（而不是从参数/配置读）
2. 套装名写死（每个角色的四件套不同）
3. 主词条/副词条写死
4. 属性写死（以太）
"""
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"
C = T / "core"

AGENT = "佩洛伊斯"
# 已知套装名（写死套装名 = 换角色就错）
SETS = ["拂晓行纪", "啄木鸟电音", "折枝剑歌", "河豚电音", "谶羽之誓",
        "荆棘玫瑰", "獠牙重金属", "呼啸沙龙", "自由蓝调", "激素朋克",
        "静听嘉音", "雷暴重金属", "震星迪斯科", "摇摆爵士", "极地重金属",
        "混沌爵士", "混沌重金属", "云岿如我", "原始朋克"]

print("=" * 78)
print("① 角色名硬编码")
print("=" * 78)
for f in sorted(T.glob("*.py")) + sorted(C.glob("*.py")):
    if f.name.startswith(("audit_", "selftest_", "_")):
        continue
    s = f.read_text(encoding="utf-8", errors="replace")
    hits = [(i + 1, l.strip()) for i, l in enumerate(s.splitlines())
            if AGENT in l and not l.strip().startswith(("#", '"""', "'"))]
    # 去掉 print/注释性的字符串（示例命令）
    hits = [(n, c) for n, c in hits
            if not (c.startswith(("print(", "out.append(")) and "→" in c)]
    if hits:
        print(f"\n  {f.name}  {len(hits)} 处")
        for ln, code in hits[:4]:
            # 合理的默认值写法：参数默认 / env 默认 / 单次调试脚本
            is_default = any(k in code for k in (
                "default", "DEFAULT", "environ.get(", "add_argument"))
            if "docstring" in code.lower() or code.strip().startswith(('"""', "#")):
                is_default = True
            tag = "（默认值，可改）" if is_default else "（硬编码！）"
            print(f"    L{ln:<4} {code[:66]} {tag}")

print()
print("=" * 78)
print("② 套装名硬编码")
print("=" * 78)
for f in sorted(T.glob("*.py")) + sorted(C.glob("*.py")):
    if f.name.startswith(("audit_", "selftest_", "_")):
        continue
    s = f.read_text(encoding="utf-8", errors="replace")
    found = {}
    for st in SETS:
        n = s.count(st)
        if n:
            found[st] = n
    if found:
        print(f"  {f.name:<26} {found}")

print()
print("=" * 78)
print("③ 属性硬编码（以太）")
print("=" * 78)
for f in sorted(T.glob("*.py")) + sorted(C.glob("*.py")):
    if f.name.startswith(("audit_", "selftest_", "_")):
        continue
    s = f.read_text(encoding="utf-8", errors="replace")
    if "以太" in s:
        hits = [l.strip() for l in s.splitlines()
                if "以太" in l and not l.strip().startswith("#")]
        print(f"  {f.name:<26} {len(hits)} 处  {hits[:2]}")

print()
print("=" * 78)
print("④ disc_meta.json 里有哪些角色")
print("=" * 78)
import json
meta = json.loads((T / "disc_meta.json").read_text(encoding="utf-8"))
roles = meta.get("角色") or {}
print(f"  共 {len(roles)} 个角色配置")
for name, cfg in roles.items():
    has_main = bool(cfg.get("主词条"))
    has_sub = bool(cfg.get("有效副词条"))
    has_set = bool(cfg.get("四件套"))
    print(f"    {name:<10} 四件套={has_set} 主词条={has_main} 有效副词={has_sub}")
