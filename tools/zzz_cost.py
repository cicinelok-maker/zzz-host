"""成本估算（重写版）：按实际等级/技能状态算，不套固定值。

## 数据来源优先级

    1. state/status_<角色>.json   （zzz_status 跑过才有，最准）
    2. state/agent_elements.json  （只有等级和属性）
    3. 都读不到 → 标记未知，不瞎猜

## 校准说明

下面的成本表按游戏常见需求粗估，**未逐项校准**，只用于排序和规划量级。
单位：材料个数；电量按副本单次消耗 × 次数算。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent

# 从 N 级练到 60 需要的经验（累计，单位千）
LEVEL_EXP_K = {1: 1800, 10: 1500, 20: 1100, 30: 750, 40: 450, 50: 200, 60: 0}
# 职级晋升认证章（每次，累计）
ASCEND_CERT = {20: 4, 30: 20, 40: 20, 50: 30, 60: 0}
# 单个技能从 N 到 12 需要的芯片（累计，含各阶）
SKILL_CHIP = {1: 125, 2: 118, 3: 110, 4: 98, 5: 86, 6: 72,
              7: 58, 8: 44, 9: 30, 10: 18, 11: 8, 12: 0}
# 核心技每圈需要
CORE_DATA = {"D": 9, "E": 15, "F": 30}
CORE_RELIC = {"D": 2, "E": 3, "F": 4}
# 音擎从 N 到 60 需要的蓄电池（单把，累计）
WENGINE_BATT = {1: 380, 10: 340, 20: 280, 30: 210, 40: 140, 50: 60, 60: 0}

# 副本：单次电量 / 单次产出
RUNS = {
    "认证章":  {"电量": 30, "产出": 3},   # 实战模拟室·基础材料
    "芯片":    {"电量": 30, "产出": 8},   # 实战模拟室·代理人技能
    "高维数据": {"电量": 40, "产出": 5},   # 专业挑战室
    "刻命残蜕": {"电量": 0, "产出": 2},   # 恶名狩猎（每周3次免费）
    "蓄电池":  {"电量": 60, "产出": 12},  # 区域巡防
}


def read_levels() -> dict[str, int]:
    """角色等级。**按文件头声明的优先级来读**（BUG-145）。

    ## 原来只读了第 2 级

    文件头写着：
        1. state/status_<角色>.json   （最准）
        2. state/agent_elements.json  （只有等级和属性）
        3. 都读不到 → 标记未知，不瞎猜

    但实现**只读第 2 个**，从来不碰 `status_*.json` 里的 `char_level`。
    于是「刚跑过 zzz_status、数据最新」这种情况用不上，
    而 `agent_elements.json` 在我修 BUG-128 之前根本没人写 ——
    读者拿的是一份可能几个月前的缓存。
    """
    out: dict[str, int] = {}

    # ① status_*.json 的 char_level（最准，刚盘点过就是最新的）
    for f in sorted((BASE / "state").glob("status_*.json")):
        if f.name.startswith("core_status_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue                    # 坏文件跳过，别让整个成本表崩
        agent = d.get("agent") or f.stem.replace("status_", "", 1)
        digits = re.sub(r"\D", "", str(d.get("char_level") or ""))
        if digits:
            out[agent] = int(digits)

    # ② agent_elements.json 只补那些没跑过 status 的
    p = BASE / "state" / "agent_elements.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        for k, v in d.items():
            if k in out:
                continue                # ① 有就别覆盖
            digits = re.sub(r"\D", "", str((v or {}).get("等级", "")))
            # ③ 读不到就是未知（-1），不当 1 级 —— 那是**最贵**的估算
            out[k] = int(digits) if digits else -1
    return out


def read_status(agent: str) -> dict:
    p = BASE / "state" / f"status_{agent}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def skill_levels(agent: str) -> dict[str, int]:
    st = read_status(agent)
    skills = st.get("skills") or st.get("技能等级") or {}
    out = {}
    for name, v in (skills.items() if isinstance(skills, dict) else []):
        digits = re.sub(r"\D", "", str(v))
        out[name] = int(digits[:2]) if len(digits) >= 2 else 0
    return out


def estimate(agent: str, lv: int) -> dict:
    # 等级
    if lv < 0:
        # 等级未知 —— 按「已满级」算（成本 0）并标注，不要按 1 级（成本最大）
        return {"lv": -1, "exp": 0, "cert": 0, "chip": 0, "data": 0,
                "relic": 0, "batt": 0, "unknown": True}
    exp_k = sum(v for k, v in LEVEL_EXP_K.items() if lv <= k < 60)
    cert = sum(v for k, v in ASCEND_CERT.items() if k > lv)

    # 技能：读不到就按 1 级算，并标记
    sk = skill_levels(agent)
    known = bool(sk)
    if known:
        # **SKILL_CHIP 是「从 N 到 12 的累计值」，不是每级增量。**
        #
        # 原来写 `sum(SKILL_CHIP[i] for i in range(cur, 12))` ——
        # 把累计值当增量相加了。cur=1 时求和 = 767 个芯片，
        # 而正确值是 125 个 —— **正好 6.1 倍**（RT 实测总量虚高 6.2 倍）。
        chip = sum(SKILL_CHIP.get(cur, 0)
                   for cur in sk.values())
    else:
        chip = SKILL_CHIP[1] * 5

    # 核心技：假设 D/E/F 都还没满
    data = sum(CORE_DATA.values())
    relic = sum(CORE_RELIC.values())

    # 音擎：读不到按 1 级算
    batt = WENGINE_BATT[1]

    return {"lv": lv, "exp_k": exp_k, "cert": cert, "chip": chip,
            "data": data, "relic": relic, "batt": batt,
            "skills_known": known}


def to_battery(e: dict) -> dict:
    out = {}
    for key, mat in (("cert", "认证章"), ("chip", "芯片"),
                     ("data", "高维数据"), ("relic", "刻命残蜕"),
                     ("batt", "蓄电池")):
        n = e[key]
        cfg = RUNS[mat]
        if cfg["产出"] <= 0:
            out[mat] = 0
            continue
        runs = -(-n // cfg["产出"])
        out[mat] = runs * cfg["电量"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", nargs="?")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    levels = read_levels()
    names = [args.agent] if args.agent else (sorted(levels) if args.all else [])
    if not names:
        print("要指定角色或 --all")
        return 2

    print(f"{'角色':<8} {'等级':>4} {'认证章':>6} {'芯片':>6} {'高维':>5} "
          f"{'残蜕':>4} {'蓄电池':>6} {'电量':>7}  技能数据")
    print("-" * 76)
    rows = []
    for n in names:
        e = estimate(n, levels.get(n, 1))
        b = to_battery(e)
        total = sum(b.values())
        rows.append((n, e, b, total))
        flag = "有" if e["skills_known"] else "缺"
        print(f"{n:<8} {e['lv']:>4} {e['cert']:>6} {e['chip']:>6} "
              f"{e['data']:>5} {e['relic']:>4} {e['batt']:>6} {total:>7}  {flag}")

    if len(rows) > 1:
        print("-" * 76)
        tot = sum(r[3] for r in rows)
        print(f"合计电量 {tot}　= {tot / 240:.0f} 轮满电量"
              f"（每轮 240 电，6 分钟回 1 电）")
        print(f"约 {tot / 240 * 24:.0f} 小时")
    print("\n注：成本表按常见需求粗估，未逐项校准，只用于排序和量级判断。")
    return 0


if __name__ == "__main__":
    sys.exit(main())