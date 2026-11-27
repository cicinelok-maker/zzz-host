"""驱动盘读取器（数值校验版）。

## 和旧版的区别

旧版：OCR 出文字 → 按名字猜属性 → 百分比被当成平A
新版：OCR 出「名字 + 数值」→ **用数值反推属性名和升级次数** → 再用名字消歧

数值是固定值不随机，所以能精确反推：
    38  →  攻击力 ×2
    6%  →  攻击力百分比 ×2 或 生命值百分比 ×2
    9   →  异常精通 ×1 或 穿透值 ×1

## 输出

每块盘一条：
    {"set","slot","level","main","subs":[{"name","value","pct","rolls"}],
     "eff_rolls","problems"}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))
from core.game_cfg import DEFAULT_AGENT as _DEFAULT_AGENT

from core import Vision,Input,Ui,Journal# noqa: E402
from core.machine import Machine# noqa: E402
from pick_agent import select_agent# noqa: E402

R_DET = (1400, 180, 1910, 960)
R_SUBS = (1420, 510, 1900, 810)


def main() -> int:
    ap = argparse.ArgumentParser()
    # **默认角色只有一个真相**：`core.game_cfg.DEFAULT_AGENT`（E16）。
    # 写死作者自己的角色名，朋友的机器上会去操作一个不存在的角色。
    ap.add_argument("agent", nargs="?", default=_DEFAULT_AGENT)
    ap.add_argument("--out", default=str(BASE / "od_test" / "discs_v2.json"))
    args = ap.parse_args()

    # 统一走 core.agent_cfg：角色没专门配置时用职业模板回退
    from core.agent_cfg import cfg_of
    cfg = cfg_of(args.agent, warn=True)
    good = set(cfg["有效副词条"])
    half = set(cfg["次选副词条"])

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)
    log = Journal("读盘v2")

    if not select_agent(ui, m, args.agent):
        print(f"选不中 {args.agent}")
        return 3

    from zzz_equip import open_custom, list_discs

    out = []
    for slot in range(1, 7):
        if not m.go_to("装备页"):
            print(f"{slot} 号位：到不了装备页")
            continue
        if not open_custom(ui, m, slot, require_equipped=False):
            print(f"{slot} 号位：进不去定制页")
            continue
        from zzz_disc_train import read_disc, evaluate
        GRID = (60, 120, 1000, 980)
        CX = GRID[0] + (GRID[2] - GRID[0]) // 2
        CY = GRID[1] + (GRID[3] - GRID[1]) // 2

        # 滚回顶部
        for _ in range(24):
            inp.move(CX, CY)
            inp.wheel(3, wait=0.1)
        inp.move(CX, CY)
        inp.wheel(-1, wait=0.3)
        vs.frame(force=True)

        def fingerprint(dd):
            """去重指纹。

            ## **必须带 `slot` 和 `main`**（BUG-080）

            原来只有 `set + level + subs` —— 于是下面这两种盘会被当成同一块：

            · 同套装、同等级、副词条一样，但**主属性不同**
              （「攻击力」vs「暴击率」）
            · 同套装、同等级，但**位号不同**（1号位 vs 2号位）

            第二块盘会被 `if fp in seen_fp: continue` **直接跳过**，
            于是 `discs_v2.json` 里少一块 —— 而这是判盘和换装的输入。

            实测这类「看起来一样」的盘在扫仓库时很常见（同一套刷出来一堆）。
            """
            return (dd.get("slot"), dd["set"], dd.get("main"), dd["level"],
                    tuple(sorted((sub["name"], sub["rolls"])
                                 for sub in dd.get("subs") or [])))

        seen_fp = set()
        got = 0
        idle = 0
        for page in range(30):
            vs.frame(force=True)
            discs = list_discs(ui)
            new_this_page = 0
            for d in discs:
                inp.click(d["cx"], d["cy"] - 42, wait=0.95)
                vs.frame(force=True)
                dd = read_disc(vs)
                if not dd["set"]:
                    continue
                fp = fingerprint(dd)
                if fp in seen_fp:
                    continue
                seen_fp.add(fp)
                ev = evaluate(dd, good, half)
                # 补齐下游依赖的字段（subs 结构化 + main/main_raw）
                # 注意：discs_v2.json 是公共接口，字段不能随便改，
                # 改了要同步 check_target_28 / show_discs_v2 / explain_crit。
                subs_struct = []
                for (nm, val) in dd.get("subs_raw") or []:
                    import re as _re
                    mm = _re.search(r"\+(\d+)", nm)
                    rolls = int(mm.group(1)) if mm else 0
                    bare = _re.sub(r"\+\d+", "", nm).strip()
                    subs_struct.append({"name": bare, "value": val, "rolls": rolls})
                # 主属性：用 zzz_status 里验证过的方法
                # 详情区文字用 | 分隔，「主属性」和「副属性」之间那段就是主属性
                from core import vocab as _vb
                main_txt = ""
                full = vs.text((0, 0, 1920, 1080))
                if "主属性" in full:
                    seg2 = full.split("主属性", 1)[1].split("副属性", 1)[0]
                    for part in seg2.split("|"):
                        q = part.strip()
                        # **同时查 STATS_MAIN_EXTRA**（RT-15）——
                        # 「以太属性伤害加成」这种写法在 STATS 里没有。
                        if any(q.startswith(k) for k in
                               list(_vb.STATS) + list(_vb.STATS_MAIN_EXTRA)):
                            main_txt = q
                            break
                main_raw = ""
                nums = re.findall(r"[\d.]+%?", main_txt)
                if nums:
                    main_raw = nums[-1]
                out.append({**dd, "subs": subs_struct,
                            "main": main_txt, "main_raw": main_raw,
                            "eff_rolls": ev["eff"]})
                got += 1
                new_this_page += 1
            if new_this_page == 0:
                idle += 1
                if idle >= 3:
                    break
            else:
                idle = 0
            inp.move(CX, CY)
            inp.wheel(-2, wait=0.5)
        print(f"{slot} 号位：读到 {got} 块（{page + 1} 屏）")

    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n共 {len(out)} 块，已写入 {args.out}")
    from collections import Counter
    c = Counter(x["slot"] for x in out)
    print("每号位：" + "  ".join(f"{k}:{v}" for k, v in sorted(c.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())