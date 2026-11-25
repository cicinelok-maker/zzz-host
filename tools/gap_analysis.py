"""分析距离小毕业还差多少，差在哪个位号。"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
import os

# 统一从 core.state 读，读不到会给清晰提示
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.state import load_status as _ls, load_meta as _lm
def __load_status__():
    return _ls()
def __load_meta__():
    return _lm()

AGENT = os.environ.get("ZZZ_AGENT", "佩洛伊斯")
s = __load_status__()

# 从 disc_cfg 取，别在这里再写一遍（改一处漏一处的老坑）
from core.disc_cfg import THRESHOLDS as _TH
TARGET = _TH["graduation"]
print("各位号有效词条：")
tot = 0.0
for x in s.get("slots") or []:
    e = float(x.get("eff") or 0)
    tot += e
    bar = "★" * int(e * 2)
    print(f"  {x['slot']}号位  {x.get('set','?'):<6} Lv{str(x.get('level')):<3} "
          f"有效 {e:>4}  {bar}")

print(f"\n合计 {tot} / 目标 {TARGET}　差 {TARGET - tot}")
print(f"6 个位号平均需要 {TARGET / 6:.1f} 条")
print()
print("按位号看缺口：")
for x in s.get("slots") or []:
    e = float(x.get("eff") or 0)
    need = TARGET / 6
    if e < need:
        print(f"  {x['slot']}号位 差 {need - e:.1f} 条（现在 {e}，要 {need:.1f}）")
print()
print("说明：一条「有效词条」= 一次升级落在 攻击力百分比/暴击率/暴击伤害 上。")
print("一块满级 S 盘最多 5 次升级，全部命中才 5 条。")
print(f"所以要凑 {TARGET} 条，6 个位号都得是高命中的盘。")
