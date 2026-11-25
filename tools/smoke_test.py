"""canonical 工具的冒烟测试：跑只读模式，看有没有实际报错。

静态检查（audit_*）只能发现常量和口径问题，
跑一遍才能发现「参数不认」「函数签名改了」「依赖缺失」这类真错。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
from core.paths import one_dragon_python, one_dragon_env
PY = one_dragon_python()
ENV = one_dragon_env()
# (工具, 参数, 期望退出码, 说明) 只跑不碰游戏的
SMOKE = [
    ("zzz_cost.py", ["佩洛伊斯"], 0, "养成成本表"),
    ("zzz_skill_target.py", ["佩洛伊斯"], 0, "技能目标表"),
    ("disc_gaps.py", ["--agent", "佩洛伊斯"], 0, "调律推导+止损"),
    ("filter_terms.py", [], 0, "筛选词条映射"),
    ("show_discs_v2.py", [], 0, "读盘展示"),
    ("gap_analysis.py", [], 0, "缺口分析"),
    ("explain_crit.py", [], 0, "命中率说明"),
    ("audit_all.py", [], 0, "全量体检"),
    ("audit_eff.py", [], 0, "口径体检"),
    ("audit_coords.py", [], 0, "坐标体检"),
    ("cleanup_tools.py", [], 0, "工具清理（预演）"),
]

print("=" * 76)
print("只读工具冒烟测试")
print("=" * 76)
ok = fail = 0
for tool, args, want, desc in SMOKE:
    p = BASE / "tools" / tool
    if not p.exists():
        print(f"  ✗ {tool:<26} 文件不存在")
        fail += 1
        continue
    r = subprocess.run([PY, "-u", str(p)] + args, cwd=str(BASE), env={**ENV},
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    tail = [l for l in (r.stdout or "").splitlines() if not l.startswith("[")]
    last = tail[-1][:58] if tail else ""
    if r.returncode == want or r.returncode == 2:   # 2 = 数据文件缺失（可接受）
        print(f"  ✔ {tool:<26} exit={r.returncode}  {desc}")
        ok += 1
    else:
        err = (r.stderr or "").strip().splitlines()
        eline = err[-1][:70] if err else (tail[-1][:70] if tail else "")
        print(f"  ✗ {tool:<26} exit={r.returncode}  {eline}")
        fail += 1

print()

# ---- tools.json 与实际的工具集是否一致 ----
try:
    import json as _json
    _mp = BASE / "tools.json"
    if _mp.exists():
        _m = _json.loads(_mp.read_text(encoding="utf-8"))
        _listed = {t["name"] for t in _m["tools"]}
        # 不参与清单比对的：审计类 / 一次性校验 / 本机可选 / 生成器
        _excl = {"feishu", "feishu_img", "gen_manifest", "cleanup_tools",
                 "check_42", "check_main_sub", "check_target_28",
                 "check_consistency", "check_main_formula"}
        _actual = {f.stem for f in (BASE / "tools").glob("*.py")
                   if not f.stem.startswith(("audit_", "selftest_", "_"))
                   and f.stem not in _excl}
        _miss = _actual - _listed
        _stale = _listed - _actual
        if _miss or _stale:
            print("")
            print("--- tools.json ---")
            print(f"  ✗ 脱节（跑 gen_manifest.py 重生成）")
            if _miss:
                print(f"    实际有未登记：{sorted(_miss)[:6]}")
            if _stale:
                print(f"    登记了但不存在：{sorted(_stale)[:6]}")
        else:
            print(f"   ✔ tools.json 与 {len(_actual)} 个工具一致")
except Exception as _e:
    print(f"   tools.json 校验跳过：{_e}")

print(f"通过 {ok}　失败 {fail}")

# ---- 检查带 --help 的工具参数是否完好 ----
print()
print("=" * 76)
print("参数检查（--help 不报错）")
print("=" * 76)
CLI = ["zzz_status.py", "zzz_plan.py", "zzz_equip.py", "zzz_disc_cycle.py",
       "zzz_disc_train.py", "zzz_tune.py", "zzz_disc_v2.py", "run_dismantle.py",
       "zzz_resource.py", "zzz_level.py", "zzz_skill.py", "zzz_core.py",
       "zzz_wengine.py", "zzz_convert.py", "zzz_farm_plan.py",
       "od_material_farm.py", "zzz_grind.py",
       "zzz_daily.py"]
for tool in CLI:
    p = BASE / "tools" / tool
    if not p.exists():
        print(f"  ✗ {tool} 不存在")
        continue
    r = subprocess.run([PY, "-u", str(p), "--help"], cwd=str(BASE), env={**ENV},
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if r.returncode == 0:
        n = len([l for l in (r.stdout or "").splitlines() if "--" in l])
        print(f"  ✔ {tool:<26} {n} 个参数")
    else:
        e = (r.stderr or "").strip().splitlines()
        print(f"  ✗ {tool:<26} {(e[-1] if e else '')[:60]}")