"""展示 discs_v2.json 的解析明细。"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
P = BASE / "od_test" / "discs_v2.json"
if not P.exists():
    print("✘ 还没有「od_test/discs_v2.json」——还没跑过，先跑：")
    print(f"     python tools/zzz_disc_v2.py <角色名>")
    raise SystemExit(2)
d = json.loads(P.read_text(encoding="utf-8"))
print(f"共 {len(d)} 块\n")

print("=== 前 5 块的完整解析 ===")
for it in d[:5]:
    print(f"{it['set']}[{it['slot']}] Lv{it['level']}/{it['cap']}  "
          f"主:{it['main']} {it['main_raw']}")
    for s in it["subs"]:
        # 新结构没有 pct / raw，按值里有没有 % 判断，raw 用 name 兜
        has_pct = s.get("pct")
        if has_pct is None:
            has_pct = "%" in str(s.get("value", ""))
        pct = "%" if has_pct else ""
        raw = s.get("raw") or s.get("name", "")
        print(f"    {s.get('name', ''):<12} {s.get('value', '')}{pct:<2}  "
              f"rolls={s.get('rolls', 0)}   原始={raw!r}")
    print(f"    有效 = {it['eff_rolls']}")
    print()

print("=== 有效值分布 ===")
from collections import Counter
c = Counter(it["eff_rolls"] for it in d)
for k in sorted(c):
    print(f"  有效 {k}: {c[k]} 块")