"""驱动盘全自动循环：升级 → 判定 → 标记弃置 → 拆解。

## 用户要求

「能不能你升级完，判定是废盘或者垃圾之后，你就自己拉去拆解？」

## 完整链路

```
1. 升级        zzz_equip.py upgrade（装到位号上直接升）
2. 读词条      zzz_disc_train.read_disc（全屏解析 + 属性名过滤）
3. 判定        口径B：有效 = Σ(1 + 升级次数) × 权重
                有效 < 阈值 → 废盘
4. 换下        装一块替代盘（或留空）
5. 标记弃置    拆解页选中该盘 → 按 R → 弹「是否将此驱动盘标记为弃置状态？」→ 确认
6. 拆解        快速选择 → 全选已弃置 → 确认 → 拆解 → 确认
```

## 关键的 R 键

实测（2026-11-24）：
```
拆解页选中一张盘 → 按 R
弹窗：是否将此驱动盘标记为弃置状态？
     弃置状态的驱动盘仍需手动拆解。锁定驱动盘时，会移除驱动盘的弃置状态。
按钮：取消@(826,680)　确认@(1128,679)
```

这是**唯一可用的逐盘标记方式**。仓库底部的弃置按钮是灰的，智能弃置只能批量。

## 用法

    python tools/zzz_disc_cycle.py 佩洛伊斯                  # 只看哪些该废
    python tools/zzz_disc_cycle.py 佩洛伊斯 --train          # 升级并判定
    python tools/zzz_disc_cycle.py 佩洛伊斯 --train --recycle # 升级+判定+标记+拆解
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
from core.disc_cfg import THRESHOLDS as _TH# noqa: E402
from pick_agent import select_agent# noqa: E402

# 实测坐标
XY_DISMANTLE_ENTRY = (365, 930)
XY_FUNNEL = (84, 1031)
XY_ABANDONED = (1425, 441)
XY_DLG_CONFIRM = (1128, 679)      # 「是否标记为弃置」的确认
XY_DISMANTLE_BTN = (1716, 900)
XY_FINAL_CONFIRM = (1107, 644)    # 「选中的驱动盘稀有度包含S级」的确认
R_TOP = (0, 0, 1200, 120)

# 判定阈值（口径B：存在+升级）
# 参考实测分布：满级盘 1.0~6.5，中位约 3
KEEP_MIN = _TH["keep"]
JUNK_MAX = _TH["junk"]
# 3~5 之间算过渡，留着但继续找更好的


def mesh(vs) -> int:
    return len([it for it in vs.items((60, 120, 1100, 980))
                if it["text"].startswith("等级")])


def top_count(vs) -> int:
    m = re.search(r"(\d+)\s*/\s*300", vs.text(R_TOP))
    return int(m.group(1)) if m else -1


def sort_by_level(ui: Ui) -> bool:
    """拆解页筛选面板：排序字段切到「等级」，圆形键点一次 = 最高→最低。

    实测坐标（2026-11-24）：
        漏斗按钮        (84,1031)
        顶部排序下拉     (1362,164)   当前显示「稀有度」
        下拉里的「等级」  (1341,307)
        圆形方向键       (1810,162)   点一次 高→低，点两次 低→高
    """
    vs, inp = ui.vs, ui.inp
    inp.click(XY_FUNNEL[0], XY_FUNNEL[1], wait=2.4)
    vs.frame(force=True)
    if "驱动盘筛选" not in vs.debug_text():
        return False
    dd = vs.find("稀有度", (1150, 100, 1920, 220))
    if not dd:
        return False
    inp.click(dd["cx"], dd["cy"], wait=1.8)
    vs.frame(force=True)
    lv = vs.find("等级", (1250, 250, 1700, 380))
    if not lv:
        return False
    inp.click(lv["cx"], lv["cy"], wait=2.0)
    vs.frame(force=True)
    # 圆形方向键：只点一次（高→低）
    inp.click(1810, 162, wait=1.8)
    vs.frame(force=True)
    inp.key("esc", wait=1.8)
    vs.frame(force=True)
    return True


def _level_label(text: str, level: int) -> bool:
    """卡片标签里的等级是否**正好**是 level。

    BUG-002：`"等级10".startswith("等级1")` 为真，
    所以前缀匹配会在 level=1 时把 Lv10~15 的卡片也捞进来。

    这里要求 `等级{N}` 后面**不能紧跟数字** —— `等级10` 不会匹配 `等级1`。
    """
    import re
    return re.search(rf"等级{level}(?!\d)", text or "") is not None


def mark_disc_abandoned(ui: Ui, m: Machine, slot: int, set_name: str,
                        level: int, want_main: str = "") -> bool:
    """在拆解页找到指定盘，按 R 标记弃置。

    做法：进拆解页 → 取消所有筛选 → 逐张点开读 → 匹配 套装+位号+等级 → 按 R → 确认
    """
    vs, inp = ui.vs, ui.inp
    if not m.go_to("驱动盘拆解页"):
        print("    到不了拆解页")
        return False
    vs.frame(force=True)

    from zzz_disc_train import read_disc
    # 用筛选面板顶部的排序：字段切「等级」+ 圆形键点一次 = 最高等级在前。
    # 比连续滚 25 次可靠得多（滚动中间不能截图，很脆弱）。
    sort_by_level(ui)
    vs.frame(force=True)
    cards = [it for it in vs.items((60, 120, 1100, 980))
             if _level_label(it["text"], level)]
    if not cards:
        # 排序失败就退回滚动
        import time as _t
        inp.move(600, 500)
        _t.sleep(0.5)
        for _batch in range(8):
            for _ in range(25):
                inp.wheel(-8)
                _t.sleep(0.18)
            vs.frame(force=True)
            got = [it for it in vs.items((60, 120, 1100, 980))
                   if _level_label(it["text"], level)]
            if got:
                cards = got
                break
    for c in cards:
        # 先看标签里的等级，快速跳过。
        # BUG-002：原来是 `str(level) not in c["text"]`，
        # level=1 时 "1" 在 "等级15" 里也成立 → 白点一堆不相干的卡。
        if not _level_label(c["text"], level):
            continue
        inp.click(c["cx"], c["cy"] - 60, wait=1.2)
        vs.frame(force=True)
        d = read_disc(vs)
        # BUG-001：**必须比对等级**。
        # 原来只比 set+slot，同套同位号的 Lv0 废盘和 Lv15 毕业盘无法区分，
        # 标记会落在该位号第一张卡片上 —— 最坏是把毕业盘标成狗粮，
        # 下一轮拆解就真拆掉了（不可逆）。
        # **匹配加上主属性**（RT-12）：同一套同位号同等级可能有两块，
        # 主属性不同（攻击力 vs 暴击率）。原来只比三级，标记可能落在错的那块，
        # 下一轮「全选已弃置」就把它拆了 —— 拆解不可逆。
        _main_ok = (not want_main) or (d.get("main") == want_main)
        if (d["set"] != set_name or d["slot"] != slot
                or d["level"] != level or not _main_ok):
            continue
        # 命中：按 R
        inp.key("r", wait=1.8)
        vs.frame(force=True)
        if "标记为弃置状态" not in vs.debug_text():
            print("    按 R 没弹窗")
            return False
        inp.click(XY_DLG_CONFIRM[0], XY_DLG_CONFIRM[1], wait=2.0)
        vs.frame(force=True)
        print(f"    已标记弃置：{set_name}[{slot}] Lv{d['level']}"
              f"（要求 Lv{level}）")
        return True
    print(f"    拆解页里没找到 {set_name}[{slot}] Lv{level}")
    return False


def dismantle_all_abandoned(ui: Ui, m: Machine, expect: int | None = None,
                            max_ratio: float | None = None) -> bool:
    """拆解所有已弃置的盘。

    ## 两道前置闸（BUG-003 / BUG-004）

    这个函数点的是「全选已弃置」—— **账号上所有被标记弃置的盘**，
    不是本轮算出来的那些。所以拆之前必须确认：

    1. `max_ratio`：已弃置数不能超过库总数的这个比例（默认读 disc_cfg 的 0.5）
    2. `expect`：已弃置数必须正好等于本轮成功标记的块数

    **任一不过就中止。** 拆解不可逆，宁可拆不动也不能多拆。
    """
    vs, inp = ui.vs, ui.inp
    if not m.go_to("驱动盘拆解页"):
        return False
    vs.frame(force=True)

    # 安全阀默认值从配置读（原来那个键写了但零引用 —— BUG-004）
    if max_ratio is None:
        try:
            from core.disc_cfg import THRESHOLDS
            max_ratio = float(THRESHOLDS.get("max_dismantle_ratio", 0.5))
        except Exception:
            max_ratio = 0.5

    # **先读库总数**（此时还没套「已弃置」筛选）
    total = mesh(vs)
    print(f"  库总数 {total} 张（比例上限 {max_ratio:.0%}）")

    # 算一下当前已弃置有多少
    inp.click(XY_FUNNEL[0], XY_FUNNEL[1], wait=2.4)
    vs.frame(force=True)
    if "驱动盘筛选" not in vs.debug_text():
        print("  漏斗打不开")
        return False
    ab = vs.find("已弃置", (1300, 380, 1920, 500))
    if ab:
        inp.click(ab["cx"], ab["cy"], wait=2.0)
        vs.frame(force=True)
    n = mesh(vs)
    inp.key("esc", wait=1.8)
    vs.frame(force=True)
    print(f"  已弃置 {n} 张")
    if n <= 0:
        return True

    # ---- 闸 1：比例（BUG-004）----
    if total > 0 and n > total * max_ratio:
        print(f"  ✘ 中止：已弃置 {n} 张 > 库总数 {total} × {max_ratio:.0%}"
              f" = {total * max_ratio:.0f}")
        print(f"     这是一次性要拆掉 {n / total:.0%} 的仓库，超出安全阀。")
        print(f"     确认要拆就把 disc_cfg.json 的 max_dismantle_ratio 调高，")
        print(f"     或先手工清掉不该拆的弃置标记。")
        return False

    # ---- 闸 2：数量必须正好等于本轮标记数（BUG-003）----
    if expect is not None and n != expect:
        print(f"  ✘ 中止：已弃置 {n} 张 ≠ 本轮标记 {expect} 张")
        print(f"     仓库里还有 {n - expect} 张别的弃置盘（上次或手工标的），")
        print(f"     拆「全选已弃置」会把它们一起拆掉。")
        print(f"     先手工清掉那些标记，或改用精确勾选。")
        return False
    print(f"  ✔ 两道闸通过（{n} 张，占库 {n / total:.0%}）" if total > 0
          else f"  ✔ 数量闸通过（{n} 张）")

    # 快速选择 → 全选已弃置 → 确认
    q = vs.find("快速选择", (0, 900, 700, 1080))
    if not q:
        # 可能还在筛选面板里，ESC 退出来再找
        inp.key("esc", wait=1.8)
        vs.frame(force=True)
        q = vs.find("快速选择", (0, 900, 700, 1080))
    if not q:
        print("  找不到快速选择（底部：" + vs.text((0, 900, 900, 1080))[:60] + "）")
        return False
    inp.click(q["cx"], q["cy"], wait=2.2)
    vs.frame(force=True)
    a = vs.find("全选已弃置", (0, 0, 1920, 1080))
    if not a:
        print("  找不到全选已弃置")
        return False
    inp.click(a["cx"], a["cy"], wait=1.8)
    vs.frame(force=True)
    c = vs.find("确认", (0, 0, 1920, 1080))
    if c:
        inp.click(c["cx"], c["cy"], wait=2.2)
    vs.frame(force=True)
    print(f"  选中 {top_count(vs)} 张")

    # 拆解
    inp.click(XY_DISMANTLE_BTN[0], XY_DISMANTLE_BTN[1], wait=2.5)
    vs.frame(force=True)
    if "分解" not in vs.debug_text():
        print("  没弹拆解确认框")
        return False
    inp.click(XY_FINAL_CONFIRM[0], XY_FINAL_CONFIRM[1], wait=4.0)
    vs.frame(force=True)
    got = vs.text((0, 0, 1920, 400))
    print(f"  拆解完成：{got[:80]}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    # **默认角色只有一个真相**：`core.game_cfg.DEFAULT_AGENT`（E16）。
    # 写死作者自己的角色名，朋友的机器上会去操作一个不存在的角色。
    ap.add_argument("agent", nargs="?", default=_DEFAULT_AGENT)
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--recycle", action="store_true")
    ap.add_argument("--keep-min", type=float, default=KEEP_MIN)
    ap.add_argument("--slots", default="")
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
    log = Journal(f"盘循环_{args.agent}")

    if not select_agent(ui, m, args.agent):
        print("选不中")
        return 3

    from zzz_disc_train import read_disc, evaluate, upgrade_disc
    from zzz_equip import open_custom

    slots = [int(x) for x in args.slots.split(",") if x.strip()] or list(range(1, 7))
    junk, kept = [], []

    for slot in slots:
        if not m.go_to("装备页"):
            break
        if not open_custom(ui, m, slot):
            print(f"{slot}号位：进不去")
            continue
        vs.frame(force=True)
        d = read_disc(vs)
        if not d["set"]:
            print(f"{slot}号位：读不到")
            continue
        ev = evaluate(d, good, half)
        print(f"{slot}号位 {d['set']} Lv{d['level']}/{d['cap']} 有效 {ev['eff']}")

        if args.train and d["level"] < d["cap"]:
            for _ in range(6):
                ok, _out = upgrade_disc(slot, args.agent)
                if not ok:
                    break
                if not m.go_to("装备页") or not open_custom(ui, m, slot):
                    break
                vs.frame(force=True)
                d = read_disc(vs)
                ev = evaluate(d, good, half)
                print(f"  升到 Lv{d['level']} 有效 {ev['eff']}")
                if d["level"] >= d["cap"]:
                    break

        # Lv0 的盘没升过，不判废——它是候选
        if d["level"] == 0:
            verdict = "候选"
        elif d["level"] < d["cap"]:
            verdict = "过渡"
        elif ev["eff"] >= args.keep_min:
            verdict = "留"
        elif ev["eff"] < JUNK_MAX:
            verdict = "废"
        else:
            verdict = "过渡"
        print(f"  → Lv{d['level']} 有效 {ev['eff']} {verdict}")
        if verdict == "废":
            junk.append((slot, d["set"], d["level"], ev["eff"], d.get("main", "")))
        else:
            kept.append((slot, d["set"], d["level"], ev["eff"]))
        log.log(f"{slot}号位", verdict, ok=True, detail=f"Lv{d['level']} 有效{ev['eff']}")

    print()
    print(f"留：{len(kept)} 块　废：{len(junk)} 块")
    for j in junk:
        print(f"  废 {j[1]}[{j[0]}] Lv{j[2]} 有效{j[3]}  主属性 {j[4] or '?'}")

    if args.recycle and junk:
        print()
        print("=== 标记弃置 ===")
        # **记成功数** —— 拆解闸要拿它比对，标记失败的不该被算进「该拆」
        marked = 0
        for slot, set_name, level, _e, main_attr in junk:
            if mark_disc_abandoned(ui, m, slot, set_name, level, main_attr):
                marked += 1
        print(f"  标记成功 {marked}/{len(junk)}")

        print()
        print("=== 拆解 ===")
        if not dismantle_all_abandoned(ui, m, expect=marked):
            print("  ⚠ 拆解被安全阀拦下，本次没有拆任何东西")
            print(log.summary())
            return 1

    print()
    print(log.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
