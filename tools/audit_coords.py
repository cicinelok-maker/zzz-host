"""审计坐标/阈值在多处重复定义的情况（冲突源）。"""
import pathlib
import re
from collections import defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
files = sorted((BASE / "tools").glob("*.py")) + sorted((BASE / "tools" / "core").glob("*.py"))

# 1) 区域常量
REGIONS = defaultdict(list)
for f in files:
    s = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"^(\w*R_[A-Z_]+)\s*=\s*\(([^)]+)\)", s, re.M):
        REGIONS[m.group(1)].append((f.name, m.group(2).strip()))

print("=" * 74)
print("一、同名区域常量在不同文件里的值")
print("=" * 74)
conflict = 0
for name, rows in sorted(REGIONS.items()):
    vals = {v for _, v in rows}
    if len(rows) > 1:
        flag = "  ⚠ 值不一致" if len(vals) > 1 else ""
        if len(vals) > 1:
            conflict += 1
        print(f"\n{name}{flag}")
        for fn, v in rows:
            print(f"    {fn:<28} {v}")
print(f"\n→ 同名但值不一致的常量：{conflict} 个")

# 2) 阈值常量
print()
print("=" * 74)
print("二、阈值常量")
print("=" * 74)
THRESH = defaultdict(list)
for f in files:
    s = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"^([A-Z][A-Z_]{2,})\s*=\s*([\d.]+)", s, re.M):
        THRESH[m.group(1)].append((f.name, m.group(2)))
for name, rows in sorted(THRESH.items()):
    if len(rows) > 1:
        vals = {v for _, v in rows}
        flag = "  ⚠ 不一致" if len(vals) > 1 else ""
        print(f"\n{name}{flag}")
        for fn, v in rows:
            print(f"    {fn:<28} {v}")

# 3) 硬编码坐标（直接写死的 xy=）
print()
print("=" * 74)
print("三、直接写死的关键坐标（应按用途归类）")
print("=" * 74)
DUPES = defaultdict(list)
for f in files:
    s = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"\((\d{3,4}),\s*(\d{2,4})\)", s):
        xy = f"({m.group(1)},{m.group(2)})"
        if f.name not in DUPES[xy]:
            DUPES[xy].append(f.name)
hot = [(k, v) for k, v in DUPES.items() if len(v) >= 3]
hot.sort(key=lambda x: -len(x[1]))
for xy, names in hot[:12]:
    print(f"  {xy:<12} 出现在 {len(names)} 个文件：{', '.join(names[:5])}")
