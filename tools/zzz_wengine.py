"""音擎强化 + 改装（突破）——改版：一次选一个，在面板里升到底。

## 为什么这么改

满级音擎的「强化」按钮是**灰的**，从详情页点不开面板。
但在面板里升到上限时，按钮会变成「改装」，点了就突破上限继续升。

所以正确策略是：
    选一个音擎 → 开面板 → 在面板里一路 强化↔改装 到材料用完 → 退出 → 换下一个

不要每轮都退出重进，那样每次撞上限就卡死。

## 完整流程（实测）

    装备页 → 点音擎圆盘中心 (1345,620) → 音擎详情
    左侧选音擎（>= 2 次点击，要验证详情真的变了）
    底部「强化」@(1717,1030) → 强化面板
        面板内循环：
            「自动添加」@(1204,842)
            「强化」@(1446,842) → 材料返还「确认」@(978,728)
            撞上限时按钮变「改装」@(1452,842) → 点它突破
            直到材料不足或到 60 级

## 用法

    python tools/zzz_wengine.py read --agent 莱卡恩
    python tools/zzz_wengine.py up --agent 莱卡恩 --times 30
    python tools/zzz_wengine.py up --agent 莱卡恩 --engine 日冕遗蜕
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

from core import Vision,Input,Ui,Journal# noqa: E402
from core.machine import Machine# noqa: E402
from pick_agent import select_agent# noqa: E402
from core.game_cfg import DEFAULT_AGENT as _DEFAULT_AGENT

W_ENGINE_CENTER = (1345, 620)
BTN_UPGRADE = (1717, 1030)
BTN_AUTO = (1204, 842)
BTN_DO_UP = (1446, 842)
BTN_CONFIRM = (978, 728)
BTN_MODIFY = (1452, 842)
R_DETAIL = (400, 120, 1100, 760)
R_PANEL = (400, 180, 1600, 900)


BTN_ASCEND = (1756, 947)      # 「进阶」——音擎到等级上限时用这个
BTN_ENHANCE = (1755, 1029)    # 「强化」——在上限内升级用这个


def can_ascend(vs: Vision) -> bool:
    """详情页底部有没有「进阶」按钮。

    实测 2026-11-24：音擎到当前突破上限（如 等级10/10）时，
    点「强化」不会打开强化面板——必须先点「进阶」突破。
    这也是之前「状态不明」报错的真因。
    """
    return vs.find("进阶", (BTN_ASCEND[0] - 90, BTN_ASCEND[1] - 60,
                            BTN_ASCEND[0] + 90, BTN_ASCEND[1] + 60)) is not None


def in_panel(vs: Vision) -> bool:
    return "自动添加" in vs.text((0, 0, 1920, 1080))


def in_detail(vs: Vision) -> bool:
    return "音擎效果" in vs.text((0, 0, 1920, 1080))


def open_detail(ui: Ui, m: Machine) -> bool:
    vs, inp = ui.vs, ui.inp
    if in_detail(vs):
        return True
    if in_panel(vs):
        inp.key("esc", wait=1.6)
        vs.frame(force=True)
        if in_detail(vs):
            return True
    vs.frame(force=True)
    inp.click(W_ENGINE_CENTER[0], W_ENGINE_CENTER[1], wait=2.2)
    vs.frame(force=True)
    return in_detail(vs)


def list_engines(vs: Vision) -> list[dict]:
    out, seen = [], set()
    for it in vs.items((60, 140, 620, 990)):
        t = it["text"]
        m = re.match(r"等级(\d+)(?:\s*/\s*(\d+))?", t)
        if not m:
            continue
        k = (round(it["cx"] / 10) * 10, round(it["cy"] / 10) * 10)
        if k in seen:
            continue
        seen.add(k)
        out.append({"level": int(m.group(1)),
                    "cap": int(m.group(2)) if m.group(2) else None,
                    "cx": it["cx"], "cy": it["cy"]})
    out.sort(key=lambda d: (d["cy"], d["cx"]))
    return out


# 图标中心相对等级标签的偏移。实测 2026-11-24 一轮试下来：
#   dy=50 命中，dy=70 会偏到相邻卡片，导致「日志说第5个、实际选中别的」。
ENGINE_LABEL_DY = 50


# 音擎的等级上限只有 10/20/30/40/50/60；驱动盘的 /15 是干扰项
ENGINE_CAPS = (10, 20, 30, 40, 50, 60)


def parse_level(det: str) -> tuple[int, int]:
    """读音擎等级。**必须排除驱动盘的 等级N/15**。

    2026-11-24 修：原来直接取第一个 等级N/M，
    结果全屏里右边驱动盘的「等级0/15」会被当成音擎等级，
    导致守卫误判通过、实际在升另一块音擎。
    """
    for m in re.finditer(r"等级\s*(\d+)\s*/\s*(\d+)", det):
        cur, cap = int(m.group(1)), int(m.group(2))
        if cap in ENGINE_CAPS:
            return cur, cap
    return -1, -1


def upgrade_loop_once(ui: Ui) -> tuple[int, int]:
    """在强化面板里点一次强化。返回 (强化次数, 改装次数)。"""
    vs, inp = ui.vs, ui.inp
    a = vs.find("自动添加", (1000, 780, 1600, 900))
    if a:
        inp.click(a["cx"], a["cy"], wait=1.8)
        vs.frame(force=True)
    b = vs.find("强化", (1380, 790, 1520, 900))
    if not b:
        return 0, 0
    inp.click(b["cx"], b["cy"], wait=2.8)
    vs.frame(force=True)
    t = vs.text((0, 0, 1920, 1080))
    if "不足" in t:
        return 0, 0
    if "确认" in t or "材料返还" in t:
        c = vs.find("确认", (700, 500, 1400, 900))
        if c:
            inp.click(c["cx"], c["cy"], wait=2.4)
        return 1, 0
    return 0, 0


# ---------------------------------------------------------------- 推荐面板
R_REC_PANEL = (1000, 20, 1920, 1080)   # 「音擎推荐」面板区域
XY_REC_BTN = (456, 1028)               # 详情页底部「推荐」
XY_REC_CLOSE = (1859, 52)


def _in_recommend(vs: Vision) -> bool:
    """是否在「音擎推荐」面板。

    实测：面板标题「音擎推荐」OCR 读不到（太小/被裁），
    但正文一定有「代理人专属」和「玩家热门」这两个标签。
    """
    t = vs.debug_text()
    return "代理人专属" in t or "玩家热门" in t


def open_recommend(ui: Ui, m: Machine) -> bool:
    """打开游戏自带的「音擎推荐」面板。"""
    vs, inp = ui.vs, ui.inp
    for _ in range(3):
        vs.frame(force=True)
        if _in_recommend(vs):
            return True
        if not in_detail(vs) and not open_detail(ui, m):
            return False
        r = vs.find("推荐", (100, 950, 700, 1080))
        if not r:
            return False
        inp.click(r["cx"], r["cy"], wait=2.6)
    vs.frame(force=True)
    return _in_recommend(vs)


def _detail_name(vs: Vision) -> str:
    """从左侧详情读出音擎名。详情第一行就是名字。"""
    t = vs.text((400, 120, 1100, 760))
    for p in (x.strip() for x in t.split("|")):
        if not p:
            continue
        if any(k in p for k in ("等级", "基础", "高级", "攻击", "属性",
                                "音擎效果", "对于", "装备者", "筛选", "推荐")):
            continue
        if len(p) >= 2:
            return p
    return ""


# 推荐面板右侧竖排的格子中心（实测截图量的）
XY_REC_SIG = (1732, 242)      # 「代理人专属」那一格
XY_REC_HOT1 = (1732, 470)     # 「玩家热门」第一格
XY_REC_HOT2 = (1732, 640)     # 第二格
XY_REC_HOT3 = (1732, 800)     # 第三格


def read_recommend(ui: Ui) -> dict:
    """读推荐面板：点每一格，从左侧详情拿名字。

    点完记得点回原来的那块，避免把角色的音擎改掉。
    """
    vs, inp = ui.vs, ui.inp
    out = {"当前": "", "专属": "", "热门": [], "专属有": False}

    # 先记下当前装备的是哪块（左半详情默认就是它）
    out["当前"] = _detail_name(vs)

    # 代理人专属那一格
    inp.click(XY_REC_SIG[0], XY_REC_SIG[1], wait=1.8)
    vs.frame(force=True)
    name = _detail_name(vs)
    if name and name != out["当前"]:
        out["专属"] = name
        out["专属有"] = True
    elif name:
        # 和当前同名 → 说明她已经装备了专属
        out["专属"] = name
        out["专属有"] = True

    # 玩家热门前三格
    for xy in (XY_REC_HOT1, XY_REC_HOT2, XY_REC_HOT3):
        inp.click(xy[0], xy[1], wait=1.5)
        vs.frame(force=True)
        n = _detail_name(vs)
        if n and n not in out["热门"] and n != out["专属"]:
            out["热门"].append(n)

    # 点回原来的那块，别改装备
    inp.click(XY_REC_SIG[0], XY_REC_SIG[1], wait=1.2)
    vs.frame(force=True)
    return out


def cmd_recommend(ui: Ui, m: Machine, agent: str) -> int:
    """报告该角色该装哪块音擎，并说明理由。"""
    vs, inp = ui.vs, ui.inp
    if not select_agent(ui, m, agent):
        print(f"选不中「{agent}」")
        return 3
    if not m.go_to("装备页"):
        print("到不了装备页")
        return 4
    if not open_recommend(ui, m):
        print("打不开音擎推荐面板")
        return 5

    rec = read_recommend(ui)
    print(f"\n=== {agent} 的音擎推荐 ===")
    print(f"  当前装备：{rec['当前'] or '?'}")
    print(f"  代理人专属：{rec['专属'] or '（读不到，可能没有专属）'}")
    if rec["热门"]:
        print(f"  玩家热门：{'、'.join(rec['热门'][:3])}")

    print()
    if rec["专属有"]:
        if rec["当前"] == rec["专属"]:
            print(f"  → 已装备专属「{rec['专属']}」，直接升它")
            verdict = "upgrade_equipped"
        else:
            print(f"  → 应换成专属「{rec['专属']}」再升")
            verdict = "equip_signature"
    else:
        pick = rec["热门"][0] if rec["热门"] else ""
        if pick and rec["当前"] == pick:
            print(f"  → 没有专属，已装备热门「{pick}」，直接升")
            verdict = "upgrade_equipped"
        elif pick:
            print(f"  → 没有专属，从玩家热门选「{pick}」装上再升")
            verdict = "equip_hot"
        else:
            print("  → 读不到推荐")
            verdict = "unknown"

    inp.key("esc", wait=1.6)
    return 0 if verdict != "unknown" else 6


XY_REC_EQUIP = (1719, 1029)     # 推荐面板底部「装备」（实测 OCR 位置）


def equip_from_recommend(ui: Ui, pick_sig: bool) -> bool:
    """在推荐面板里把指定那一格装上。

    pick_sig=True 点「代理人专属」格，False 点「玩家热门」第一格。
    """
    vs, inp = ui.vs, ui.inp
    xy = XY_REC_SIG if pick_sig else XY_REC_HOT1
    inp.click(xy[0], xy[1], wait=1.8)
    vs.frame(force=True)
    b = vs.find("装备", (1400, 980, 1900, 1080))
    if not b:
        # OCR 没读到就用实测坐标兜底
        print("    OCR 没找到装备按钮，用实测坐标")
        b = {"cx": XY_REC_EQUIP[0], "cy": XY_REC_EQUIP[1]}
    inp.click(b["cx"], b["cy"], wait=2.4)
    vs.frame(force=True)
    # 可能要确认
    t = vs.debug_text()
    if "确认" in t or "替换" in t:
        c = vs.find("确认", (600, 400, 1500, 900)) or vs.find("替换", (600, 400, 1500, 900))
        if c:
            inp.click(c["cx"], c["cy"], wait=2.2)
            vs.frame(force=True)
    print("    已装备")
    return True


def cmd_auto(ui: Ui, m: Machine, agent: str, times: int) -> int:
    """指名角色 → 判断该装哪块 → 换装 → 升满。完整闭环。"""
    vs, inp = ui.vs, ui.inp
    if not select_agent(ui, m, agent):
        print(f"选不中「{agent}」")
        return 3
    if not m.go_to("装备页"):
        print("到不了装备页")
        return 4

    # ---- 1) 判断 ----
    if not open_recommend(ui, m):
        print("打不开音擎推荐面板")
        return 5
    rec = read_recommend(ui)
    print(f"\n=== {agent} ===")
    print(f"  当前：{rec['当前'] or '?'}")
    print(f"  专属：{rec['专属'] or '（无）'}")
    if rec["热门"]:
        print(f"  热门：{'、'.join(rec['热门'][:3])}")

    # ---- 2) 决定目标 + 换装 ----
    if rec["专属有"]:
        target, need_equip = rec["专属"], rec["当前"] != rec["专属"]
        pick_sig = True
    elif rec["热门"]:
        target, need_equip = rec["热门"][0], rec["当前"] != rec["热门"][0]
        pick_sig = False
    else:
        print("  读不到推荐，放弃")
        inp.key("esc", wait=1.6)
        return 6

    print(f"  目标：{target}")
    if need_equip:
        print(f"  → 需要换装（{rec['当前']} → {target}）")
        if not equip_from_recommend(ui, pick_sig):
            inp.key("esc", wait=1.6)
            return 7
    else:
        print("  → 已经是目标音擎，跳过换装")

    inp.key("esc", wait=1.8)
    vs.frame(force=True)

    # ---- 3) 升级 ----
    if not open_detail(ui, m):
        print("打不开音擎详情")
        return 8
    vs.frame(force=True)
    lv, cap = parse_level(vs.text(R_DETAIL))
    print(f"\n  开始升级：等级{lv}/{cap}")

    total_up = 0
    for _ in range(times * 2 + 6):
        vs.frame(force=True)
        lv, cap = parse_level(vs.text(R_DETAIL))
        if lv < 0:
            print("    读不到等级，停止")
            break
        if lv >= cap > 0 and cap >= 60:
            break
        if can_ascend(vs):
            inp.click(BTN_ASCEND[0], BTN_ASCEND[1], wait=2.8)
            vs.frame(force=True)
            if "确认" in vs.debug_text():
                c = vs.find("确认", (600, 450, 1500, 900))
                if c:
                    inp.click(c["cx"], c["cy"], wait=2.5)
                    vs.frame(force=True)
            if can_ascend(vs):
                print("    进阶失败（材料不足？）")
                break
            total_up += 1
            continue
        b = vs.find("强化", (1600, 960, 1900, 1080))
        if not b:
            break
        inp.click(b["cx"], b["cy"], wait=3.2)
        vs.frame(force=True)
        if not in_panel(vs):
            print("    强化面板没打开，停止")
            break
        ups, _mods = upgrade_loop_once(ui)
        if ups == 0:
            print("    强化没有进度（材料不足）")
            break
        total_up += ups
        inp.key("esc", wait=1.6)

    ui.vs.frame(force=True)

    lv, cap = parse_level(ui.vs.text(R_DETAIL))
    print(f"\n完成：有效操作 {total_up} 次，最终等级 {lv}/{cap}")
    return 0


def cmd_read(ui: Ui, m: Machine, agent: str) -> int:
    vs = ui.vs
    if not select_agent(ui, m, agent):
        print(f"选不中「{agent}」")
        return 3
    if not m.go_to("装备页"):
        print("到不了装备页")
        return 4
    if not open_detail(ui, m):
        print("打不开音擎详情")
        return 5
    vs.frame(force=True)   # go_to 后必须刷新再读列表
    engines = list_engines(vs)
    print(f"音擎列表 {len(engines)} 个：")
    for e in engines:
        print(f"  等级{e['level']}{'/' + str(e['cap']) if e['cap'] else ''}"
              f" @({e['cx']},{e['cy']})")
    print(f"\n当前详情：{vs.text(R_DETAIL)[:150]}")
    return 0


def cmd_up(ui: Ui, m: Machine, agent: str, times: int) -> int:
    """只升当前装备的那一块音擎（用户 2026-11-24 纠正）。

    音擎不像驱动盘需要换装：每个角色就一块专属/下位音擎，
    升它就够了。所以这里完全不遍历列表。
    """
    vs, inp = ui.vs, ui.inp
    log = Journal(f"音擎_{agent}")
    if not select_agent(ui, m, agent):
        print(f"选不中「{agent}」")
        return 3
    if not m.go_to("装备页"):
        print("到不了装备页")
        return 4
    if not open_detail(ui, m):
        print("打不开音擎详情")
        return 5

    vs.frame(force=True)
    lv, cap = parse_level(vs.text(R_DETAIL))
    print(f"当前装备的音擎：等级{lv}/{cap}")

    total_up = total_mod = 0
    for step in range(times * 2 + 4):
        vs.frame(force=True)
        det = vs.text(R_DETAIL)
        lv, cap = parse_level(det)
        if lv < 0:
            print("  读不到等级，停止")
            break
        if lv >= cap > 0 and cap >= 60:
            print(f"  已满级（{lv}/{cap}），完成")
            break

        # 到当前突破上限 → 先进阶
        if can_ascend(vs):
            print(f"  等级{lv}/{cap} 到上限，进阶…")
            inp.click(BTN_ASCEND[0], BTN_ASCEND[1], wait=2.8)
            vs.frame(force=True)
            if "确认" in vs.debug_text():
                c = vs.find("确认", (600, 450, 1500, 900))
                if c:
                    inp.click(c["cx"], c["cy"], wait=2.5)
                    vs.frame(force=True)
            if can_ascend(vs):
                print("    进阶失败（材料不足？）")
                break
            total_up += 1
            continue

        # 没到上限 → 强化
        b = vs.find("强化", (1600, 960, 1900, 1080))
        if not b:
            print("  找不到「强化」按钮，停止")
            break
        inp.click(b["cx"], b["cy"], wait=3.2)
        vs.frame(force=True)
        if not in_panel(vs):
            print("  强化面板没打开，停止")
            break
        ups, mods = upgrade_loop_once(ui)
        total_up += ups
        total_mod += mods
        if ups == 0 and mods == 0:
            print("  强化没有进度（材料不足？）")
            break
        print(f"  强化 {ups} 次 → 等级{parse_level(vs.text(R_DETAIL))[0]}")
        inp.key("esc", wait=1.6)

    print(f"\n完成：强化 {total_up} 次，改装 {total_mod} 次")
    ui.vs.frame(force=True)   # 循环里最后可能按过 ESC，读等级前刷新
    lv, cap = parse_level(ui.vs.text(R_DETAIL))
    print(f"最终等级：{lv}/{cap}")
    print(log.summary())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("read"); p1.add_argument("--agent", default=_DEFAULT_AGENT)
    p2 = sub.add_parser("up")
    p2.add_argument("--agent", default=_DEFAULT_AGENT)
    p2.add_argument("--times", type=int, default=20)
    p3 = sub.add_parser("recommend")
    p3.add_argument("--agent", default=_DEFAULT_AGENT)
    p4 = sub.add_parser("auto")
    p4.add_argument("--agent", default=_DEFAULT_AGENT)
    p4.add_argument("--times", type=int, default=20)
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)

    if args.cmd == "read":
        return cmd_read(ui, m, args.agent)
    if args.cmd == "recommend":
        return cmd_recommend(ui, m, args.agent)
    if args.cmd == "auto":
        return cmd_auto(ui, m, args.agent, args.times)
    return cmd_up(ui, m, args.agent, args.times)


if __name__ == "__main__":
    sys.exit(main())