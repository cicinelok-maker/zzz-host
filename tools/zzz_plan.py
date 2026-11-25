"""驱动盘决策器：按 4+2 套装组合选最优盘。

## 4+2 是什么意思

绝区零的套装效果：
    4 件套 = 给 4 个位号装同一套装 → 激活 4 件套效果
    2 件套 = 另外 2 个位号装另一套装 → 激活 2 件套效果

所以 6 个位号的正确构成是 **4 件主套装 + 2 件副套装**，不是 6 件同套装。

## 决策逻辑

    1. 主套装 = disc_meta 的「四件套」
       副套装 = 「二件套候选」里挑一个
    2. 每个位号的候选盘 = 主套装的盘 ∪ 副套装的盘（同位号）
    3. 求一个 4+2 的分配，使总有效词条最大：
       · 先假设 6 个位号都装主套装
       · 主套装数量 > 4 时，挑「换成副套装收益最大」的位号换掉，
         直到主套装恰好 4 个
    4. 和当前装备比，逐位号决定换不换

## 用法

    python tools/zzz_plan.py 佩洛伊斯              # 只出计划
    python tools/zzz_plan.py 佩洛伊斯 --apply      # 真换装
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision,Input,Ui,Journal# noqa: E402
from core.machine import Machine# noqa: E402
from pick_agent import select_agent# noqa: E402
from zzz_equip import open_custom,list_discs,R_DETAIL# noqa: E402

R_BOTTOM = (0, 900, 1920, 1080)


def rolls(sub: str) -> int:
    # 游戏显示 +N = 升级次数。
    # 有效权重 = 1（本身存在）+ N（升过几次）
    m = re.search(r"\+(\d+)", sub)
    return 1 + (int(m.group(1)) if m else 0)


def stat_of(sub: str) -> str:
    m = re.match(r"\s*([^\s+]+)", sub)
    return m.group(1) if m else ""


def eff_of(detail_text: str, good, half) -> tuple[float, list[str]]:
    """算有效值。**统一走 core.disc_cfg**，保证和 zzz_status 完全一致。

    2026-11-24 统一：以前这里用自己的 stat_of/rolls：
      · 没做百分比归名（攻击力+2 9% 被当平A，减半算）
      · rolls() 没 +N 时返回 1，口径B 下重复计数
    结果同一块盘比 zzz_status 少 1~2 条。现在只保留这一条路径。
    """
    from core.disc_cfg import parse_full_screen, effective
    d = parse_full_screen(detail_text)
    eff, rows = effective(d["subs_raw"], good, half)
    detail = [f"{r['name']}+{r['rolls']}" for r in rows]
    return eff, detail


def set_name_of(detail: str, known: set[str]) -> str:
    for s in known:
        if s in detail:
            return s
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--eff-loss-limit", type=float, default=1.5,
                    help="为了凑套装，最多接受掉多少有效值（默认 1.5）")
    ap.add_argument("--secondary", default="", help="指定副套装（否则用 disc_meta 的第一个候选）")
    ap.add_argument("--out", default=str(BASE / "state" / "plan.json"))
    args = ap.parse_args()

    # 统一走 core.agent_cfg：角色没专门配置时用职业模板回退
    from core.agent_cfg import cfg_of
    cfg = cfg_of(args.agent, warn=True)
    if not cfg:
        print(f"{args.agent} 不在 disc_meta.json")
        return 2
    main_set = cfg["四件套"]
    sec_cands = cfg.get("两件套候选") or cfg.get("二件套候选") or []
    sec_set = args.secondary or (sec_cands[0] if sec_cands else "")
    good = set(cfg["有效副词条"])
    half = set(cfg.get("次选副词条") or [])
    known_sets = {main_set} | set(sec_cands) | {args.secondary} - {""}

    print(f"目标：{args.agent}")
    print(f"  4件套：{main_set}")
    print(f"  2件套：{sec_set or '（未配置）'}"
          + (f"　候选：{sec_cands}" if len(sec_cands) > 1 else ""))
    print(f"  有效词条：{sorted(good)}")

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    log = Journal(f"决策_{args.agent}")
    ui.start()
    m = Machine(ui, verbose=False)

    if not select_agent(ui, m, args.agent):
        print("选不中角色")
        return 3

    # 逐位号收集：当前装备 + 主/副套装候选
    slots = {}
    for slot in range(1, 7):
        if not open_custom(ui, m, slot):
            print(f"  {slot} 号位：进不去（可能空位）")
            slots[slot] = {"cur": None, "main": [], "sec": []}
            continue
        vs.frame(force=True)
        # 定制页详情在左中，用全屏更稳（和 zzz_disc_train 一致）
        cur_detail = vs.text((0, 0, 1920, 1080))
        cur_set = set_name_of(cur_detail, known_sets)
        cur_eff, _ = eff_of(cur_detail, good, half)
        cur = {"set": cur_set, "eff": cur_eff,
               "level": (re.search(r"等级(\d+)/15", cur_detail) or [None, "?"])[1]}

        mlist, slist = [], []
        for d in sorted(list_discs(ui), key=lambda x: -x["level"]):
            inp.click(d["cx"], d["cy"] - 42, wait=1.2)
            vs.frame(force=True)
            det = vs.text((0, 0, 1920, 1080))
            s = set_name_of(det, known_sets)
            if not s:
                continue
            e, detail = eff_of(det, good, half)
            # 主词条校验：主词条错的盘，副词条再好也不换上去
            # 2026-11-25 实测：没这道检查时把「主:暴击率」换成了「主:防御力」
            from core.disc_main import verdict as _mv
            from core import vocab
            from core.game_cfg import element_of as _eo
            _main_txt = ""
            if "主属性" in det:
                _seg = det.split("主属性", 1)[1].split("副属性", 1)[0]
                for _part in _seg.split("|"):
                    _q = _part.strip()
                    if any(_q.startswith(k) for k in vocab.STATS):
                        _main_txt = _q
                        break
            _mvd, _ = _mv(_main_txt, slot, (cfg.get("主词条") or {}),
                          _eo(args.agent))
            if _mvd == "bad":
                continue
            item = {"level": d["level"], "eff": e, "detail": detail,
                    "cx": d["cx"], "cy": d["cy"], "set": s,
                    "main": _main_txt, "main_verdict": _mvd}
            if s == main_set:
                mlist.append(item)
            elif s == sec_set:
                slist.append(item)
        slots[slot] = {"cur": cur, "main": mlist, "sec": slist}

    # ---- 求最优 4+2 分配 ----
    best_main = {s: (max(v["main"], key=lambda x: x["eff"]) if v["main"] else None)
                 for s, v in slots.items()}
    best_sec = {s: (max(v["sec"], key=lambda x: x["eff"]) if v["sec"] else None)
                for s, v in slots.items()}

    print("\n各位号候选：")
    for s in range(1, 7):
        bm, bs = best_main[s], best_sec[s]
        print(f"  {s} 号位　主套最好 "
              f"{bm['eff']:.1f}" if bm else f"  {s} 号位　主套 无", end="")
        print(f"　副套最好 {bs['eff']:.1f}" if bs else "　副套 无")

    # 初始：全部用主套装；主套不足 4 的位号，用副套装补
    assign = {}
    for s in range(1, 7):
        if best_main[s]:
            assign[s] = ("main", best_main[s])
        elif best_sec[s]:
            assign[s] = ("sec", best_sec[s])

    main_count = sum(1 for k, _ in assign.values() if k == "main")
    # 主套超过 4，挑「换副套收益最大」的换
    while main_count > 4:
        cands = [(s, best_sec[s]["eff"] - best_main[s]["eff"])
                 for s in assign
                 if assign[s][0] == "main" and best_sec[s]]
        if not cands:
            break
        s, gain = max(cands, key=lambda x: x[1])
        # 4+2 必须强制：主套只能 4 件，多出来的必须换副套
        # 即使副套词条更差也要换——因为 2 件套效果的价值补偿得回来
        assign[s] = ("sec", best_sec[s])
        main_count -= 1

    # 主套不足 4，看能不能从副套换回主套
    while main_count < 4:
        cands = [(s, best_main[s]["eff"] - best_sec[s]["eff"])
                 for s in assign
                 if assign[s][0] == "sec" and best_main[s]]
        if not cands:
            break
        s, gain = max(cands, key=lambda x: x[1])
        assign[s] = ("main", best_main[s])
        main_count += 1

    print(f"\n最优分配：主套 {main_count} 件 + 副套 {6 - main_count} 件")

    # 真实当前构成（区分「副套 2 件」和「空位 2 个」）
    cur_main = sum(1 for s, v in slots.items()
                   if (v["cur"] or {}).get("set") == main_set)
    cur_sec = sum(1 for s, v in slots.items()
                  if sec_set and (v["cur"] or {}).get("set") == sec_set)
    cur_empty = sum(1 for s, v in slots.items() if not (v["cur"] or {}).get("set"))
    print(f"当前实际：主套 {cur_main} 件　副套 {cur_sec} 件　空位 {cur_empty} 个")
    if cur_main < 4:
        print(f"  ⚠ 主套不足 4 件，4 件套效果没激活")
    if cur_sec < 2:
        print(f"  ⚠ 副套不足 2 件，2 件套效果没激活")
        if cur_empty >= 2:
            print(f"  → 需要先补齐 {cur_empty} 个空位（定向调律或找盘）")

    eff_loss_limit = args.eff_loss_limit
    plan = []
    for s in range(1, 7):
        kind, item = assign.get(s, (None, None))
        if not item:
            print(f"  {s} 号位：无可用盘")
            plan.append({"slot": s, "action": "none", "reason": "无可用盘"})
            continue
        cur_eff = (slots[s]["cur"] or {}).get("eff", 0)
        cur_set = (slots[s]["cur"] or {}).get("set", "")
        cur_lv = (slots[s]["cur"] or {}).get("level", 0)
        # 换装判断要看两件事：
        #   1) 有效值变了没有
        #   2) 套装构成变了没有（4+2 的套装效果不算进 eff，但价值真实）
        #
        # **但「套装变了就换」是个无上限的开关。** 2026-11-25 实跑：
        # 为了凑 4+2，4 号位从 eff 4.0 换成 1.5（掉 2.5），6 号位掉 1.0，
        # 总分 24.0 → 20.5。套装加成补不回这些。
        # → 加一个「为了套装最多让步多少」的上限。
        eff_better = item["eff"] > cur_eff
        eff_drop = cur_eff - item["eff"]
        set_diff = item["set"] != cur_set

        if eff_better:
            need = True
        elif set_diff and eff_drop <= eff_loss_limit:
            need = True
        else:
            need = False

        why = []
        if eff_better:
            why.append(f"有效 {cur_eff:.1f}→{item['eff']:.1f}")
        if set_diff:
            if need and not eff_better:
                why.append(f"为套装让步 -{eff_drop:.1f}")
            elif not need:
                why.append(f"套装 {cur_set or '空'}→{item['set']} "
                           f"但要掉 {eff_drop:.1f}（超上限 {eff_loss_limit}）")
            else:
                why.append(f"套装 {cur_set or '空'}→{item['set']}")
        tag = (" → 换（" + "；".join(why) + "）") if need else " → 不换"
        if not need and not why:
            why.append("有效值和套装都没变好")
        print(f"  {s} 号位：{item['set']} Lv{item['level']} 有效 {item['eff']:.1f}"
              f"（当前 {cur_set or '空'} Lv{cur_lv} 有效 {cur_eff:.1f}）{tag}")
        plan.append({"slot": s, "set": item["set"], "level": item["level"],
                     "eff": item["eff"], "cur_eff": cur_eff,
                     "xy": [item["cx"], item["cy"]], "detail": item["detail"],
                     "action": "equip" if need else "keep"})

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"agent": args.agent, "main_set": main_set, "sec_set": sec_set,
         "main_count": main_count, "plan": plan}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n计划已写入 {args.out}")

    todo = [p for p in plan if p.get("action") == "equip"]
    if not todo:
        print("没有需要换装的位号")
        return 0
    print(f"需要换装 {len(todo)} 个位号")
    if not args.apply:
        print("（只出计划。加 --apply 才真换）")
        return 0

    for p in todo:
        slot = p["slot"]
        if not open_custom(ui, m, slot):
            continue
        vs.frame(force=True)
        x, y = p["xy"]
        inp.click(x, y - 42, wait=1.6)
        vs.frame(force=True)
        det = vs.text(R_DETAIL)
        if p["set"] not in det:
            print(f"  {slot} 号位：点开的不是 {p['set']}，跳过（防误装）")
            log.log(f"{slot}号位", "跳过", ok=False, detail="套装不匹配")
            continue
        btn = vs.find("替换", R_BOTTOM)
        if not btn:
            print(f"  {slot} 号位：没有「替换」")
            continue
        inp.click(btn["cx"], btn["cy"], wait=2.2)
        vs.frame(force=True)
        c = vs.find("确认", (600, 600, 1400, 900))
        if c:
            inp.click(c["cx"], c["cy"], wait=2.0)
        print(f"  ✔ {slot} 号位已换装（{p['set']}）")
        log.log(f"{slot}号位", "换装", ok=True,
                detail=f"{p['cur_eff']}→{p['eff']}")

    print()
    print(log.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())