"""核心技：A~F 六个圈的等级、材料需求、材料来源。

## 摸清的界面（用户指点后确认）

技能页右侧有六个圈 A~F **就是核心技**（不是手柄示意图）：
    A(1111,302)  C(1300,302)  E(1490,302)
    B(1063,472)  D(1300,472)  F(1490,472)

点一个 → 打开「核心技強化」面板：
    核心技強化
    基础攻击力提升25点
    [核心被动：煊赫车辇]技能等级+1
      上分支-终结技万军诛绝 / 下分支-凯旋坦途
      左分支-无拘剑势 / 右分支-永陷幽囚
    消耗材料   3/4   6/30   丁尼 3769294/200000
    前置天赋尚未解锁        ← 没解锁时会有这行
    培养建议 / 操作教学

## 材料来源：点材料图标（数字上方约 36px）

    刻命残蜕（高等级核心技）      → 恶名狩猎 / 哨站后勤
    高维数据：深蚀回路（核心技等级）→ 专业挑战室

    python tools/zzz_core.py read            # 读六个核心技
    python tools/zzz_core.py material        # 读当前面板里两个材料的来源
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

from core import Vision,Input,Ui,Journal,anchors# noqa: E402
from core.machine import Machine# noqa: E402
from pick_agent import select_agent# noqa: E402
from core import locate# noqa: E402
from core.game_cfg import DEFAULT_AGENT as _DEFAULT_AGENT# 统一默认角色

CORES = {"A": (1111, 302), "B": (1063, 472), "C": (1300, 302),
         "D": (1300, 472), "E": (1490, 302), "F": (1490, 472)}

R_PANEL = (0, 150, 1000, 780)
R_COST = (60, 730, 700, 960)

# 材料图标在数字上方约 36px
MAT_ICON_DY = -36
MAT_X = (135, 265)


def _on_skill_page(vs: Vision) -> bool:
    """判定是否已经在技能/核心技页面。

    注意：不能等「核心技」这三个字——那是点了某个核心技圈之后才出现的标题。
    技能页的特征是能看到技能名（普通攻击/闪避/…）或核心技的字母圈。
    """
    # 技能页的 OCR 只能读到等级数字（1012 / 08 / 12 …），读不到技能名，
    # 所以最可靠的判定是走状态机指纹。
    try:
        from core import anchors as _anc
        st = _anc.describe(vs)
        if st in ("技能页", "核心技", "技能详情", "技能强化面板"):
            return True
    except Exception:
        pass
    t = vs.debug_text()
    names = ["普通攻击", "闪避", "支援技", "特殊技", "连携技"]
    return any(n in t for n in names) or "核心技" in t


def goto_skill_tab(ui: Ui, m: Machine, agent: str) -> bool:
    vs, inp = ui.vs, ui.inp
    if not select_agent(ui, m, agent):
        return False
    vs.frame(force=True)   # 换角色后必须刷新
    # 实测：点「技能」标签偶发不生效（和驱动盘空位点击同一类问题），
    # 所以必须点击后验证面板真的开了，失败就重试。
    for attempt in range(3):
        hits = vs.find_all("技能", (0, 0, 1920, 1080))
        if not hits:
            print("  找不到「技能」标签")
            return False
        h = max(hits, key=lambda i: i["cy"])
        inp.click(h["cx"], h["cy"], wait=2.2)
        vs.frame(force=True)
        if _on_skill_page(vs):
            return True
        if attempt < 2:
            inp.click(h["cx"], h["cy"] + 6, wait=1.8)
            vs.frame(force=True)
            if _on_skill_page(vs):
                return True
    print("  技能页打开失败（重试 3 次）")
    return False


def parse_panel(txt: str) -> dict:
    """从核心技面板抽信息"""
    info = {
        "unlocked": "前置天赋尚未解锁" not in txt,
        "passive": "",
        "branches": [],
        "costs": [],
    }
    m = re.search(r"\[核心被动[：:]([^\]]+)\]", txt)
    if m:
        info["passive"] = m.group(1)
    for name in ("上分支", "下分支", "左分支", "右分支"):
        if name in txt:
            info["branches"].append(name)
    # 消耗材料：形如 3/4、6/30，以及丁尼
    seg = txt
    for a, b in re.findall(r"(\d+)\s*/\s*(\d+)", seg):
        info["costs"].append([int(a), int(b)])
    return info


def read_material(vs: Vision, inp: Input, xy: tuple[int, int]) -> dict:
    """点材料图标，读名称 + 来源"""
    icon = (xy[0], xy[1] + MAT_ICON_DY)
    before = vs.text((0, 0, 1920, 1080))
    inp.click(icon[0], icon[1], wait=2.0)
    vs.frame(force=True)
    popup = vs.text((0, 0, 1920, 1080))
    result = {"name": "", "have": 0, "sources": []}
    if popup == before:
        return result
    m = re.match(r"\s*([^|]+)", popup)
    if m:
        result["name"] = m.group(1).strip()
    h = re.search(r"当前拥有\s*[×x]\s*(\d+)", popup)
    if h:
        result["have"] = int(h.group(1))
    # [获取] 后面的名字
    for src in re.findall(r"\[获取\]\s*([^|\[]+)", popup):
        s = src.strip()
        if s and s not in result["sources"]:
            result["sources"].append(s)
    inp.key("esc", wait=1.5)
    return result


def read_all(ui: Ui, m: Machine, agent: str, with_mat: bool) -> dict:
    vs, inp = ui.vs, ui.inp
    if not goto_skill_tab(ui, m, agent):
        return {}
    out = {}
    live = locate.core_nodes(vs)          # OCR 现场读，读不到退回写死坐标
    if live:
        print(f"  核心技 OCR 定位到 {len(live)} 个圈")
    for key, xy in CORES.items():
        xy = live.get(key, xy)
        vs.frame(force=True)
        inp.click(xy[0], xy[1], wait=1.8)
        vs.frame(force=True)
        txt = vs.text(R_PANEL)
        if "核心技" not in txt:
            out[key] = {"error": "没打开"}
            continue
        info = parse_panel(txt + " " + vs.text(R_COST))
        info["key"] = key
        if with_mat and info["costs"]:
            mats = []
            for mx in MAT_X:
                d = read_material(vs, inp, (mx, 926))
                if d["name"]:
                    mats.append(d)
            info["materials"] = mats
        out[key] = info
        print(f"  {key}: 被动={info['passive'] or '?'} "
              f"分支={len(info['branches'])} 材料={info['costs']} "
              f"{'已解锁' if info['unlocked'] else '前置未解锁'}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("read", "material"):
        p = sub.add_parser(c)
        p.add_argument("--agent", default=_DEFAULT_AGENT)
        p.add_argument("--out", default=str(BASE / "state" / "core_status.json"))
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    log = Journal(f"核心技_{args.cmd}")
    ui.start()
    m = Machine(ui, verbose=False)

    data = read_all(ui, m, args.agent, with_mat=(args.cmd == "material"))
    if not data:
        print("读不到核心技")
        return 3

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\n已写入 {args.out}")
    if args.cmd == "material":
        print("\n材料来源汇总：")
        for k, v in data.items():
            for mat in v.get("materials") or []:
                print(f"  {mat['name']}（拥有{mat['have']}） → "
                      f"{' / '.join(mat['sources']) or '未读到来源'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())