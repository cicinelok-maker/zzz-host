"""角色升级（代理人培训）。

## 界面（实测，用猫又 等级10 验证）

基础页的等级显示是「当前 / 上限」，右边有个绿色 `>>>` 按钮：
```
等级10 / 20  >>>       ← >>> 在 (1355, 472)
```
点它打开「代理人培训」面板：
```
代理人培训
生命值 1767      攻击力 249      防御力 136
等级10 → 等级11
0/1800
0/3    0/8    0/153        ← 三种材料（拥有/需要）
长按连续添加材料
[自动添加] (830,822)   [升级] (1181,822)
```

**注意**：材料数量为 0 时，材料图标不显示，读不到来源。
要等有材料才能像技能材料那样点图标看「[获取]XXX」。

    python tools/zzz_level.py read                  # 读等级和升级需求
    python tools/zzz_level.py up --auto             # 自动添加材料并升级
    python tools/zzz_level.py roster                # 列出所有角色的等级
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, Journal  # noqa: E402
from core.machine import Machine  # noqa: E402
from pick_agent import reset_to_world, current_name  # noqa: E402

LV_ARROW = (1355, 472)          # 等级右边的绿色 >>> 按钮
R_LEVEL = (1000, 400, 1300, 520)
R_PANEL = (300, 200, 1400, 900)
BTN_AUTO = (830, 822)
BTN_UP = (1181, 822)


def goto_base(ui: Ui, m: Machine) -> bool:
    if not m.go_to("装备页"):
        return False
    ui.vs.frame(force=True)   # go_to 后必须刷新，否则读到导航前的旧帧
    h = ui.vs.find("基础", (900, 940, 1500, 1080))
    if h:
        ui.inp.click(h["cx"], h["cy"], wait=2.0)
    return True


def read_level(vs: Vision) -> str:
    for it in vs.items(R_LEVEL):
        if it["text"].startswith("等级"):
            return it["text"]
    # 有些页会把「等级10 / 20」拆成两块
    t = vs.text(R_LEVEL)
    m = re.search(r"等级\s*(\d+)", t)
    return f"等级{m.group(1)}" if m else ""


def find_arrow(vs: Vision) -> tuple[int, int] | None:
    """动态找等级右边的 >> 按钮。

    等级文字「等级30」在 (1122,471)，>> 在它右边约 210px。
    硬编码 (1355,472) 偏右 23px，正好擦边点不到，所以改成算出来的。
    """
    for it in vs.items((900, 420, 1500, 530)):
        m = re.match(r"等级(\d+)", it["text"])
        if m:
            return (it["cx"] + 210, it["cy"] + 6)
    return None


def open_panel(ui: Ui) -> str:
    """点等级右边的 >> 打开面板。

    返回面板类型：
        "培训"  → 代理人培训（没到等级上限时显示）
        "晋升"  → 职级晋升（**等级卡上限时显示这个**，不是培训）
        ""      → 打不开

    这就是为什么莱卡恩（30/30 卡上限）以前一直报「打不开」——
    工具在找「代理人培训」，游戏显示的是「职级晋升」。
    """
    vs, inp = ui.vs, ui.inp
    vs.frame(force=True)
    t = vs.text((0, 0, 1920, 1080))
    if "代理人培训" in t:
        return "培训"
    if "职级晋升" in t:
        return "晋升"

    xy = find_arrow(vs)
    for cand in ([xy] if xy else []) + [LV_ARROW, (1332, 477), (1320, 477)]:
        if not cand:
            continue
        inp.click(cand[0], cand[1], wait=2.2)
        vs.frame(force=True)
        t = vs.text((0, 0, 1920, 1080))
        if "代理人培训" in t:
            return "培训"
        if "职级晋升" in t:
            return "晋升"
    return ""


def read_material(vs: Vision) -> tuple[int, int]:
    """从面板读认证章数量。返回 (拥有, 需要)，读不到返回 (-1,-1)。

    先去掉「LV30/30」「LV30/40」这种等级显示，否则会被误当成材料。
    """
    t = vs.text((0, 0, 1920, 1080))
    t_clean = re.sub(r"LV\d+\s*/\s*\d+", "", t)
    pairs = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*/\s*(\d+)", t_clean)]
    for a, b in pairs:
        if 1 <= b <= 500:
            return a, b
    return -1, -1


def do_ascend(ui: Ui) -> tuple[bool, str]:
    """职级晋升。

    **关键：先点「转化获取」自动合成**（用户指出的）。
    转化获取会消耗低阶材料合成认证章；如果还是不够，游戏会显示材料不足。

    流程：
        1. 读材料 X/Y
        2. X < Y 就点「转化获取」自动合成
        3. 重新读
        4. 够了就点「晋升」，不够就报不足

    返回 (成功?, 说明)
    """
    vs, inp = ui.vs, ui.inp

    have, req = read_material(vs)
    if have < 0:
        return False, "读不到材料数量"

    # 材料不够 → 先转化获取（自动合成）
    if have < req:
        btn = vs.find("转化获取", (600, 700, 1600, 950))
        if not btn:
            return False, f"认证章不足 {have}/{req}，且找不到「转化获取」"
        print(f"    认证章 {have}/{req}，点「转化获取」自动合成…")
        inp.click(btn["cx"], btn["cy"], wait=4.5)
        vs.frame(force=True)
        # 可能弹确认
        c = vs.find("确认", (600, 500, 1400, 900))
        if c:
            inp.click(c["cx"], c["cy"], wait=2.5)
            vs.frame(force=True)
        for _ in range(3):
            have2, req2 = read_material(vs)
            if have2 >= req2:
                break
            vs.frame(force=True)
            time.sleep(1.0)
        if have2 >= 0:
            have, req = have2, req2
        print(f"    合成后：{have}/{req}")

    if have < req:
        return False, f"认证章仍不足 {have}/{req}（已尝试自动合成）"

    # 晋升按钮在面板底部按钮行，实测约 (1175, 824)
    # 注意：不能从 y=850 开始搜，会漏掉
    btn = vs.find("晋升", (900, 770, 1500, 880))
    if not btn:
        btn = vs.find("晋升", (600, 700, 1700, 950))
    if not btn:
        return False, f"材料够（{have}/{req}）但没找到「晋升」按钮"
    inp.click(btn["cx"], btn["cy"], wait=2.5)
    vs.frame(force=True)
    c = vs.find("确认", (600, 500, 1400, 900))
    if c:
        inp.click(c["cx"], c["cy"], wait=2.5)
        vs.frame(force=True)
    return True, f"已晋升（{have}/{req}）"


def parse_panel(vs: Vision, cur_level: int = -1) -> dict:
    """解析代理人培训面板。

    注意这个面板的数字约定和其他界面**相反**：
        0/4680 = 已选 0 / 经验上限 4680
        0/3    = 已选 0 / 仓库拥有 3
        0/246  = 已选 0 / 仓库拥有 246
    所以「能不能升」看的是分母（拥有量）> 0，不是分子>=分母。
    """
    t = vs.text(R_PANEL)
    costs = [[int(a), int(b)] for a, b in re.findall(r"(\d+)\s*/\s*(\d+)", t)]
    # 材料项（排除经验条：分子分母都很大或分母是 3 位数以上的经验）
    mats = [c for c in costs if c[1] <= 9999 and c[0] == 0] or costs[1:]
    have = [b for a, b in mats if b > 0]
    # 升级目标 = 当前等级 + 1（面板上的「20 → 20」是上下限，不是等级）
    lv_from = cur_level if cur_level > 0 else -1
    return {
        "from": lv_from,
        "to": (lv_from + 1) if lv_from > 0 else -1,
        "costs": costs,
        "materials_owned": have,
        "can": len(have) > 0 and all(b > 0 for a, b in mats if a == 0),
    }


def cmd_read(ui: Ui, m: Machine, agent: str) -> int:
    vs = ui.vs
    reset_to_world(ui)
    from pick_agent import select_agent
    if not select_agent(ui, m, agent):
        print(f"选不中「{agent}」")
        return 3
    if not goto_base(ui, m):
        print("到不了基础页")
        return 4
    lv_text = read_level(vs)
    m_lv = re.search(r"(\d+)", lv_text)
    cur_level = int(m_lv.group(1)) if m_lv else -1
    print(f"{agent}：{lv_text or '读不到等级'}")
    kind = open_panel(ui)
    if not kind:
        print("打不开面板")
        return 0
    if kind == "晋升":
        t = vs.text((0, 0, 1920, 1080))
        ok, why = do_ascend(ui)
        print(f"  职级晋升：{'✔ ' if ok else '✖ '}{why}")
        print(f"  {t[:110]}")
        return 0
    info = parse_panel(vs, cur_level)
    print(f"  升级：{info['from']} → {info['to']}")
    print(f"  材料：{'  '.join(f'{a}/{b}' for a, b in info['costs'])}")
    print(f"  {'材料够，可以升' if info['can'] else '材料不足'}")
    ui.inp.key("esc", wait=1.4)
    return 0


def cmd_up(ui: Ui, m: Machine, agent: str, auto: bool, times: int) -> int:
    vs, inp = ui.vs, ui.inp
    log = Journal(f"升级_{agent}")
    reset_to_world(ui)
    from pick_agent import select_agent
    if not select_agent(ui, m, agent):
        print(f"选不中「{agent}」")
        return 3
    if not goto_base(ui, m):
        print("到不了基础页")
        return 4

    done = 0
    for i in range(times):
        # 每轮都重新读一次当前等级（上一轮升完会变）
        vs.frame(force=True)
        lv_text = read_level(vs)
        m_lv = re.search(r"(\d+)", lv_text)
        cur_level = int(m_lv.group(1)) if m_lv else -1
        kind = open_panel(ui)
        if not kind:
            print(f"第 {i + 1} 轮：打不开面板，停止")
            break
        if kind == "晋升":
            # 卡等级上限了，先晋升再继续培训
            ok, why = do_ascend(ui)
            if ok:
                print(f"第 {i + 1} 轮：✔ 职级晋升成功，继续")
                log.log(f"第{i + 1}轮", "晋升", ok=True)
                done += 1
                continue
            print(f"  职级晋升：{why}")
            log.log(f"第{i + 1}轮", "晋升", ok=False, detail=why)
            inp.key("esc", wait=1.4)
            break
        info = parse_panel(vs, cur_level)
        print(f"第 {i + 1} 轮：{info['from']} → {info['to']}  "
              f"材料 {'  '.join(f'{a}/{b}' for a, b in info['costs'])}")
        if not info["can"]:
            print("  材料不足，停止")
            log.log(f"第{i + 1}轮", "材料不足", ok=False)
            inp.key("esc", wait=1.4)
            break
        if auto:
            inp.click(BTN_AUTO[0], BTN_AUTO[1], wait=1.5)
        inp.click(BTN_UP[0], BTN_UP[1], wait=2.0)
        vs.frame(force=True)
        print(f"  ✔ 已点升级")
        log.log(f"第{i + 1}轮", "升级", ok=True, detail=f"{info['from']}→{info['to']}")
        done += 1
        inp.key("esc", wait=1.2)

    print(f"\n完成，升级 {done} 次")
    print(log.summary())
    return 0


def cmd_roster(ui: Ui, m: Machine) -> int:
    """列出代理人列表里所有角色的等级"""
    vs, inp = ui.vs, ui.inp
    reset_to_world(ui)
    if not m.go_to("代理人列表"):
        print("到不了代理人列表")
        return 3
    vs.frame(force=True)
    lv = [(x["text"], x["cx"], x["cy"]) for x in vs.items((0, 0, 1920, 1080))
          if x["text"].startswith("等级")]
    print(f"本屏 {len(lv)} 个角色：")
    for t, x, y in lv:
        inp.click(x, y - 40, wait=1.5)
        vs.frame(force=True)
        nm = current_name(vs)
        print(f"  {nm or '?':<8} {t}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("read"); p1.add_argument("--agent", required=True)
    p2 = sub.add_parser("up")
    p2.add_argument("--agent", required=True)
    p2.add_argument("--auto", action="store_true", help="先点「自动添加」")
    p2.add_argument("--times", type=int, default=5)
    sub.add_parser("roster")
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)

    if args.cmd == "read":
        return cmd_read(ui, m, args.agent)
    if args.cmd == "up":
        return cmd_up(ui, m, args.agent, args.auto, args.times)
    return cmd_roster(ui, m)


if __name__ == "__main__":
    sys.exit(main())