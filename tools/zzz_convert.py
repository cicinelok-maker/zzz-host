"""材料转化：低级↔高级双向（用户 2026-11-24 确认）。

## 三个「转化获取」入口（都在材料不足时才出现）

| 入口 | 材料 | 状态 |
|---|---|---|
| 技能强化 → 转化获取 | 特化芯片（攻击/防御/异常…） | ✔ 本工具处理 |
| 角色晋升 → 转化获取 | 认证章 | ✔ zzz_level.py 处理 |
| 音擎强化 → 材料转化 | 音擎蓄电池 | ✗ **未验证**（材料够时看不到按钮） |

## 双向转化（关键）

用户指出：**不但能从低级合成到高级，也能从高级分解到低级。**

所以刷本策略简化成：**只刷最高级副本**，缺什么用转化补。
详见 core/game_cfg.py 的 CONVERT_STRATEGY。

## 技能转化的界面（实测）

技能格 → 技能强化 → 「转化获取」→ 弹「材料转化」对话框：

    材料转化
    24 → 8
    仍需 8 个特化以太芯片，是否消耗其他材料进行转化？
    消耗：3769294/2400
    [取消]  [确认]

注意：这个按钮**只在材料不足时出现**。材料够时点进去什么都没有，
所以本工具在材料充足时会报「没有转化获取」，那是正常的。

## 未完成

--decompose（高级分解到低级）还没实现——需要材料不足的场合才能看到
分解按钮的位置，目前无法验证。
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

from core import Vision,Input,Ui,Journal# noqa: E402
from core.machine import Machine# noqa: E402
from pick_agent import select_agent# noqa: E402
from core import locate# noqa: E402
from core.game_cfg import DEFAULT_AGENT as _DEFAULT_AGENT# 统一默认角色

# 底部五个技能格（图标中心）
SKILL_CELLS = {1: (984, 700), 2: (1158, 700), 3: (1332, 700),
               4: (1503, 700), 5: (1679, 700)}
R_CONFIRM = (700, 700, 1400, 820)


def goto_skill(ui: Ui, m: Machine, agent: str) -> bool:
    vs, inp = ui.vs, ui.inp
    if not select_agent(ui, m, agent):
        return False
    vs.frame(force=True)   # 换角色后必须刷新
    hits = vs.find_all("技能", (0, 0, 1920, 1080))
    if not hits:
        return False
    h = max(hits, key=lambda i: i["cy"])
    inp.click(h["cx"], h["cy"], wait=2.0)
    return True


def open_convert_dialog(ui: Ui, slot: int) -> dict | None:
    """进技能详情 → 技能强化 → 转化获取，返回对话框信息"""
    vs, inp = ui.vs, ui.inp
    # **少读格子时位置索引会整体错位**（BUG-94）。
    #
    # `locate.skill_cells()` 返回的是**位置列表**（按 x 排序的前 5 个）。
    # 如果只读出 4 个（某个图标没识别到），`live[2]`（3 号技能）
    # 拿到的是**第 3 个被认出的格子**，可能其实是 4 号或 5 号 ——
    # 于是「点 3 号技能」实际点了别的技能，然后**转化/升级花掉了材料**。
    #
    # 现在：只有认全 5 个才用实测坐标，否则退回固定坐标
    # （固定坐标是按 1920x1080 标定的，本项目也强制这个分辨率）。
    live = locate.skill_cells(vs)
    if len(live) == len(SKILL_CELLS):
        xy = live[slot - 1]
    else:
        if live:
            print(f"    ⚠ 只认出 {len(live)}/5 个技能格，位置索引会错位，"
                  f"改用固定坐标")
        xy = SKILL_CELLS.get(slot)
    if not xy:
        return None
    inp.click(xy[0], xy[1], wait=1.8)
    vs.frame(force=True)

    h = vs.find("技能强化", (1200, 950, 1920, 1080))
    if not h:
        print(f"  {slot} 号技能：找不到「技能强化」")
        return None
    inp.click(h["cx"], h["cy"], wait=2.2)
    vs.frame(force=True)

    c = vs.find("转化获取", (900, 850, 1500, 980))
    if not c:
        print(f"  {slot} 号技能：没有「转化获取」（材料可能够）")
        return None
    inp.click(c["cx"], c["cy"], wait=2.2)
    vs.frame(force=True)

    txt = vs.text((600, 300, 1400, 820))
    if "材料转化" not in txt:
        print(f"  {slot} 号技能：没弹出材料转化框　{txt[:80]}")
        return None

    need = re.search(r"仍需\s*(\d+)\s*个(.+?)[，,]?\s*是否", txt)
    cost = re.search(r"消耗[：:].*?(\d+)\s*/\s*(\d+)", txt)
    nums = re.findall(r"(\d+)\s*/\s*(\d+)", txt)
    return {
        "slot": slot,
        "raw": txt[:300],
        "need_count": int(need.group(1)) if need else 0,
        "need_name": need.group(2).strip() if need else "",
        "cost": nums,
        "confirm": c is not None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=0, help="1-5，0 表示全部")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--agent", default=_DEFAULT_AGENT)
    ap.add_argument("--confirm", action="store_true", help="真的点确认（会消耗材料）")
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    log = Journal("材料转化")
    ui.start()
    m = Machine(ui, verbose=False)

    if not goto_skill(ui, m, args.agent):
        print("到不了技能页")
        return 3

    slots = list(SKILL_CELLS) if (args.all or args.slot == 0) else [args.slot]
    done = 0
    for slot in slots:
        print(f"\n=== {slot} 号技能 ===")
        info = open_convert_dialog(ui, slot)
        if not info:
            inp.key("esc", wait=1.0)
            continue
        print(f"  仍需 {info['need_count']} 个「{info['need_name']}」")
        print(f"  消耗：{info['cost']}")
        log.log(f"{slot}号", "读取", ok=True,
                detail=f"缺{info['need_count']}个{info['need_name']}")

        if args.confirm:
            c = vs.find("确认", R_CONFIRM)
            if c:
                inp.click(c["cx"], c["cy"], wait=2.0)
                vs.frame(force=True)
                print("  ✔ 已确认转化")
                log.log(f"{slot}号", "转化", ok=True)
                done += 1
            else:
                print("  找不到「确认」")
        else:
            print("  （未加 --confirm，只是查看）")
            cancel = vs.find("取消", R_CONFIRM)
            if cancel:
                inp.click(cancel["cx"], cancel["cy"], wait=1.2)
        # 退回技能页
        for _ in range(3):
            vs.frame(force=True)
            if "技能强化" not in vs.text((400, 130, 1200, 220)):
                break
            inp.key("esc", wait=1.2)

    print(f"\n完成，实际转化 {done} 次")
    print(log.summary())
    # **加了 --confirm 却一次都没转成，就不是成功**（BUG-087）。
    #
    # 转化会消耗低阶材料、不可逆。原来无论转了 0 次还是 5 次都 `return 0`，
    # 上层看不出区别。
    if done == 0 and getattr(args, "confirm", False):
        print("  ✘ 加了 --confirm 但一次都没转成（找不到确认按钮或材料不够）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())