"""审计：这套东西作为「别人的 agent 的工具集」够不够用。

## 一个外部 agent 接入需要什么

1. **能力清单** —— 有哪些工具、每个干什么、参数是什么（机器可读）
2. **稳定输出** —— 结构化结果（JSON），不是只有给人看的 print
3. **退出码约定** —— 成功/失败/配置缺失要能区分
4. **状态契约** —— 中间产物（status_*.json / discs_v2.json）的字段定义
5. **前置条件自检** —— 一条命令确认环境能用
6. **幂等性** —— 重复跑不会搞坏
"""
import json
import pathlib
import re
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"

print("=" * 78)
print("① 哪些工具有 --json（结构化输出）")
print("=" * 78)
with_json = []
without = []
for f in sorted(T.glob("*.py")):
    if f.name.startswith(("audit_", "selftest_", "_", "check_", "gen_")):
        continue
    s = f.read_text(encoding="utf-8", errors="replace")
    if '"--json"' in s or "'--json'" in s:
        with_json.append(f.name)
    else:
        without.append(f.name)
print(f"  有 --json：{len(with_json)} 个")
for n in with_json[:12]:
    print(f"    {n}")
print(f"  没有 --json：{len(without)} 个")
for n in without[:12]:
    print(f"    {n}")

print()
print("=" * 78)
print("② 退出码约定")
print("=" * 78)
codes = {}
for f in sorted(T.glob("*.py")):
    if f.name.startswith(("audit_", "selftest_", "_")):
        continue
    s = f.read_text(encoding="utf-8", errors="replace")
    found = sorted(set(int(m) for m in re.findall(r"return (\d)\b", s)))
    if found:
        codes[f.name] = found
all_codes = sorted({c for v in codes.values() for c in v})
print(f"  用到的退出码：{all_codes}")
print(f"  有 return 数字的工具：{len(codes)} 个")

print()
print("=" * 78)
print("③ 中间产物（状态契约）")
print("=" * 78)
STATE = BASE / "state"
if STATE.exists():
    for f in sorted(STATE.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                print(f"  {f.name:<28} dict  keys={list(d.keys())[:5]}")
            elif isinstance(d, list):
                k = list(d[0].keys())[:6] if d and isinstance(d[0], dict) else "?"
                print(f"  {f.name:<28} list[{len(d)}] 项字段={k}")
        except Exception:
            print(f"  {f.name:<28} 读不了")

print()
print("=" * 78)
print("④ 有没有机器可读的能力清单")
print("=" * 78)
for name in ["tools.json", "manifest.json", "capabilities.json",
             "capabilities.md", "AGENTS.md", "agent.md"]:
    p = BASE / name
    print(f"  {'✔' if p.exists() else '✘'} {name}")

print()
print("=" * 78)
print("⑤ 给人看的文档有多大（agent 读不读得动）")
print("=" * 78)
for name in ["README.md", "INSTALL.md", "TOOLS.md", "MAINTENANCE.md"]:
    p = BASE / name
    if p.exists():
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        print(f"  {name:<20} {n:>5} 行")