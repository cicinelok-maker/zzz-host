"""审计：哪些网格/列表界面需要滚动，哪些已经做了。

用户 2026-11-24：「顺便看看还有没有其他能用滚轮的地方，我记得网格状的都行」
"""
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"
C = T / "core"

# 游戏里会超出屏幕、需要滚动的界面
SCREENS = {
    "驱动仓库（混合所有位号）": "驱动仓库",
    "驱动盘定制页（单个位号）": "驱动盘定制",
    "驱动盘筛选·套装网格": "套装网格",
    "驱动盘拆解页": "驱动盘拆解",
    "音擎列表": "音擎详情",
    "音擎推荐面板": "音擎推荐",
    "音擎回收": "音擎回收",
    "代理人列表": "代理人列表",
    "调律·音轨设定": "音轨设定",
    "调律界面": "调律界面",
    "技能强化面板": "技能强化",
}

print("=" * 78)
print("哪些界面做了滚动")
print("=" * 78)

files = list(T.glob("*.py")) + list(C.glob("*.py"))
for label, anchor in SCREENS.items():
    users = []
    for f in files:
        s = f.read_text(encoding="utf-8", errors="replace")
        if anchor not in s:
            continue
        # 这个文件里有没有 wheel
        has_wheel = "wheel(" in s
        # 有 wheel 的地方是不是在这个 anchor 附近（同函数里）
        users.append((f.name, has_wheel))
    if not users:
        print(f"\n  {label:<26} 没有任何工具处理")
        continue
    with_scroll = [n for n, w in users if w]
    without = [n for n, w in users if not w]
    tag = "✔" if with_scroll else "⚠"
    print(f"\n  {tag} {label}")
    if with_scroll:
        print(f"       有滚动: {with_scroll}")
    if without:
        print(f"       无滚动: {without}")

print()
print("=" * 78)
print("所有 wheel( 调用点")
print("=" * 78)
for f in files:
    s = f.read_text(encoding="utf-8", errors="replace")
    hits = [(i + 1, l.strip()) for i, l in enumerate(s.splitlines())
            if "wheel(" in l and not l.strip().startswith("#")]
    if hits:
        print(f"\n  {f.name}")
        for ln, code in hits[:6]:
            print(f"    L{ln:<4} {code[:76]}")

print()
print("=" * 78)
print("判断：哪些'网格状'界面还缺滚动")
print("=" * 78)
MUST_SCROLL = [
    ("驱动仓库", "90+ 块盘，一屏放不下"),
    ("驱动盘定制", "单号位 9~16 块，滚动能多看"),
    ("套装网格", "18 个套装，一屏放不下"),
    ("驱动盘拆解页", "全部可拆解盘，远超一屏"),
    ("音擎列表", "角色有多把音擎"),
    ("音擎回收", "826 把可用，必滚"),
    ("代理人列表", "14+ 个角色"),
]
for name, why in MUST_SCROLL:
    found = []
    for f in files:
        s = f.read_text(encoding="utf-8", errors="replace")
        if name in s and "wheel(" in s:
            found.append(f.name)
    print(f"  {'✔' if found else '⚠'} {name:<14} {why}"
          + (f"　→ {found}" if found else "　→ **缺滚动**"))
