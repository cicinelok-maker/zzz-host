"""驱动盘训练循环：升级 → 读词条 → 判断留/弃。

## 这是闭环的核心缺口

之前会：刷盘 → 识别 → 筛选 → 弃置拆解
缺的是：**升级一块盘 → 读它升出了什么 → 决定继续升还是弃置**

## 机制

一块 S 盘 Lv0 有 3-4 条副词条，全是 +0。
升级到 Lv3/6/9/12/15 各触发一次随机强化（落在 4 条里随机一条）。
所以：

    Lv0  → 0 次强化
    Lv15 → 5 次强化（如果起始 4 条）

每条副词条显示 `+N`，N 就是它被强化了几次。
有效词条数 = 落在 攻击力百分比/暴击率/暴击伤害 上的 N 之和。

**你无法控制强化落到哪**，所以流程是：
    升到满级 → 看结果 → 命中多就留，命中少就弃

## 中途止损

理论上可以边升边看：
    Lv3 出第一次 → 没中 → 还有 4 次机会，继续
    Lv9 出第三次 → 还没中 → 剩 2 次，大概率废了，可以停

但这需要「升 3 级 → 读一次」，比直接升满慢。
按需选择。

## 用法

    python tools/zzz_disc_train.py 佩洛伊斯              # 只报当前哪些能升
    python tools/zzz_disc_train.py 佩洛伊斯 --train      # 真升级并判定
    python tools/zzz_disc_train.py 佩洛伊斯 --train --stop-early  # 边升边判
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision,Input,Ui,Journal# noqa: E402
from core import disc_stats as ds# noqa: E402
from core.disc_cfg import THRESHOLDS as _TH# noqa: E402
from core.machine import Machine# noqa: E402
from pick_agent import select_agent# noqa: E402

from core.paths import one_dragon_python,one_dragon_env
PY = one_dragon_python()
ENV = one_dragon_env()
R_DET = (1400, 180, 1910, 960)
R_SUBS = (1420, 510, 1900, 810)

# 判定阈值
KEEP_MIN = _TH["keep"]   # 统一从 core.disc_cfg 取，别再写死

# 每位号的初始副词条条数（升级前记录，升级后会被第4条污染）
_INIT_SUBS = {}


def read_disc(vs: Vision) -> dict:
    # 定制页的详情区位置和仓库不同（在左中），所以直接读全屏按关键词解析。
    # 全屏文字顺序是可靠的：... 拂晓行纪[1] | 等级15/15 | 主属性 | 生命值 | 2200
    #   | 副属性 | 攻击力+2 | 9% | ... | 套装效果 | ...
    det = vs.text((0, 0, 1920, 1080))
    raw = det
    m = re.search(r"([\u4e00-\u9fa5]{2,6})\[(\d)\]", det)
    setname = m.group(1) if m else ""
    slot = int(m.group(2)) if m else 0
    ml = re.search(r"等级\s*(\d+)\s*/\s*(\d+)", det)
    level = int(ml.group(1)) if ml else 0
    cap = int(ml.group(2)) if ml else 15

    src = raw if "副属性" in raw else det
    subs = []
    if "副属性" in src:
        seg = src.split("副属性", 1)[1]
        seg = re.split(r"套装效果|套装|查看", seg)[0]
        parts = [p.strip() for p in seg.split("|") if p.strip()]
        i = 0
        while i < len(parts):
            nm = parts[i]
            if i + 1 < len(parts) and re.fullmatch(r"[+\-]?\d+(?:\.\d+)?%?", parts[i + 1]):
                subs.append((nm, parts[i + 1]))
                i += 2
            else:
                mm = re.match(r"(.+?)\s*([+\-]?\d+(?:\.\d+)?%?)$", nm)
                if mm and not re.fullmatch(r"[+\-]?\d+(?:\.\d+)?%?", nm):
                    subs.append((mm.group(1).strip(), mm.group(2)))
                i += 1
    # 全屏解析会把左边盘列表的「等级N」也带进来，按已知属性名过滤
    from core import vocab as _vb
    clean = []
    for nm, val in subs:
        bare = re.sub(r"\+\d+", "", nm).strip()
        if not bare:
            continue
        if _vb.stat_name_of(bare) not in _vb.STATS:
            continue
        clean.append((nm, val))
    # 套装名繁简归一：OCR 有时读「自由藍调」有时读「自由蓝调」，
    # 不归一的话同一套装会被当成两个，破坏 4+2 计数和匹配。
    # 主属性。
    # OCR 原文长这样（中间隔着 4 个其它盘片的等级标签）：
    #   ... | 等级0/15 | 主属性 | 等级0 | 等级0 | 等级0 | 等级0 | 火属性伤害加成 | 7.5% | DRIVER | 副属性 | ...
    # 所以不能直接跟在「主属性」后面取，要先切断区间再过滤噪声。
    main = ""
    if "主属性" in det:
        _seg = det.split("主属性", 1)[1]
        _seg = re.split(r"副属性|套装效果", _seg)[0]
        _parts = [x.strip() for x in _seg.split("|") if x.strip()]
        _cands = [x for x in _parts
                  if not x.startswith("等级")
                  and x not in ("DRIVER", "DEMO", "S", "R", "O")
                  and not re.match(r"^[\d.]+%?\$", x)]
        if _cands:
            main = _cands[0]
    from core.zh import canonical_set
    return {"set": canonical_set(setname), "slot": slot, "level": level,
            "cap": cap, "main": main, "subs_raw": clean}


def evaluate(d: dict, good: set, half: set) -> dict:
    eff = 0.0
    rows = []
    for nm, val in d["subs_raw"]:
        pv = ds.parse_value(val)
        if not pv:
            continue
        num, pct = pv
        name, rolls = ds.resolve(nm, num, pct)
        if name == "?":
            continue
        w = ds.is_effective(name, good, half)
        eff += (1 + rolls) * w
        rows.append({"name": name, "value": num, "pct": pct,
                     "rolls": rolls, "weight": w})
    return {"eff": round(eff, 1), "subs": rows}


def upgrade_disc(slot: int, agent: str) -> tuple[bool, str]:
    """调 zzz_equip upgrade 升级指定位号"""
    env = dict(os.environ)
    # BUG-069：ENV_EXTRA 从来没定义过 —— NameError，训练第一步就崩。
    # 应该用 OneDragon 提供的环境变量（PYTHONPATH 等）。
    from core.paths import one_dragon_env
    env.update(one_dragon_env())
    cmd = [PY, "-u", str(HERE / "zzz_equip.py"), "upgrade",
           "--slot", str(slot), "--agent", agent]
    try:
        r = subprocess.run(cmd, cwd=str(BASE), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=1800)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return False, "超时"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", nargs="?", default="佩洛伊斯")
    ap.add_argument("--train", action="store_true", help="真升级")
    ap.add_argument("--no-stop-loss", action="store_true",
                    help="关掉止损，一路升到满级")
    ap.add_argument("--slots", default="", help="只处理这些位号，如 2,3,4")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多处理几块盘（0 = 不限制）。按位号顺序，不是按潜力排")
    ap.add_argument("--max-steps", type=int, default=6, help="每个位号最多升几次")
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
    log = Journal(f"训盘_{args.agent}")

    if not select_agent(ui, m, args.agent):
        print("选不中")
        return 3
    if not m.go_to("装备页"):
        print("到不了装备页")
        return 4

    targets = [int(x) for x in args.slots.split(",") if x.strip()] or list(range(1, 7))
    report = []

    # **真的限制块数**（BUG-057）。
    #
    # 原来 `zzz_disc_daily --train-n N` 只改了一句提示文案，
    # 实际调用是 `zzz_disc_train.py --train --max-steps 6` ——
    # **一个块数参数都没传**，所以 N 改多少都是训练全部位号。
    #
    # 现在有了 `--limit`：数到 N 块就停（跳过「进不去/读不到」的）。
    _done = 0
    for slot in targets:
        if args.limit and _done >= args.limit:
            print(f"  已达上限 {args.limit} 块，停止")
            break
        vs.frame(force=True)
        # 打开定制页读当前盘
        from zzz_equip import open_custom
        if not open_custom(ui, m, slot):
            report.append(f"{slot}号位：进不去")
            continue
        vs.frame(force=True)
        d = read_disc(vs)
        if not d["set"]:
            report.append(f"{slot}号位：读不到")
            continue
        ev = evaluate(d, good, half)
        line = (f"{slot}号位 {d['set']} Lv{d['level']}/{d['cap']} "
                f"有效 {ev['eff']}")
        subs_str = " ".join(f"{s['name']}+{s['rolls']}" for s in ev["subs"])
        print(line)
        print(f"   {subs_str}")

        # ---- 初始判定：升级前先看主词条 + 初始副词条 ----
        # 用户 2026-11-25：「先判断主词条是否正确，再看初始副词条是否全部命中，
        #                   再决定升级」
        _iv = None
        if d["level"] == 0:
            from core.disc_main import verdict as _mv
            from core.disc_initial import judge_disc, report as _irep
            # verdict(main, slot, want: dict, element) —— want 是整个主词条表
            _want_all = cfg.get("主词条") or {}
            _mk, _mnote = _mv(d.get("main") or "", slot, _want_all,
                              cfg.get("属性") or "")
            _iv = judge_disc(d["subs_raw"], good, half,
                             main_ok=(_mk != "bad"),
                             main_is_rare=("暴击率" in
                                           ((_want_all.get(str(slot)) or []))))
            print(f"   初始判定：{_irep(_iv)}")
            print(f"      主词条 {d.get('main', '?')}：{_mnote}")
            if _iv["action"] == "drop":
                report.append(f"{slot}号位 {d['set']} 初始{_iv['hits']}/"
                              f"{_iv['total']} 丢（不升，省镀剂）")
                print(f"   → 不升（省镀剂）")
                continue

        if d["level"] >= d["cap"]:
            verdict = "已满级·" + ("留" if ev["eff"] >= KEEP_MIN else "可弃")
            print(f"   → {verdict}")
            report.append(f"{slot}号位 {d['set']} Lv{d['level']} 有效{ev['eff']} {verdict}")
            continue

        if not args.train:
            print("   → 可升（未执行）")
            report.append(f"{slot}号位 {d['set']} Lv{d['level']} 有效{ev['eff']} 可升")
            continue

        # 真升级
        # 记下**初始**副词条条数（升级后 3 条的会变成 4 条，不能那时再数）
        _INIT_SUBS[slot] = len(d["subs_raw"])
        _done += 1          # 这一块真的要训练了，计入 --limit
        steps = 0
        while d["level"] < d["cap"] and steps < args.max_steps:
            ok, out = upgrade_disc(slot, args.agent)
            steps += 1
            if not ok:
                print(f"   升级失败：{out.strip().splitlines()[-1][:60] if out.strip() else '?'}")
                break
            # 重新读
            if not m.go_to("装备页"):
                break
            if not open_custom(ui, m, slot):
                break
            vs.frame(force=True)
            d = read_disc(vs)
            ev = evaluate(d, good, half)
            subs_str = " ".join(f"{s['name']}+{s['rolls']}" for s in ev["subs"])
            print(f"   升到 Lv{d['level']} → 有效 {ev['eff']}　{subs_str}")

            # 止损：每个节点判一次要不要继续
            if not args.no_stop_loss:
                from core.disc_stoploss import should_stop, report as _srep
                _n_eff = sum(1 for x in ev["subs"] if x.get("weight", 0) >= 1.0)
                _init_n = _INIT_SUBS.get(slot, len(d["subs_raw"]))
                _v = should_stop(ev["eff"], _n_eff, _init_n, d["level"],
                                 keep_line=KEEP_MIN)
                print(f"     {_srep(_v)}")
                if _v["stop"] and d["level"] < d["cap"]:
                    print(f"   → 提前停（省镀剂），当前有效 {ev['eff']}")
                    break

            if d["level"] >= d["cap"]:
                break

        verdict = "留" if ev["eff"] >= KEEP_MIN else "可弃"
        print(f"   → 最终 Lv{d['level']} 有效 {ev['eff']}　{verdict}")
        report.append(f"{slot}号位 {d['set']} Lv{d['level']} 有效{ev['eff']} {verdict}")
        log.log(f"{slot}号位", "训练", ok=True,
                detail=f"Lv{d['level']} 有效{ev['eff']}")

    print()
    print("=== 汇总 ===")
    for r in report:
        print("  " + r)
    print()
    print(log.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())