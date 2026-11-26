"""用 UID API 交叉核对角色库。

## 用户要求（2026-11-26 07:43）

> 还有那个api的uid确认角色库也能做一下

## 它到底能核对什么（实测，2026-11-26）

```
agent_roster.json: 14 个
  佩洛伊斯 / 蕾米埃尔 / 维琳娜 / 派派 / 猫又 / 丽娜 / 妮可 /
  莱卡恩 / 苍角 / 安比 / 真斗 / 潘引壶 / 凯撒 / 波可娜

API（/api/enka/zzz/47668477）: 2 个
  蕾米埃尔·丹 / 简·杜
```

**抓到两个真问题：**

**1 `简·杜` 不在 roster 里** —— **我们的扫描漏了这个角色。**
   这是有价值的：说明 `zzz_who --scan` 有遗漏（可能是列表滚动没到底）。

**2 `蕾米埃尔·丹` vs roster 的 `蕾米埃尔`** —— 带后缀，名字归一没处理。

## 但它不是完整的角色库核对

**API 只返回「展柜」角色**（玩家公开的那 2 个），不是全账号 14 个。
`skippedAgents` 是空的 —— 不是跳过，是源头就没有。

所以这个工具的定位是：
**「抽样交叉验证」** —— 能发现遗漏（像简·杜），但不能替代全量扫描。

## 用法

```powershell
python tools/zzz_uid.py 47668477              # 核对 roster，报告差异
python tools/zzz_uid.py 47668477 --detail     # 顺便打印每个角色的精确数据
```
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

BASE = pathlib.Path(__file__).resolve().parent.parent
STATE = BASE / "state"
API = "https://zzzcaculator.top/api/enka/zzz/"


def _norm_loose(s: str) -> str:
    """更宽松的归一：去掉「·」后面的那段。"""
    t = str(s)
    if "·" in t:
        t = t.split("·")[0]
    return t.replace(" ", "").strip()


def fetch(uid: str, timeout: int = 40) -> dict:
    url = API + str(uid).strip()
    req = urllib.request.Request(url, headers={
        "User-Agent": "zzz-host/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def load_roster() -> list[str]:
    p = STATE / "agent_roster.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    v = d.get("agents") or d.get("角色")
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, dict):
        return [str(x) for x in v.keys()]
    return [str(x) for x in d.keys() if not str(x).startswith("_")]


def main() -> int:
    ap = argparse.ArgumentParser(description="用 UID API 交叉核对角色库")
    ap.add_argument("uid", help="游戏 UID")
    ap.add_argument("--detail", action="store_true", help="打印每个角色的精确数据")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    roster = load_roster()
    print(f"agent_roster.json：{len(roster)} 个角色")

    d = fetch(args.uid)
    if not d.get("ok"):
        print(f"✘ API 失败：{d.get('error')}")
        return 3

    agents = d.get("agents") or []
    api_names = [a.get("agentName") or a.get("agentId") or "?" for a in agents]
    print(f"API（UID {args.uid}）：{len(api_names)} 个（**只有展柜角色**）")
    print()

    # 对照
    roster_loose = {_norm_loose(x) for x in roster}
    missing, matched = [], []
    for a in agents:
        nm = a.get("agentName") or a.get("agentId") or "?"
        if _norm_loose(nm) in roster_loose:
            matched.append(nm)
        else:
            missing.append(nm)

    print("=== 核对结果 ===")
    for nm in matched:
        print(f"  ✔ {nm}　两边都有")
    for nm in missing:
        print(f"  ⚠ {nm}　**API 有，但 roster 里没有**")
        print(f"      → 可能 zzz_who --scan 漏了（列表没滚到底？）")

    if not missing:
        print("  ✔ 展柜角色全部在 roster 里")

    print()
    print("注意：API 只返回展柜角色（玩家公开的那几个）。")
    print("所以这个核对是**抽样**，不能证明 roster 完整；")
    print("但它能抓到「漏掉了某个角色」这种错（实测抓到过一个）。")

    if args.detail:
        print()
        print("=== 展柜角色的精确数据 ===")
        for a in agents:
            nm = a.get("agentName") or "?"
            sk = a.get("skillLevels") or {}
            we = a.get("wEngine") or {}
            discs = a.get("driveDiscs") or []
            print(f"  {nm}　Lv{a.get('agentLevel')}　核心{a.get('coreSkillLevel')}"
                  f"　影画{a.get('cinemaLevel')}")
            print(f"    技能 普攻{sk.get('basic')} 特殊{sk.get('special')} "
                  f"闪避{sk.get('dodge')} 连携{sk.get('chain')} 支援{sk.get('assist')}")
            print(f"    音擎 {we.get('name')} Lv{we.get('level')} 精{we.get('modificationLevel')}")
            for dd in discs:
                ms = dd.get("mainStat") or {}
                subs = dd.get("subStats") or []
                rolls = sum(int(s.get("propertyLevel") or 1) for s in subs)
                print(f"      {dd.get('slot')}号位 Lv{dd.get('level')}　"
                      f"主{ms.get('propertyId')}={ms.get('propertyValue')}　"
                      f"副{len(subs)}条(强化{rolls}次)")

    if args.json:
        print()
        print(json.dumps({"roster": roster, "api": api_names,
                          "matched": matched, "missing": missing},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())