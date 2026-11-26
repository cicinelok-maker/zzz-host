"""自查：我有没有遵守 MAINTENANCE.md 自己的规矩。

规矩清单（MAINTENANCE.md「三、Canonical 工具清单」）：
1. 加功能先改现有 canonical 工具，不准新建复制品
2. 常量只准在 core/ 的中心文件定义
3. 算有效值只能调 core.disc_cfg.effective()
4. 改完必跑四项体检
5. 新文件必须同时更新本文档的清单
"""
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
_md_p = BASE / "MAINTENANCE.md"
if not _md_p.exists():
    # MAINTENANCE.md 是维护者文档，不随发布包发出去。
    # 干净副本里没有它是正常的 —— 跳过依赖它的规矩，不算失败。
    print("=" * 74)
    print("MAINTENANCE.md 不存在（发布集里没有它，这是正常的）")
    print("→ 跳过「规矩 5：新文件登记」")
    print("=" * 74)
    raise SystemExit(0)
md = _md_p.read_text(encoding="utf-8")

# 1) 清单里的工具
listed = set(re.findall(r"`([\w]+\.py)`", md))

# 2) 实际文件
actual = set()
for f in (BASE / "tools").glob("*.py"):
    actual.add(f.name)
for f in (BASE / "tools" / "core").glob("*.py"):
    actual.add(f.name)

# 3) 审计/自测/脚手架类，本来就不进 canonical 清单
SKIP = {
    "audit_all.py", "audit_disc.py", "audit_eff.py", "audit_coords.py",
    "audit_systems.py", "audit_conflict.py", "audit_stale_frame.py",
    "audit_patterns.py", "selftest_audit.py", "smoke_test.py",
    "check_consistency.py", "check_42.py", "check_main_sub.py",
    "check_main_formula.py", "check_target_28.py", "cleanup_tools.py",
    "gen_tools_doc.py", "__init__.py", "feishu_agent.py",
    "capture_fp_we.py",  # 一次性录指纹脚本
}

unlisted = sorted(actual - listed - SKIP)

print("=" * 70)
print("规矩 5：新文件有没有登记进 MAINTENANCE.md 的清单")
print("=" * 70)
print(f"  实际 {len(actual)} 个文件，清单里列了 {len(listed)} 个")
print(f"  审计/脚手架类跳过 {len(SKIP)} 个")
print()
if unlisted:
    print(f"  ⚠ 未登记 {len(unlisted)} 个：")
    for n in unlisted:
        p = BASE / "tools" / n
        if not p.exists():
            p = BASE / "tools" / "core" / n
        lines = len(p.read_text(encoding="utf-8", errors="replace").splitlines()) if p.exists() else 0
        print(f"      {n:<26} {lines:>4} 行")
else:
    print("  ✔ 全部已登记")

# 4) 查重复职责（规矩 1：不准新建复制品）
print()
print("=" * 70)
print("规矩 1：有没有重复职责的工具（新建复制品）")
print("=" * 70)
GROUPS = {
    "读盘": ["zzz_disc_v2.py", "zzz_disc_train.py"],
    "点击封装": ["core/click.py"],
    "套装名归一": ["core/zh.py"],
    "潜力评估": ["core/disc_potential.py"],
    "日常总控": ["zzz_daily.py", "zzz_disc_daily.py"],
}
for role, names in GROUPS.items():
    exist = [n for n in names if (BASE / "tools" / n).exists()
             or (BASE / "tools" / "core" / n.split("/")[-1]).exists()]
    if len(exist) > 1:
        print(f"  {role}：{len(exist)} 个 → {exist}")
print()

# 5) 查常量有没有写死在业务文件
print("=" * 70)
print("规矩 2：常量有没有写死在中心文件之外")
print("=" * 70)
CENTRAL = {"disc_cfg.py", "game_cfg.py", "disc_stats.py", "vocab.py", "slots.py", "zh.py"}
BAD = []
for f in sorted((BASE / "tools").glob("*.py")) + sorted((BASE / "tools" / "core").glob("*.py")):
    if f.name in CENTRAL or f.name.startswith(("audit_", "selftest_", "_")):
        continue
    s = f.read_text(encoding="utf-8", errors="replace")
    # 找重复定义的中心常量
    for name in ("KEEP_MIN", "JUNK_MAX", "FARM_COST", "CARD_BATTERY",
                 "CARDS_DEFAULT", "MAX_RATIO", "CHARGET_MAX"):
        if re.search(rf"^{name}\s*=\s*[\d.]", s, re.M):
            BAD.append((f.name, name))
if BAD:
    for n, c in BAD:
        print(f"  ⚠ {n}: {c} 写死了")
else:
    print("  ✔ 没发现写死的中心常量")

# **有问题就非 0**（BUG-043）：原来脚本结尾什么都不返回，恒 exit 0，
# 而 audit_ship 只认退出码 —— 这一项结构上不可能变红。
if BAD:
    print(f"\n✘ {len(BAD)} 处违反项目规矩")
    raise SystemExit(1)
