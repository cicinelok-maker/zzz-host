"""代理人选择：按「等级标签」定位头像，不猜坐标。

## 为什么改

旧版用硬编码的候选坐标网格逐点试，遇到网格右下角（猫又在 1824,1003）
或角色数量变化就选不中。

## 新做法（数据驱动）

代理人列表里每个头像下方都有「等级N」标签，OCR 能直接读到。
所以：

    1. OCR 找出屏幕上所有「等级N」标签的坐标
    2. 头像中心 = 标签上方约 40px
    3. 逐个点击 + 读左下角名字，命中就停
    4. 把「名字 → 坐标」记到缓存，下次先查缓存

这样完全不需要猜网格布局，角色数量变化、滚动都不影响。

## 缓存

state/agent_positions.json：{名字: [x, y]}
命中的位置记下来，下次直接点，失败再从 OCR 重扫。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, anchors  # noqa: E402
from core.machine import Machine  # noqa: E402

R_NAME = (80, 880, 620, 1030)
R_GRID = (900, 60, 1920, 1080)
AGENT_LABEL_DY = -40
CACHE = BASE / "state" / "agent_positions.json"


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(d: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_name(vs: Vision) -> str:
    """读左下角的当前角色名（纯中文 2~6 字）"""
    vs.frame(force=True)
    t = vs.text(R_NAME)
    for part in t.split("|"):
        p = part.strip()
        if not p or "等级" in p or "UID" in p:
            continue
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,6}", p):
            return p
    return ""


def current_name(vs: Vision) -> str:
    if not anchors.is_(vs, "代理人列表"):
        return ""
    return _read_name(vs)


def _describe_stable(vs, tries: int = 2, gap: float = 0.18) -> str:
    """连判几次，任一次认出就用它。

    抢前台/切换画面后的第一帧经常是过渡画面。
    单次判定失败不代表「不在大世界」，可能只是「还没画好」。
    """
    last = "未知界面"
    for i in range(max(1, tries)):
        try:
            vs.frame(force=True)
        except Exception:
            pass
        last = anchors.describe(vs)
        if last != "未知界面":
            return last
        if i + 1 < tries:
            time.sleep(gap)
    return last


def reset_to_world(ui: Ui, max_esc: int = 6) -> bool:
    """退回大世界。

    **不要在第一帧判不出来时就按键。** ESC 在大世界会打开菜单，
    越按画面越不像大世界 —— 实测会反复重试白花 28 秒。
    所以：先多判几次；确实要按键时，优先用手柄 B（无副作用），ESC 兜底。
    """
    vs, inp = ui.vs, ui.inp

    # 第一轮：只判不按。画面可能还在过渡。
    if _describe_stable(vs, tries=3, gap=0.2) == "世界":
        return True

    for i in range(max_esc):
        # 优先手柄 B：它在大世界没有副作用（不像 ESC 会开菜单）
        try:
            inp.pad_tap("b", wait=1.2)
        except Exception:
            inp.key("esc", wait=1.5)      # 手柄不可用才用 ESC
        if _describe_stable(vs, tries=2, gap=0.15) == "世界":
            return True

    return _describe_stable(vs, tries=3, gap=0.2) == "世界"


def _scan_portraits(vs: Vision) -> list[tuple[int, int]]:
    """OCR 读所有「等级N」标签，返回头像中心坐标列表（按 y 再 x 排序）"""
    vs.frame(force=True)
    pts = []
    for it in vs.items(R_GRID):
        if not it["text"].startswith("等级"):
            continue
        pts.append((it["cx"], it["cy"] + AGENT_LABEL_DY))
    pts.sort(key=lambda p: (p[1], p[0]))
    return pts


def _select_once(ui: Ui, m: Machine, name: str, verbose: bool) -> bool:
    vs, inp = ui.vs, ui.inp
    if not m.go_to("代理人列表"):
        if verbose:
            print("  到不了代理人列表")
        return False
    vs.frame(force=True)   # go_to 后必须刷新帧再读画面
    if not anchors.is_(vs, "代理人列表"):
        if verbose:
            print("  不在代理人列表页")
        return False

    # 归一化比较：OCR 读出来的可能是繁体/多个空格，裸 == 会误判
    from core.agent_name import lenient_match
    if lenient_match(current_name(vs), name):
        if verbose:
            print(f"  已经是「{name}」")
        return True

    # 1) 先查缓存
    cache = load_cache()
    order: list[tuple[int, int]] = []
    if name in cache:
        order.append(tuple(cache[name]))
    # 2) 再用 OCR 扫出来的实际位置
    for p in _scan_portraits(vs):
        if p not in order:
            order.append(p)

    if verbose:
        print(f"  候选位置 {len(order)} 个")

    for pt in order:
        inp.click(pt[0], pt[1], wait=1.3)
        vs.frame(force=True)
        got = _read_name(vs)
        if not got:
            continue
        if lenient_match(got, name):
            cache[name] = [pt[0], pt[1]]
            save_cache(cache)
            if verbose:
                print(f"  找到「{name}」@ {pt}")
            return True

    # 3) 当前屏没有，滚动再找（实测网格会滚动，第一屏只有 9 个）
    if verbose:
        print("  第一屏没找到，开始滚动")
    for key in (-3, -3, 3, 3):
        inp.wheel(key, wait=1.5)
        vs.frame(force=True)
        if not anchors.is_(vs, "代理人列表"):
            continue
        for pt in _scan_portraits(vs):
            inp.click(pt[0], pt[1], wait=1.3)
            vs.frame(force=True)
            got = _read_name(vs)
            if lenient_match(got, name):
                cache[name] = [pt[0], pt[1]]
                save_cache(cache)
                if verbose:
                    print(f"  滚动后找到「{name}」@ {pt}")
                return True

    if verbose:
        print(f"  没找到「{name}」（滚动了 4 次）")
    return False


def select_agent(ui: Ui, m: Machine, name: str, verbose: bool = True) -> bool:
    """选中指定角色。内部带「退大世界重来」兜底。"""
    if _select_once(ui, m, name, verbose):
        return True
    if verbose:
        print("  第一次没选中，退回大世界重试")
    if not reset_to_world(ui):
        return False
    return _select_once(ui, m, name, verbose)


def list_agents(ui: Ui, m: Machine) -> dict[str, str]:
    """扫一遍代理人列表（含滚动），返回 {名字: 等级}"""
    vs, inp = ui.vs, ui.inp
    reset_to_world(ui)
    if not m.go_to("代理人列表"):
        return {}
    out = {}
    for round_i in range(4):
        if round_i > 0:
            inp.wheel(-3, wait=1.5)
            vs.frame(force=True)
            if not anchors.is_(vs, "代理人列表"):
                break
        for pt in _scan_portraits(vs):
            inp.click(pt[0], pt[1], wait=1.2)
            vs.frame(force=True)
            nm = _read_name(vs)
            if not nm or nm in out:
                continue
            lv = ""
            for it in vs.items(R_GRID):
                if it["text"].startswith("等级") and abs(it["cx"] - pt[0]) < 60:
                    lv = it["text"]
                    break
            out[nm] = lv
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)

    if args.list or not args.name:
        roster = list_agents(ui, m)
        print(f"共 {len(roster)} 个角色：")
        for nm, lv in roster.items():
            print(f"  {nm:<8} {lv}")
    else:
        ok = select_agent(ui, m, args.name)
        print(f"选中「{args.name}」: {'✔' if ok else '✖'}  当前={current_name(vs)}")
