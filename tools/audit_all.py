"""整个大闭环的体检：跨系统冲突、重复、口径、死代码、链路缺口。

覆盖五个系统：
    电量/资源 · 刷本 · 角色（等级/技能/核心技） · 音擎 · 驱动盘
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TOOLS = BASE / "tools"
CORE = TOOLS / "core"
files = sorted(TOOLS.glob("*.py")) + sorted(CORE.glob("*.py"))


def read(f: Path) -> str:
    return f.read_text(encoding="utf-8", errors="replace")


print("=" * 78)
print("一、工具总量与分布")
print("=" * 78)
top = [f for f in TOOLS.glob("*.py")]
core = [f for f in CORE.glob("*.py")]
print(f"  tools/*.py      {len(top)} 个")
print(f"  tools/core/*.py {len(core)} 个")
print(f"  合计            {len(top) + len(core)} 个")
total_lines = sum(len(read(f).splitlines()) for f in files)
print(f"  总行数          {total_lines}")

# ---------------------------------------------------------------- 常量冲突
print()
print("=" * 78)
print("二、同名常量值冲突（跨系统）")
print("=" * 78)
CONST_RE = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*(.+?)$", re.M)
consts = defaultdict(list)
for f in files:
    for m in CONST_RE.finditer(read(f)):
        name = m.group(1)
        val = re.split(r"\s+#", m.group(2).strip())[0]
        if name in ("PY", "OUT", "HERE", "BASE", "ENV_EXTRA", "UID"):
            continue
        consts[name].append((f.name, val))

conflicts = []
for name, rows in sorted(consts.items()):
    vals = {v for _, v in rows}
    # 指向同一个来源的（__import__ / _TH[...] / COST_xxx）不算冲突
    indirect = all(('__import__' in v) or v.startswith('_TH') or
                   v.startswith('COST_') or v.startswith('MAX_') or
                   not v[0].isdigit() for _, v in rows)
    if len(rows) > 1 and len(vals) > 1 and not indirect:
        conflicts.append((name, rows))
for name, rows in conflicts:
    print(f"\n{name}  ⚠ {len({v for _, v in rows})} 种值")
    for fn, v in rows[:6]:
        print(f"    {fn:<26} {v[:50]}")
print(f"\n→ 冲突常量 {len(conflicts)} 个")

# ---------------------------------------------------------------- 口径
print()
print("=" * 78)
print("三、口径一致性（有效词条 = 存在1 + 升级N）")
print("=" * 78)
# 注意：up_eff / up_on_eff 是「命中次数」指标，故意只数升级，不算违规
# 所以要用 \b 排除前缀，只匹配真正的 eff +=
BAD = [
    (r"(?<![_a-zA-Z])eff \+= r\s*$", "eff += r"),
    (r"(?<![_a-zA-Z])eff \+= u\s*$", "eff += u"),
    (r"(?<![_a-zA-Z])eff \+= r \* 0\.5\s*$", "eff += r*0.5"),
    (r"(?<![_a-zA-Z])eff \+= u \* 0\.5\s*$", "eff += u*0.5"),
    (r"return max\(1, int", "rolls 返回最少1"),
]
bad = defaultdict(list)
for f in files:
    s = read(f)
    for pat, desc in BAD:
        if re.search(pat, s, re.M):
            bad[f.name].append(desc)
if bad:
    for k, v in bad.items():
        print(f"  ✗ {k}: {v}")
else:
    print("  ✔ 全部统一")

# ---------------------------------------------------------------- 阈值
print()
print("=" * 78)
print("四、关键阈值汇总")
print("=" * 78)
KEYS = ["BATTERY", "CHARGE", "FARM_COST", "CARD_BATTERY", "CARDS_DEFAULT",
        "KEEP_MIN", "JUNK_MAX", "MAX_RATIO", "THRESHOLD", "KEEP_THRESHOLD"]
for k in KEYS:
    rows = consts.get(k, [])
    if rows:
        vals = {v for _, v in rows}
        flag = " ⚠" if len(vals) > 1 else ""
        print(f"  {k}{flag}")
        for fn, v in rows:
            print(f"      {fn:<26} {v[:40]}")

# ---------------------------------------------------------------- 系统清单
print()
print("=" * 78)
print("五、五大系统的工具与入口")
print("=" * 78)
SYSTEMS = {
    "资源/电量": ["zzz_resource.py", "zzz_convert.py"],
    "刷本": ["od_material_farm.py", "zzz_farm_plan.py"],
    "角色等级": ["zzz_level.py"],
    "技能": ["zzz_skill.py", "zzz_skill_target.py", "apply_skill.py"],
    "核心技": ["zzz_core.py", "apply_core.py"],
    "音擎": ["zzz_wengine.py", "apply_wengine.py"],
    "驱动盘": ["zzz_disc_v2.py", "zzz_disc_train.py", "zzz_disc_cycle.py",
               "zzz_equip.py", "zzz_plan.py", "zzz_status.py",
               "zzz_tune.py", "run_dismantle.py"],
    "总控": ["zzz_auto.py", "zzz_next.py", "zzz_grind.py", "zzz_daily.py"],
}
for sysname, names in SYSTEMS.items():
    exist = [n for n in names if (TOOLS / n).exists()]
    miss = [n for n in names if not (TOOLS / n).exists()]
    status = "✔" if exist and not miss else ("⚠" if exist else "✗")
    print(f"\n{status} {sysname}")
    for n in exist:
        ln = len(read(TOOLS / n).splitlines())
        print(f"      {n:<26} {ln:>4} 行")
    for n in miss:
        print(f"      {n:<26} ✗ 不存在")

# ---------------------------------------------------------------- 总控依赖
print()
print("=" * 78)
print("六、总控工具的调用链完整性")
print("=" * 78)
for orch in ["zzz_auto.py", "zzz_next.py", "zzz_grind.py", "zzz_daily.py"]:
    p = TOOLS / orch
    if not p.exists():
        continue
    s = read(p)
    calls = set(re.findall(r"[\"']?(zzz_\w+|od_\w+|run_\w+|apply_\w+)[\"']?", s))
    calls = {c for c in calls if (TOOLS / f"{c}.py").exists() and c != orch[:-3]}
    print(f"\n{orch} 调用 {len(calls)} 个工具:")
    for c in sorted(calls):
        print(f"    → {c}.py")

# ---------------------------------------------------------------- 状态文件
print()
print("=" * 78)
print("七、状态文件")
print("=" * 78)
st = BASE / "state"
for f in sorted(st.glob("*.json")):
    size = f.stat().st_size
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        kind = f"dict({len(d)})" if isinstance(d, dict) else f"list({len(d)})"
    except Exception:
        kind = "解析失败"
    print(f"  {f.name:<28} {size:>8} B  {kind}")
