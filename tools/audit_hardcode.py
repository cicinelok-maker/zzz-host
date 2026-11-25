"""审计：代码里有多少硬编码的角色假设。

## 用户 2026-11-25

> 你这些搞的旧代码，不会是基于佩洛伊丝开发的吧，
> 如果别人点了其他角色的名呢，又或者是不在我们的角色库之内呢

## 查三件事

**A. 硬编码「佩洛伊斯」的地方**
看看是默认值（可接受）还是写死的逻辑（不可接受）。

**B. 硬编码其他角色名的地方**
同理。

**C. 不在角色库里的角色会怎样**
`cfg_of` 会返回什么？会不会静默走错分支？
"""
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
T = BASE / "tools"

# 所有 py 文件
FILES = list(T.glob("*.py")) + list((T / "core").glob("*.py"))

# 角色名（从 disc_meta 拿）
import json
meta = json.loads((T / "disc_meta.json").read_text(encoding="utf-8"))
CHAR_NAMES = sorted((meta.get("角色") or {}).keys(),
                    key=len, reverse=True)   # 长的优先，避免「比利」先匹配「星徽·比利」

print("=" * 78)
print("A. 「佩洛伊斯」硬编码在哪")
print("=" * 78)
hits = []
for f in FILES:
    if f.stem.startswith(("audit_", "selftest_", "_")):
        continue
    s = f.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(s.splitlines(), 1):
        if "佩洛伊斯" in line:
            hits.append((f.stem, i, line.strip()))
for name, i, line in hits:
    kind = ""
    if "DEFAULT_AGENT" in line or "default=" in line or "nargs=" in line:
        kind = "  ← 默认值（可接受）"
    print(f"  {name:<22} L{i:<5} {line[:60]}{kind}")
print(f"\n  共 {len(hits)} 处")

print()
print("=" * 78)
print("B. 其他角色名的硬编码")
print("=" * 78)
other = []
for f in FILES:
    if f.stem.startswith(("audit_", "selftest_", "_")):
        continue
    s = f.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(s.splitlines(), 1):
        for nm in CHAR_NAMES:
            if nm == "佩洛伊斯":
                continue
            if nm in line and not line.strip().startswith("#"):
                other.append((f.stem, i, nm, line.strip()[:56]))
                break
if other:
    for name, i, nm, line in other[:20]:
        print(f"  {name:<22} L{i:<5} [{nm}] {line}")
else:
    print("  ✔ 没有")

print()
print("=" * 78)
print("C. 不在角色库的角色会怎样")
print("=" * 78)
import sys
sys.path.insert(0, str(T))
from core.agent_cfg import cfg_of, role_of, element_of
from core.agent_name import canonical_agent

TEST = ["不存在的角色", "无此人物", "", "「野人」", "某某某"]
for t in TEST:
    try:
        c = cfg_of(t)
        print(f"  {t!r:<16} → 归一 {canonical_agent(t)!r:<12} "
              f"定位={c['定位']:<4} 来源={c['_来源']:<6} "
              f"四件套={c.get('四件套') or '空'}")
    except Exception as e:
        print(f"  {t!r:<16} → ✘ {type(e).__name__}: {e}")
