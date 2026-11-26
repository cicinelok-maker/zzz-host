"""驱动盘升级 / 装备（基于新底层，纯键鼠）。

摸清的界面：
    装备页（代理人详情）→ 点盘位 → 驱动盘定制
        定制页底部按钮：
            一键卸下 / 卸下（或「替换」当选中盘与当前装备不同）/ 强化
        强化面板按钮：
            阶段添加 (1286,866) / 升级 (1533,866)

    python tools/zzz_equip.py upgrade --slot 3 --set 拂晓行纪
    python tools/zzz_equip.py equip --slot 3 --set 拂晓行纪
    python tools/zzz_equip.py show --slot 3
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, Journal, anchors  # noqa: E402
from core.slots import slot_xy  # noqa: E402
from core.machine import Machine  # noqa: E402
from core.game_cfg import DEFAULT_AGENT as _DEFAULT_AGENT  # 统一默认角色

R_LIST = (60, 200, 1000, 940)
R_BOTTOM = (900, 980, 1920, 1080)
R_DETAIL = (500, 120, 900, 980)
R_PANEL = (240, 160, 1920, 960)

BTN_ADD = (1286, 866)      # 阶段添加
BTN_UP = (1533, 866)       # 升级


def open_custom(ui: Ui, m: Machine, slot: int, tries: int = 4,
                require_equipped: bool = True) -> bool:
    """导航到指定盘位的驱动盘定制页。

    实测这个点击偶发失败（约 1/4 概率，尤其 1 号位）。
    统一走 core.click.click_verify：同一位置重试 + 换偏移。
    """
    from core.click import click_verify
    from core.slots import slot_map
    for _outer in range(2):
        if not m.go_to("装备页"):
            return False
        ui.vs.frame(force=True)   # go_to 后必须刷新，否则读到旧帧
        # 空位判断：slot_map 里没有这个位号 = 没装盘。
        # 不判断的话点进去看到的是「仓库候选盘」，会被误当成已装备的盘。
        # 用户 2026-11-24 指出：1 号位明明是空的，却被算进副词条总数。
        if require_equipped and slot not in slot_map(ui.vs):
            print(f"  {slot} 号位是空位（没装盘）")
            return False
        xy = slot_xy(ui.vs, slot)
        if xy is None:
            print(f"  认不出 {slot} 号位（可能是空盘位）")
            return False
        ok = click_verify(
            ui, xy,
            check=lambda: anchors.is_(ui.vs, "驱动盘定制"),
            tries=tries, wait=2.0, label=f"{slot}号位",
        )
        if ok:
            return True
    return False

def list_discs(ui: Ui) -> list[dict]:
    """读定制页左侧列表里的盘（位号/等级/名称）。"""
    out = []
    for it in ui.vs.items(R_LIST):
        t = it["text"]
        m = re.match(r"等级(\d{1,2})", t)
        if m:
            out.append({"level": int(m.group(1)), "cx": it["cx"], "cy": it["cy"]})
    return out


def current_detail(ui: Ui) -> str:
    return ui.vs.text(R_DETAIL)


def find_disc(ui: Ui, set_name: str, want_level: int = -1,
              max_pages: int = 30) -> dict | None:
    """在列表里点遍所有盘（含滚动），直到左侧详情标题是目标套装。

    列表里的盘不显示名字，只能点开看左侧详情。
    2026-11-24 修正：原来只读可见卡片不滚动，屏幕外的盘找不到。
    实测驱动仓库不滚动只能看到 28/73 块。
    """
    inp = ui.inp
    cx = (R_LIST[0] + R_LIST[2]) // 2
    cy = (R_LIST[1] + R_LIST[3]) // 2

    # 滚回顶部
    for _ in range(24):
        inp.move(cx, cy)
        inp.wheel(3, wait=0.08)
    inp.move(cx, cy)
    inp.wheel(-1, wait=0.3)
    ui.vs.frame(force=True)

    seen_pos = set()
    idle = 0
    for page in range(max_pages):
        ui.vs.frame(force=True)
        discs = list_discs(ui)
        if want_level >= 0:
            discs = [d for d in discs if d["level"] == want_level]
        new = 0
        for d in discs:
            key = (d["cx"] // 8, d["cy"] // 8)
            if key in seen_pos:
                continue
            seen_pos.add(key)
            new += 1
            # 标签在卡片下方约 40px，要点卡片本身
            inp.click(d["cx"], d["cy"] - 42, wait=0.8)
            det = current_detail(ui)
            if set_name in det:
                return {**d, "detail": det}
        if new == 0:
            idle += 1
            if idle >= 3:
                break
        else:
            idle = 0
        inp.move(cx, cy)
        inp.wheel(-2, wait=0.45)
    return None

def _bottom_state(ui: Ui) -> str:
    """底部按钮区的文本快照（用来对比装备前后）。"""
    ui.vs.frame(force=True)
    return ui.vs.text(R_BOTTOM).strip()


def _equip_confirmed(before: str, after: str) -> bool:
    """点完「替换/装备」之后，能不能确认装上了。

    ## 判据（宁可报「未确认」，也不要谎报成功）

    1. 底部出现「卸下」——说明这块已经装在身上了（能卸才说明装着）
    2. 或者出现「已装备」「使用中」等字样
    3. 按钮文本变化了（`替换` → 别的东西）

    **返回 False 不代表一定失败，只代表「我确认不了」。**
    这种情况要报未确认 + 非 0 返回码，不能像原来那样直接 `print("装备完成")`。
    """
    for kw in ("卸下", "已装备", "装备中", "使用中"):
        if kw in after and kw not in before:
            return True
    if before != after and after:
        # 按钮文本变了，通常是 替换/装备 → 卸下
        return True
    return False


def panel_exp(ui: Ui) -> str:
    """从强化面板读经验进度（形如 0/480，排除丁尼那种大数字）"""
    import re as _re
    txt = ui.vs.text(R_PANEL)
    for m in _re.finditer(r"(\d{1,5})\s*/\s*(\d{1,5})", txt):
        cur, cap = int(m.group(1)), int(m.group(2))
        if cap and cap <= 5000 and cur <= cap:
            return m.group(0)
    return ""


def do_upgrade(ui: Ui, log: Journal, max_rounds: int = 8) -> str:
    """返回 'ok' / 'nomaterial' / 'nopanel'"""
    """在强化面板里反复「阶段添加 + 升级」直到满级或没材料。"""
    hit = ui.vs.find("强化", R_BOTTOM)
    if not hit:
        print("  底部没有「强化」按钮")
        return "nopanel"
    ui.inp.click(hit["cx"], hit["cy"], wait=2.2)
    ui.vs.frame(force=True)
    if not anchors.is_(ui.vs, "强化面板"):
        print(f"  没打开强化面板（当前 {anchors.describe(ui.vs)}）")
        print(f"  面板区域文字：{ui.vs.text(R_PANEL)[:100]}")
        return "nopanel"
    print(f"  强化面板已打开，经验 {panel_exp(ui) or '?'}")
    log.log("升级", "打开面板", ok=True, detail=panel_exp(ui))

    for i in range(max_rounds):
        txt = ui.vs.text(R_PANEL)
        if "物品不足" in txt:
            print(f"  第 {i + 1} 轮：物品不足，停止")
            log.log("升级", "物品不足", ok=False, detail=txt[:80])
            ui.inp.key("esc", wait=1.6)
            return "nomaterial"
        ui.inp.click(*BTN_ADD, wait=0.7)
        ui.inp.click(*BTN_UP, wait=1.6)
        e = panel_exp(ui)
        print(f"  第 {i + 1} 轮：经验 {e or '?'}")
        log.log("升级", f"第{i + 1}轮", ok=True, detail=e)
    # 退出面板
    ui.inp.key("esc", wait=1.6)
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("upgrade")
    e = sub.add_parser("equip")
    s = sub.add_parser("show")
    for p in (u, e, s):
        p.add_argument("--slot", type=int, default=1)
        p.add_argument("--set", dest="set_name", default="")
        p.add_argument("--agent", default=_DEFAULT_AGENT)
        p.add_argument("--level", type=int, default=-1,
                       help="优先选这个等级的盘（-1=不限）")
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    log = Journal(f"{args.cmd}_{args.slot}")
    ui.start()

    # 关键：先确认当前是这个角色，否则会在别人的配装上操作
    if getattr(args, "agent", ""):
        from core.machine import Machine as _M
        from pick_agent import select_agent as _sel, current_name as _cur
        _m = _M(ui, verbose=False)
        if not _sel(ui, _m, args.agent):
            print(f"  选不中「{args.agent}」（当前「{_cur(vs)}」），中止以免动错角色")
            return 4
        print(f"  已选中「{args.agent}」")
    m = Machine(ui, verbose=False)
    print("起点:", anchors.describe(vs))

    if not open_custom(ui, m, args.slot, require_equipped=False):
        print("到不了驱动盘定制")
        return 3

    d = find_disc(ui, args.set_name, getattr(args, "level", -1)) if args.set_name else None
    if args.set_name and not d:
        print(f"  定制页里没找到「{args.set_name}」的盘")
        return 4
    if d:
        print(f"  选中：等级{d['level']}  {args.set_name}")
        log.log("选盘", f"{args.set_name}", ok=True, detail=f"Lv{d['level']}")

    if args.cmd == "show":
        print(current_detail(ui))
        return 0

    if args.cmd == "upgrade":
        # 满级盘直接跳过（否则会在 MAX 面板里空点）
        #
        # BUG-005：原来是 `lv = d["level"] if d else -1`，
        # 不传 --set 时 `d` 恒 None → `lv` 恒 -1 → `if lv >= 15` 恒假，
        # **满级保护从来没生效过**。
        # 现在 d 为 None 时从详情面板文本里读等级。
        lv = d["level"] if d else -1
        if lv < 0:
            _m = re.search(r"(?:等级|Lv\.?)\s*(\d{1,2})", current_detail(ui))
            if _m:
                lv = int(_m.group(1))
        if lv >= 15:
            print(f"  这块盘已经是 Lv{lv} 满级，跳过")
            log.log("升级", "已满级", ok=True, detail=f"Lv{lv}")
            print(log.summary())
            return 0
        res = do_upgrade(ui, log)
        print({"ok": "升级完成", "nomaterial": "材料不足，已停止",
               "nopanel": "没能打开强化面板"}[res])
        return {"ok": 0, "nomaterial": 7, "nopanel": 5}[res]

    if args.cmd == "equip":
        # **没定位到目标盘就绝不点按钮**（BUG-005）。
        #
        # 原来不管 `d` 是不是 None 都点「替换/装备」——
        # 没跑过 find_disc 时，列表里选中的是游戏默认项，
        # 点下去就是把一个完全不相关的盘装上去，而且报「装备完成」。
        if d is None:
            print("  ✘ 没有定位到要装的盘，不点「替换/装备」")
            print("     换装必须能确认目标（--set 指定套装名）；")
            print("     否则点下去装的是游戏默认选中项，不是你想要的那块。")
            log.log("装备", "未定位", ok=False, detail="没有目标盘")
            print()
            print(log.summary())
            return 4

        # 只点「替换」，绝不点「卸下」——卸下是把装备拆掉，不是换装
        # 按钮文字实测有两种：「替换」或「装备」
        before = _bottom_state(ui)
        hit = ui.vs.find("替换", R_BOTTOM) or ui.vs.find("装备", R_BOTTOM)
        if not hit:
            print("  底部没有「替换/装备」按钮")
            return 6
        print(f"  点「{hit['text']}」")
        ui.inp.click(hit["cx"], hit["cy"], wait=2.0)

        # **点完必须验证**（BUG-005：原来这里直接 log ok=True + print 装备完成）
        after = _bottom_state(ui)
        if _equip_confirmed(before, after):
            log.log("装备", args.set_name, ok=True,
                    detail=f"Lv{d['level']} 已验证")
            print(f"  ✔ 已装备并确认：{args.set_name} Lv{d['level']}")
        else:
            log.log("装备", args.set_name, ok=False, detail="点了但没看到装备后的状态")
            print("  ✘ 点了「替换/装备」，但界面上没出现装备后的状态")
            print(f"     底部按钮前后都是：{after[:40]!r}")
            print("     不能确认装上去了 —— 请人工看一眼。")
            print()
            print(log.summary())
            return 1

    print()
    print(log.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())