"""通用养成链条：指名 → 读缺口 → 排副本 → 出计划。

## 用户要的（2026-11-26 07:55）

> 现在有了官方的养成指南那别人是不是就能指名，扫角色，差缺口，
> 根据缺口材料刷本，然后升级了呢，而不是仅仅根据你对我的角色库的熟悉，
> 这个要打磨成通用的

## 现在链条长这样

```
① 指名        resolve_agent / 用户说名字
② 扫角色      zzz_who.py --scan          → 15 个（刚修好）
③ 读缺口      zzz_guide.py               → 官方所需的材料名 + 仍需数量
④ 排副本      本工具                      → 材料名 → 副本 + 次数 + 电量
⑤ 升级        zzz_core upgrade / zzz_daily
```

**③ 是这轮最大的改变**：以前缺口是自己算的（材料表 + 公式 + 库存），
现在直接读游戏（官方精确值，带真实库存）。

## ④ 为什么还需要一张表

游戏给了「缺什么」，**但没给「去哪刷」**。

不过「材料名 → 副本」是**规则推导**，不是按角色维护的知识：

```
初阶/高阶/执锋者认证章  → 实战模拟室·代理人晋升（{职业}演练）
特化{属性}芯片          → 实战模拟室·代理人技能（{属性}测试）
{职业}组件/增强型/特化型 → 实战模拟室·音擎改装（{职业}试验）
资深调查员记录          → 实战模拟室·基础材料（代理人经验）
高维数据：深蚀回路      → 专业挑战室
{boss材料}             → 恶名狩猎·{boss}
{套装}                 → 区域巡防·{副本}
```

**所以表是「材料类型 → 副本类型」的通用映射，不是「角色 → 一堆材料」。**
新增角色不用改表；只有新**材料类型**才需要加一行。

## 用法

```powershell
python tools/zzz_gap.py 挽昼              # 读游戏里的缺口，出刷本计划
python tools/zzz_gap.py 挽昼 --json
```
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

BASE = HERE.parent

# 职业 → 演练名
ROLES = ("强攻", "异常", "命破", "击破", "支援", "防护", "锋御")
# 属性 → 芯片名
CHIP_ATTR = {
    "物理": "物理", "火": "引燃", "冰": "冰结", "电": "感电",
    "以太": "以太", "风": "风蚀", "流明": "流明",
    "烈霜": "冰结", "玄墨": "以太", "凛刃": "物理",
}

# 实战模拟室的电量/产出（每次刷本 = 5 卡）
CARD_BATTERY = 20
CARDS = 5
RUN_BATTERY = CARD_BATTERY * CARDS      # 100

PROD = {
    "认证章": 15,       # 每卡 3 × 5
    "芯片": 40,         # 每卡 8 × 5
    "音擎组件": 15,
    "角色经验": 15,
    "镀剂": 15,
}


def _load(name: str) -> dict:
    try:
        return json.loads((HERE / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _agent_role_attr(agent: str) -> tuple[str, str]:
    """取角色的 定位 和 属性。取不到返回 ("", "")。"""
    try:
        from core.agent_cfg import cfg_of, element_of
        c = cfg_of(agent)
        role = (c.get("定位") or "").split("/")[0]
        return role, element_of(agent) or ""
    except Exception:
        return "", ""


def infer_role_attr(materials: list[str]) -> tuple[str, str]:
    """**从材料名反推角色的 定位 和 属性。**

    ## 为什么这是通用性的关键

    以前「这个角色是什么定位」要查 `disc_meta.json`（64 个手写角色）。
    不在库里就默认「强攻」—— **猜错了整份刷本计划都错。**

    但官方养成指南给的材料名里，**直接写着定位和属性**：
    ```
    初阶锋御认证章   → 定位 = 锋御
    高阶锋御认证章   → 定位 = 锋御
    执锋者认证章     → 定位 = 锋御（专属章名也能反查）
    特化以太芯片     → 属性 = 以太
    强攻组件         → 定位 = 强攻
    ```

    **所以不需要角色库 —— 从「游戏说缺什么材料」就能推出「这是什么角色」。**

    实测：挽昼 不在 disc_meta（默认猜强攻），但材料名写着「锋御认证章」
    → 正确推出 定位=锋御。

    Returns (定位, 属性)，推不出返回空串。
    """
    role = ""
    attr = ""

    # 专属认证章名 → 职业
    CERT = {
        "先行者": "强攻", "掌控者": "异常", "裁决者": "命破",
        "破阵者": "击破", "统御者": "支援", "捍卫者": "防护",
        "执锋者": "锋御",
    }

    for m in materials:
        t = str(m)
        if not role:
            for r in ("锋御", "命破", "强攻", "击破", "异常", "支援", "防护"):
                if r in t and "认证章" in t:
                    role = r
                    break
        if not role:
            for cn, r in CERT.items():
                if cn in t:
                    role = r
                    break
        if not role and "组件" in t:
            for r in ("锋御", "命破", "强攻", "击破", "异常", "支援", "防护"):
                if r in t:
                    role = r
                    break
        if not attr and t.endswith("芯片"):
            for a, cn in CHIP_ATTR.items():
                # 芯片名里是「引燃/冰结/感电」这种，反查回属性
                if cn in t:
                    attr = a
                    break
        if role and attr:
            break

    return role, attr


def where_to_farm(mat: str, role: str = "", attr: str = "") -> dict | None:
    """材料名 → 副本信息。查不到返回 None。

    Returns {"副本": str, "类型": str, "每次电量": int, "每次产出": int, "周本": bool}
    """
    m = mat.strip()

    # ---------- 认证章（三档同名系）----------
    if "认证章" in m:
        return {"副本": "实战模拟室·代理人晋升", "类型": "认证章",
                "每次电量": RUN_BATTERY, "每次产出": PROD["认证章"], "周本": False}

    # ---------- 技能芯片 ----------
    if m.endswith("芯片"):
        return {"副本": "实战模拟室·代理人技能", "类型": "芯片",
                "每次电量": RUN_BATTERY, "每次产出": PROD["芯片"], "周本": False}

    # ---------- 音擎 ----------
    if ("组件" in m) or ("音擎" in m) or m.endswith("模块"):
        return {"副本": "实战模拟室·音擎改装", "类型": "音擎组件",
                "每次电量": RUN_BATTERY, "每次产出": PROD["音擎组件"], "周本": False}

    # ---------- 角色经验 ----------
    if "调查员记录" in m or "经验" in m:
        return {"副本": "实战模拟室·基础材料", "类型": "角色经验",
                "每次电量": RUN_BATTERY, "每次产出": PROD["角色经验"], "周本": False}

    # ---------- 镀剂 ----------
    if "镀剂" in m:
        return {"副本": "实战模拟室·基础材料", "类型": "镀剂",
                "每次电量": RUN_BATTERY, "每次产出": PROD["镀剂"], "周本": False}

    # ---------- 高维数据 / 专业挑战室 ----------
    if "高维数据" in m:
        return {"副本": "专业挑战室", "类型": "高维数据",
                "每次电量": 40, "每次产出": 5, "周本": False}

    # ---------- boss 材料（恶名狩猎）----------
    #
    # **踩过的坑**：`恶名狩猎_材料对照` 的结构是
    #     {boss: {"材料": "刻命残蜕", "类别": ..., "来源": ...}}
    # 我原来写 `if m in mats` —— mats 是 dict，`in` 查的是 key（"材料"/"类别"/"来源"），
    # **永远匹配不上 value**，所以「刻命残蜕」查不到。
    # 正确写法：`mats.get("材料") == m`。
    ddata = _load("dungeon_data.json")
    boss_map = (ddata.get("恶名狩猎_材料对照") or {})
    for boss, info in boss_map.items():
        if isinstance(info, dict) and info.get("材料") == m:
            return {"副本": f"恶名狩猎·{boss}", "类型": "boss材料",
                    "每次电量": 60, "每次产出": 2, "周本": True}

    # ---------- 驱动盘套装 ----------
    # 权威来源是 `disc_meta.json` 的「套装副本」（zzz_farm_plan 也用这张），
    # 不是 materials.json —— 我原来假设 materials.json 有「驱动盘.副本」，
    # **实际只有「盘」和「镀剂」两个 key，没有套装映射。**
    dmeta = _load("disc_meta.json")
    set_dungeon = (dmeta.get("套装副本") or {})
    if m in set_dungeon:
        return {"副本": f"区域巡防·{set_dungeon[m]}", "类型": "驱动盘",
                "每次电量": 60, "每次产出": 2, "周本": False}

    return None


def plan(agent: str) -> dict:
    """读游戏里的缺口 → 排副本 → 出计划。"""
    import zzz_guide
    from core import Vision, Input, Ui

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()

    role, attr = _agent_role_attr(agent)

    if not zzz_guide.open_guide(ui):
        return {"ok": False, "error": "到不了养成指南"}
    if not zzz_guide.switch_to_detail(ui):
        return {"ok": False, "error": "切不到养成材料明细"}

    # **滚动读全** —— 一屏只放 1~2 节，不滚就读不到技能芯片（属性也就推不出）
    detail = zzz_guide.read_detail_all(ui)
    got = detail.get("角色") or "?"

    # **优先用材料名反推定位/属性** —— 不依赖角色库
    _all_mats = []
    for _sec in detail.get("分节") or []:
        for _m in _sec.get("材料") or []:
            if _m.get("材料"):
                _all_mats.append(_m["材料"])
    _r2, _a2 = infer_role_attr(_all_mats)
    if _r2:
        role = _r2
    if _a2:
        attr = _a2

    rows = []
    for sec in detail.get("分节") or []:
        for m in sec.get("材料") or []:
            left = m.get("仍需")
            if not left:
                continue                      # 已满足，跳过
            name = m.get("材料") or ""
            w = where_to_farm(name, role, attr)
            if not w:
                rows.append({"材料": name, "仍需": left, "副本": "（查不到）",
                             "次数": 0, "电量": 0, "周本": False,
                             "节": sec.get("节", "")})
                continue
            runs = -(-left // max(1, w["每次产出"]))
            rows.append({
                "材料": name, "仍需": left, "副本": w["副本"],
                "类型": w["类型"], "次数": runs,
                "电量": runs * w["每次电量"], "周本": w["周本"],
                "节": sec.get("节", ""),
            })

    # 周本优先（次数有限），其次按电量从少到多
    rows.sort(key=lambda r: (not r["周本"], r["电量"]))

    return {
        "ok": True, "角色": got, "定位": role, "属性": attr,
        "分节": detail.get("分节") or [], "行": rows,
        "总电量": sum(r["电量"] for r in rows),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="通用养成链条：读游戏缺口 → 排副本 → 出计划")
    ap.add_argument("agent", help="角色名")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    d = plan(args.agent)
    if not d.get("ok"):
        print(f"✘ {d.get('error')}")
        return 4

    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0

    print(f"角色：{d['角色']}　定位 {d['定位'] or '?'}　属性 {d['属性'] or '?'}")
    print()

    # 先打缺口原文（官方数据）
    print("═══ 官方缺口（读自游戏，不是估算）═══")
    for sec in d["分节"]:
        ms = sec.get("材料") or []
        if not ms:
            continue
        print(f"\n【{sec['节']}】" + (f"  丁尼 {sec['丁尼']}" if sec.get("丁尼") else ""))
        for m in ms:
            print(f"  {m['材料']:<18}所需 {m.get('所需','?'):>6}"
                  f"　已有 {m.get('已有','?'):>6}　仍需 {m.get('仍需','?'):>6}")

    print()
    print("═══ 刷本计划（按材料类型推副本，不是按角色硬编码）═══")
    if not d["行"]:
        print("  缺口是空的 —— 这个角色已经养满了？")
        return 0
    print(f"  {'材料':<18}{'仍需':>6}  {'副本':<26}{'次数':>4}{'电量':>6}")
    for r in d["行"]:
        mark = "周" if r["周本"] else "  "
        print(f"  {r['材料']:<18}{r['仍需']:>6}  {r['副本']:<26}"
              f"{r['次数']:>4}{r['电量']:>6} {mark}")

    print()
    print(f"  合计电量 {d['总电量']}　按 240/轮算 {(d['总电量'] + 239) // 240} 轮")
    print()
    print("  「周」= 恶名狩猎，每周 3 次免费（免费时电量记 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
