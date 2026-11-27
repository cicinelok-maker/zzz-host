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
# **属性 → 芯片名，从 materials.json 读，不在这里复制一份。**
#
# 踩过：这里原来写死了一份（「电」还写成「感电」），
# 而 materials.json 里已经改成「电击」了 —— **两份表漂移，查出来的副本名就不对。**
# 现在统一以 materials.json 为唯一来源。
def _chip_attr_map() -> dict:
    try:
        import json as _j
        from pathlib import Path as _P
        m = _j.loads((_P(__file__).parent / "materials.json").read_text(encoding="utf-8"))
        return (m.get("技能芯片") or {}).get("属性名") or {}
    except Exception:
        return {"物理": "物理", "火": "引燃", "冰": "冰结", "电": "电击",
                "以太": "以太", "风": "风蚀", "流明": "流明"}


CHIP_ATTR = _chip_attr_map()


# 实战模拟室的电量/产出（每次刷本 = 5 卡）
# **从中心配置读，不再在工具里写死**（audit_self 规则 2 / BUG-043 的前置）
try:
    from core.disc_cfg import THRESHOLDS as _TH
    CARD_BATTERY = int(_TH.get("card_battery", 20))
except Exception:
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
        # **副本名带上属性** —— materials.json 里有模板
        # `实战模拟室·代理人技能（{属性}测试）`，属性要换成游戏里的芯片名
        # （电 → 电击 / 火 → 引燃 / 冰 → 冰结 …）
        _a = CHIP_ATTR.get(attr or "", attr or "")
        _d = ("实战模拟室·代理人技能（%s测试）" % _a) if _a else "实战模拟室·代理人技能"
        return {"副本": _d, "类型": "芯片",
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

    # **确认面板显示的是不是你要的角色，不是就切过去。**
    #
    # 养成指南有状态 —— 停在上一次选中的角色。不处理就会拿别人的缺口当你的，
    # 而且**完全不会报错**（用户会以为那就是自己的清单）。
    #
    # ## 之前为什么放弃了自动切
    #
    # 切完读不到名字，以为是切换失败。**实际是页面被滚走了** ——
    # 养命指南右侧是一个长页面，顶部角色牌滚出视野后 `current_agent()`
    # 会读到正文（实测返回 `'玩偶驻场时间较长'`）。
    #
    # 现在 `current_agent()` 会先滚回顶部再读，所以自动切可以恢复。
    _shown = zzz_guide.current_agent(ui)
    try:
        from core.agent_name import canonical_agent as _canon
        _want = _canon(agent)
        _got = _canon(_shown) if _shown else ""
    except Exception:
        _want, _got = agent, _shown or ""

    if _got and (_got == _want or _want in _got or _got in _want):
        print(f"  面板确认是「{_shown}」")
    else:
        print(f"  面板当前是「{_shown or '读不到'}」，切到「{agent}」")
        if not zzz_guide.select_agent(ui, agent):
            return {"ok": False,
                    "error": (f"切不到「{agent}」（面板停在「{_shown or '读不到'}」）。\n"
                              f"  养成指南只覆盖当期有攻略的角色（约 46 个），"
                              f"这个角色可能没有官方攻略。")}
        zzz_guide.switch_to_detail(ui)

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


def do_farm(rows: list[dict], max_elec: int = 240, run_it: bool = False) -> int:
    """按「次数」刷本，**刷够就停，不刷到没电**。

    rows 来自 `plan()` 的「行」：每行有 {材料, 副本, 次数, 电量, 周本}。

    电量预算：`max_elec` 是**这一轮最多花多少电**（默认 240 = 一次满电回满）。
    超出预算的条目**自动截断次数**，剩下的留给下一轮。
    """
    import json
    import subprocess
    import sys

    if not rows:
        print("没有缺口，不用刷")
        return 0

    print()
    print("╔" + "═" * 62 + "╗")
    print("║ 刷本执行" + " " * 53 + "║")
    print("╚" + "═" * 62 + "╝")

    left = max_elec
    todo = []
    for r in rows:
        if r.get("副本") in ("（查不到）", ""):
            continue
        runs = int(r.get("次数") or 0)
        per = 0 if r.get("周本") else (
            int(r["电量"]) // max(1, runs) if runs else 0)
        if runs <= 0:
            continue
        # 周本不吃电量（免费次数）
        if r.get("周本"):
            todo.append({**r, "本次刷": runs})
            continue
        afford = (left // per) if per else runs
        take = min(runs, afford)
        if take <= 0:
            continue
        todo.append({**r, "本次刷": take})
        left -= take * per

    if not todo:
        print("  电量预算内没有可刷的（或全是查不到副本的材料）")
        return 0

    total_elec = 0
    for t in todo:
        per = 0 if t.get("周本") else (
            int(t["电量"]) // max(1, int(t["次数"])) if t["次数"] else 0)
        total_elec += per * t["本次刷"]
        skip = "（原计划 %d 次，预算内先刷 %d 次）" % (t["次数"], t["本次刷"]) \
            if t["本次刷"] < t["次数"] else ""
        print(f"  {t['副本']:<28} 刷 {t['本次刷']} 次{skip}")

    print()
    print(f"  本轮电量 {total_elec}（上限 {max_elec}）")

    if not run_it:
        print()
        print("  这是计划。要真刷加 --run")
        return 0

    # ---------- 真刷 ----------
    # **走共享模块读**（RT-08）—— schema 只有一个来源。
    # 原来这里按 list 读，而 zzz_daily 按 dict 写，交叉跑就互相炸。
    from core import farm_log as _fl
    _n_today, _why = _fl.count_today_safe()
    if _why:
        print(f"  ⚠ {_why}")
        print(f"     **不知道今天刷过没** —— 自己看着办（可能重复刷）")
    elif _n_today > 0:
        print(f"  今天已经刷过 {_n_today} 次")

    ok_n = 0
    for t in todo:
        runs = int(t["本次刷"])
        if runs <= 0:
            continue
        # 拆成 od_material_farm 能吃的参数
        d = t["副本"]
        # **路由统一在 core/farm_cmd.py** —— 不再在这里内联一份
        from core.farm_cmd import farm_cmd
        cmd = farm_cmd(d, runs, run=True, python=sys.executable)

        print()
        print(f"  ▶ {' '.join(cmd[1:])}")
        r = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=36000)
        tail = (r.stdout or "").strip().splitlines()[-4:]
        for line in tail:
            print(f"    {line}")
        if r.returncode == 0:
            ok_n += 1
            _fl.append(dungeon=d, times=runs, ok=True, source="zzz_gap")
        else:
            print(f"    ✘ 返回 {r.returncode}")
            _fl.append(dungeon=d, times=runs, ok=False, source="zzz_gap")

    # 每条已经在循环里通过 _fl.append 原子写过了，这里不用再写整份
    print()
    print(f"  完成 {ok_n}/{len(todo)} 项，记账写入 {_fl.LOG.name}")
    return 0 if ok_n == len(todo) else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="通用养成链条：读游戏缺口 → 排副本 → 出计划")
    ap.add_argument("agent", help="角色名")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--run", action="store_true",
                    help="真刷（不加只出计划）")
    ap.add_argument("--max-elec", type=int, default=240,
                    help="本轮电量上限，默认 240（一次满电）。"
                         "超出自动截断次数，剩下的留给下一轮")
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
    return do_farm(d["行"], max_elec=args.max_elec, run_it=args.run)


if __name__ == "__main__":
    sys.exit(main())