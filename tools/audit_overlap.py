"""查新增模块和已有的有没有职责重叠/冲突。

用户 2026-11-24：「你新增这么多东西有冲突和重复吗」
"""
import pathlib
import re
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"
C = T / "core"

NEW = ["click.py", "zh.py", "disc_potential.py", "disc_color.py",
       "zzz_disc_daily.py", "audit_stale_frame.py", "audit_patterns.py",
       "selftest_audit.py", "audit_self.py"]


def funcs(p):
    s = p.read_text(encoding="utf-8", errors="replace")
    fs = set(re.findall(r"^def (\w+)", s, re.M)) | set(re.findall(r"^    def (\w+)", s, re.M))
    # 通用入口名不算冲突（每个 CLI 工具都有 main，多个工具有 run helper）
    return fs - {"main", "run", "__init__"}


print("=" * 76)
print("① 新增模块定义了哪些函数，有没有和老的撞名")
print("=" * 76)
all_files = {f.name: f for f in list(T.glob("*.py")) + list(C.glob("*.py"))}
new_funcs = {}
for n in NEW:
    p = C / n if (C / n).exists() else T / n
    if p.exists():
        new_funcs[n] = funcs(p)

for n, fs in new_funcs.items():
    dup = []
    for other, p in all_files.items():
        if other == n:
            continue
        common = fs & funcs(p)
        if common:
            dup.append((other, sorted(common)))
    tag = "⚠" if dup else "✔"
    print(f"\n{tag} {n}　{len(fs)} 个函数")
    if dup:
        for o, c in dup:
            print(f"    和 {o} 撞名: {c}")
    else:
        print(f"    {', '.join(sorted(fs)[:8])}{'...' if len(fs) > 8 else ''}")

print()
print("=" * 76)
print("② 概念重叠检查（不同名字、同一件事）")
print("=" * 76)
CONCEPTS = {
    "点击后验证": ["click_verify", "click_until", "click_first", "wait_for",
                 "click_text", "click_if", "goto_verify"],
    "判断是否有效词条": ["is_effective", "effective(", "count_effective",
                   "classify_color", "WEIGHT", "hit_ratio"],
    "算潜力": ["potential", "remain_rolls", "expected_gain"],
    "套装名处理": ["canonical_set", "normalize", "set_name", "same_set"],
}
for concept, keys in CONCEPTS.items():
    found = {}
    for name, p in all_files.items():
        s = p.read_text(encoding="utf-8", errors="replace")
        hits = [k for k in keys if k in s]
        if hits:
            found[name] = hits
    if len(found) > 1:
        print(f"\n  {concept}：{len(found)} 个文件涉及")
        for n, h in sorted(found.items()):
            print(f"    {n:<26} {h}")

print()
print("=" * 76)
print("③ 新模块有没有被真正使用（没人用的就是死代码）")
print("=" * 76)
for n in NEW:
    mod = n[:-3]
    users = []
    for name, p in all_files.items():
        if name == n:
            continue
        s = p.read_text(encoding="utf-8", errors="replace")
        if re.search(rf"\b{mod}\b", s):
            users.append(name)
    tag = "✔" if users else "⚠ 无人使用"
    print(f"  {tag:<12} {n:<24} 被 {len(users)} 处引用"
          + (f"：{users[:4]}" if users else ""))