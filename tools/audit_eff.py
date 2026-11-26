"""逐行审计所有「算有效值」的代码，确认口径统一。"""
import pathlib
import re
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

BASE = pathlib.Path(__file__).resolve().parent.parent
files = sorted((BASE / "tools").glob("*.py")) + sorted((BASE / "tools" / "core").glob("*.py"))

print("所有涉及 eff 累加的行：")
print("-" * 76)
by_file = {}
for f in files:
    s = f.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(s.splitlines(), 1):
        if re.search(r"eff\s*\+=", line) or "sum(" in line and "eff" in line:
            by_file.setdefault(f.name, []).append((i, line.strip()))

ok, bad = 0, 0
for name, rows in sorted(by_file.items()):
    print(f"\n{name}")
    for i, line in rows:
        # 判定是否带 1 +
        good = bool(re.search(r"\b1\s*\+", line)) or "+= 0" in line
        mark = "✔" if good else "✘"
        if good:
            ok += 1
        else:
            bad += 1
        print(f"  {mark} {i:>4}: {line[:88]}")

print()
print("-" * 76)
print(f"带 1+ 的：{ok} 处　不带的：{bad} 处")
if bad:
    print("\n需要人工确认的（可能不是有效值计算，也可能是漏改）：")
    for name, rows in sorted(by_file.items()):
        for i, line in rows:
            if not (re.search(r"\b1\s*\+", line) or "+= 0" in line):
                print(f"  {name}:{i}  {line[:88]}")