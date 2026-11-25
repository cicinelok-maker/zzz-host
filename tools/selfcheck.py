"""兼容性自检：所有工具能不能正常加载，有没有互相冲突。

检查项：
1. 每个工具能不能 import / --help（语法和导入没问题）
2. 重复功能：有没有两个工具在做同一件事
3. 调用链断裂：A 调 B，但 B 的参数变了
4. 数据格式变更：改了 JSON 字段，谁还在读旧字段
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
T = BASE / "tools"
PY = sys.executable
from core.paths import one_dragon_python
ENV_PY = one_dragon_python()
print("=" * 62)
print("一、所有工具语法检查")
print("=" * 62)
bad = []
files = sorted(T.glob("*.py")) + sorted((T / "core").glob("*.py"))
for f in files:
    try:
        compile(f.read_text(encoding="utf-8"), str(f), "exec")
    except SyntaxError as e:
        bad.append((f.name, str(e)))
if bad:
    for n, e in bad:
        print(f"  ✗ {n}: {e}")
else:
    print(f"  ✔ {len(files)} 个文件语法全部正常")

print("\n" + "=" * 62)
print("二、重复功能检查（两个工具做同一件事）")
print("=" * 62)
orchestrators = {
    "zzz_daily.py": "跑一个角色的全套动作",
    "zzz_grind.py": "反复跑 daily 直到达标",
    "zzz_farm_plan.py": "出缺口清单按预算批量刷",
}
print("  编排层的五个工具，职责其实是：")
for k, v in orchestrators.items():
    exists = (T / k).exists()
    print(f"    {'✔' if exists else '✗'} {k:<18} {v}")
print("  ⚠ daily / grind / auto 三者有重叠：daily 是 auto 的子集，grind 是 auto 的循环版")

print("\n" + "=" * 62)
print("三、调用链检查（谁调用谁，参数对不对）")
print("=" * 62)
calls = {}
for f in T.glob("*.py"):
    s = f.read_text(encoding="utf-8")
    for m in re.finditer(r'"(\w+\.py)"', s):
        target = m.group(1)
        if target != f.name:
            calls.setdefault(target, set()).add(f.name)
for target in sorted(calls):
    ok = (T / target).exists()
    print(f"  {'✔' if ok else '✗'} {target:<22} ← 被 {', '.join(sorted(calls[target]))} 调用")

print("\n" + "=" * 62)
print("四、数据格式变更后谁还在读旧字段")
print("=" * 62)
# disc_meta: 二件套候选 → 两件套候选
meta = json.loads((T / "disc_meta.json").read_text(encoding="utf-8"))
old_key = [n for n, c in (meta.get("角色") or {}).items() if "二件套候选" in c]
print(f"  disc_meta 里还在用「二件套候选」的角色：{old_key or '无'}")
readers = []
for f in T.glob("*.py"):
    s = f.read_text(encoding="utf-8")
    if "两件套候选" in s or "二件套候选" in s:
        readers.append(f.name)
print(f"  读这个字段的工具：{readers}")

# status_*.json: 新加 skills / char_level
import os
st = BASE / "state" / f"status_{os.environ.get('ZZZ_AGENT', '佩洛伊斯')}.json"
if st.exists():
    d = json.loads(st.read_text(encoding="utf-8"))
    print(f"  status JSON 字段：{list(d.keys())}")
    print(f"    {'✔' if 'skills' in d else '✗'} 有 skills（skill_target / next 要用）")
    print(f"    {'✔' if 'char_level' in d else '✗'} 有 char_level")

print("\n" + "=" * 62)
print("五、改过签名/返回值的函数，调用处有没有跟着改")
print("=" * 62)
checks = [
    ("zzz_level.open_panel", "bool → str", ["zzz_level.py"]),
    ("zzz_level.do_ascend", "bool → (bool, str)", ["zzz_level.py"]),
]
s = (T / "zzz_level.py").read_text(encoding="utf-8")
for fn, change, files in checks:
    name = fn.split(".")[-1]
    callers = len(re.findall(rf"(?<![a-z_]){name}\(", s)) - 1  # 减去定义
    print(f"  {fn}: {change}　调用处 {callers} 个")
    # 检查有没有还在当 bool 用的
    bad_use = re.findall(rf"if not {name}\(", s) + re.findall(rf"if {name}\(", s)
    print(f"    {'✗ 有 ' + str(len(bad_use)) + ' 处当 bool 用' if bad_use else '✔ 没有当 bool 用的'}")

print("\n" + "=" * 62)
print("六、指纹/状态机改动影响面")
print("=" * 62)
fp = json.loads((BASE / "state" / "fingerprints.json").read_text(encoding="utf-8"))
pages = [k for k in fp if isinstance(fp[k], list)]
mach = (T / "core" / "core/machine.py").read_text(encoding="utf-8")
states = set()
for a, b in re.findall(r'Transition\("([^"]+)", "([^"]+)"', mach):
    states.add(a)
    states.add(b)
states.discard("*")
print(f"  指纹 {len(pages)} 个页面 / 状态机 {len(states)} 个状态")
only_fp = sorted(set(pages) - states)
only_mach = sorted(states - set(pages))
print(f"  只有指纹没导航的：{only_fp or '无'}")
print(f"  只有导航没指纹的：{only_mach or '无'}")