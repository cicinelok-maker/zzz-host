"""从 Enka API 读账号数据（zzzcaculator.top 提供的代理接口）。

## 用户给的站点（2026-11-26 07:19）

`https://zzzcaculator.top/` —— 一个 Vue SPA「ZZZ Calculator」（**伤害计算器**，
不是养成材料计算器）。HTML 是空壳，数据在 JS 里。

**但它的 JS 里暴露了一个 API：**

```javascript
async function na(E, m) {
  const _ = await aa(`/api/enka/zzz/${encodeURIComponent(String(E).trim())}`, m);
  return { uid: _.uid, mappedAgents: _.agents ?? [], ... };
}
```

**`GET /api/enka/zzz/<UID>` —— 输入 UID，返回该账号的角色数据。**

## 实测（UID 47668477，2026-11-26）

返回 28.9 KB：
```json
{"ok": true, "uid": "47668477", "ttlSeconds": 60,
 "agents": [{
   "enkaId": "1581", "agentId": "remielle_dan", "agentName": "蕾米埃尔·丹",
   "agentLevel": 60, "cinemaLevel": 1,
   "coreSkillLevel": "F",
   "skillLevels": {"basic": 12, "special": 10, "dodge": 10, "chain": 12, "assist": 12},
   "wEngine": {"id": "zzz_wiki_2109", "name": "空羽复归之诗",
               "level": 60, "modificationLevel": 1},
   "driveDiscs": [{
     "slot": 1, "level": 15, "locked": false,
     "mainStat": {"propertyId": "11103", "propertyLevel": 1, "propertyValue": 550},
     "subStats": [{"propertyId": "11102", "propertyLevel": 2, "propertyValue": 300}, ...]
   }]
 }]}
```

**`propertyLevel` = 该词条的强化次数** —— 这正是口径B（存在1 + 升级N）需要的。

## 价值

**对我们屏幕自动化抓的那些数据，这里全是精确值：**
```
角色等级     agentLevel
核心技等级   coreSkillLevel（"F"）
技能等级     skillLevels.{basic,special,dodge,chain,assist}
音擎          wEngine.{name,level,modificationLevel}
驱动盘        driveDiscs[].{slot,level,mainStat,subStats}
```

**不用 OCR、不用截图、不用等 2~5 分钟。一次 HTTP GET。**

## 两个限制（必须说清）

**1 只返回「展柜」里的角色**
   实测：账号有 14 个角色，API 只回了 **2 个**（蕾米埃尔·丹、简·杜）。
   `skippedAgents` 是空的 —— 说明不是「跳过」，是**源头就没有**。
   所以：**展柜角色能拿精确数据，其余还是得 OCR。**

**2 第三方服务**
   `zzzcaculator.top` 能看到你 UID 对应的账号数据。
   **这是用户要自己决定的事**，不是默认行为。
   所以这个模块**必须显式调用**，不能塞进日常流程。

## 用法

```powershell
python tools/zzz_enka.py 47668477            # 只读，打印摘要
python tools/zzz_enka.py 47668477 --write    # 写进 state/enka_<uid>.json
python tools/zzz_enka.py 47668477 --diff     # 和 OCR 抓的 status 对比
```
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
STATE = BASE / "state"
API = "https://zzzcaculator.top/api/enka/zzz/"


def fetch(uid: str, timeout: int = 40) -> dict:
    """拉一个 UID 的数据。网络失败返回 {"ok": False, "error": ...}。"""
    url = API + str(uid).strip()
    req = urllib.request.Request(url, headers={
        "User-Agent": "zzz-host/1.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def summarize(d: dict) -> None:
    """打印摘要。"""
    if not d.get("ok"):
        print(f"✘ 拉取失败：{d.get('error')}")
        return
    agents = d.get("agents") or []
    print(f"UID {d.get('uid')}：{len(agents)} 个角色（**只有展柜角色**）")
    print()
    for a in agents:
        name = a.get("agentName") or a.get("agentId") or "?"
        lv = a.get("agentLevel")
        core = a.get("coreSkillLevel")
        sk = a.get("skillLevels") or {}
        we = a.get("wEngine") or {}
        discs = a.get("driveDiscs") or []
        print(f"  {name}　Lv{lv}　核心技 {core}　影画 {a.get('cinemaLevel')}")
        print(f"    技能  普攻{sk.get('basic','?')} 特殊{sk.get('special','?')} "
              f"闪避{sk.get('dodge','?')} 连携{sk.get('chain','?')} 支援{sk.get('assist','?')}")
        print(f"    音擎  {we.get('name','?')} Lv{we.get('level','?')} "
              f"精{we.get('modificationLevel','?')}")
        print(f"    驱动盘 {len(discs)} 块：")
        for dd in discs:
            ms = dd.get("mainStat") or {}
            subs = dd.get("subStats") or []
            rolls = sum(int(s.get("propertyLevel") or 1) for s in subs)
            print(f"      {dd.get('slot')}号位 Lv{dd.get('level')}　"
                  f"主 {ms.get('propertyId')}={ms.get('propertyValue')}　"
                  f"副 {len(subs)} 条（总强化 {rolls} 次）")
        print()


def to_status(a: dict) -> dict:
    """把 Enka 的一个 agent 转成我们 status_<角色>.json 的形状。

    **propertyId 到词条名的映射还没做** —— 所以这里只放原始 id，
    交给上层决定怎么映射（`core/disc_stats.py` 有自己的词条表）。
    """
    return {
        "agent": a.get("agentName") or a.get("agentId"),
        "char_level": f"等级{a.get('agentLevel')}",
        "skills": {
            "普通攻击": f"{a.get('skillLevels', {}).get('basic', 0):02d}/12",
            "特殊技": f"{a.get('skillLevels', {}).get('special', 0):02d}/12",
            "闪避": f"{a.get('skillLevels', {}).get('dodge', 0):02d}/12",
            "连携技": f"{a.get('skillLevels', {}).get('chain', 0):02d}/12",
            "支援技": f"{a.get('skillLevels', {}).get('assist', 0):02d}/12",
        },
        "core_skill_level": a.get("coreSkillLevel"),
        "wengine": a.get("wEngine") or {},
        "slots": [
            {
                "slot": dd.get("slot"),
                "level": dd.get("level"),
                "locked": dd.get("locked"),
                "main_property_id": (dd.get("mainStat") or {}).get("propertyId"),
                "main_value": (dd.get("mainStat") or {}).get("propertyValue"),
                "subs": [
                    {"propertyId": s.get("propertyId"),
                     "rolls": s.get("propertyLevel"),
                     "value": s.get("propertyValue")}
                    for s in (dd.get("subStats") or [])
                ],
                "_source": "enka",
            }
            for dd in (a.get("driveDiscs") or [])
        ],
        "_source": "enka",
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="从 Enka 读账号数据（只含展柜角色，不含全账号）")
    ap.add_argument("uid", help="游戏 UID")
    ap.add_argument("--write", action="store_true",
                    help="写进 state/enka_<uid>.json")
    ap.add_argument("--status", action="store_true",
                    help="同时写 state/status_enka_<角色>.json（不覆盖 OCR 的）")
    ap.add_argument("--json", action="store_true", help="原始 JSON 输出")
    args = ap.parse_args()

    d = fetch(args.uid)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0 if d.get("ok") else 3

    summarize(d)
    if not d.get("ok"):
        return 3

    if args.write:
        STATE.mkdir(parents=True, exist_ok=True)
        p = STATE / f"enka_{args.uid}.json"
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {p}")

    if args.status:
        STATE.mkdir(parents=True, exist_ok=True)
        for a in (d.get("agents") or []):
            st = to_status(a)
            nm = st.get("agent") or "unknown"
            nm = str(nm).replace("/", "_")
            p = STATE / f"status_enka_{nm}.json"
            p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"已写入 {p}" +
                  ("（注意：文件名带 enka_ 前缀，不覆盖 OCR 的 status_）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
