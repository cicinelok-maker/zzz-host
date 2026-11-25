"""全歪判定逻辑 + 全中判定，用真实数据展示。

## 判定链

每块盘读出来是：4 条副词条，每条带 +N（N = 这条被升级了几次）。

    总升级次数 = Σ(+N) 所有副词条
                 注意：如果盘起始只有 3 条，第 4 条是升级解锁的，
                 解锁那一次不计 +N，所以总升级数会比 floor(等级/3) 少 1

    有效升级次数 = Σ(+N) 只算有效词条，次选词条算 0.5

判定：
    全歪   → 有效升级次数 == 0 且 总升级次数 > 0
    全中   → 有效升级次数 == 总升级次数 且 总升级次数 > 0
    部分   → 介于两者之间，用命中率表示

## 实例

    攻击力+2 / 防御力+1 / 生命值+1 / 异常精通+1
      总升级 = 5，有效只有 攻击力+2 = 2  →  命中率 40%

    攻击力+3 / 暴击率+2 / 防御力(没升) / 生命值(没升)
      总升级 = 5，有效 = 3+2 = 5        →  命中率 100%，全中
"""
import json
import sys
from pathlib import Path

HERE_ = Path(__file__).resolve().parent

sys.path.insert(0, str(HERE_))
from core import disc_stats as ds  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
if not (BASE / "tools" / "disc_meta.json").exists():
    print("✘ 还没有「od_test/discs_v2.json」——还没跑过，先跑：")
    print(f"     python tools/zzz_disc_v2.py <角色名>")
    raise SystemExit(2)
meta = json.loads((BASE / "tools" / "disc_meta.json").read_text(encoding="utf-8"))
import os
AGENT = os.environ.get("ZZZ_AGENT", "佩洛伊斯")
cfg = (meta.get("角色") or {}).get(AGENT) or {}
GOOD = set(cfg.get("有效副词条") or [])
HALF = set(cfg.get("次选副词条") or [])

_DV2 = BASE / "od_test" / "discs_v2.json"
if not _DV2.exists():
    print("✘ 还没有 od_test/discs_v2.json —— 先盘点一次：")
    print("     python tools/zzz_disc_v2.py <角色名>")
    raise SystemExit(2)
d = json.loads(_DV2.read_text(encoding="utf-8"))

print(f"有效 {sorted(GOOD)}　次选 {sorted(HALF)}\n")
print(f"{'盘':<16}{'等级':>5}{'总升级':>6}{'有效升级':>8}{'命中率':>7}  判定")
print("-" * 66)

buckets = {"全歪": [], "全中": [], "部分命中": [], "没升过": []}
for it in d:
    subs = it["subs"]
    tot = sum(s["rolls"] for s in subs)
    eff = sum((1 + s["rolls"]) * ds.is_effective(s["name"], GOOD, HALF) for s in subs)
    rate = (eff / tot * 100) if tot else 0

    if it["level"] == 0 or tot == 0:
        v = "没升过"
    elif eff == 0:
        v = "全歪"
    elif abs(eff - tot) < 1e-6:
        v = "全中"
    else:
        v = "部分命中"
    buckets[v].append((it, tot, eff, rate))

    detail = " ".join(f"{s['name']}+{s['rolls']}" for s in subs)
    print(f"{it['set']}[{it['slot']}]{'':<3}{it['level']:>5}{tot:>6}{eff:>8.1f}"
          f"{rate:>6.0f}%  {v}")
    print(f"    {detail}")

print()
print("=== 汇总 ===")
for k, v in buckets.items():
    print(f"  {k}: {len(v)} 块")