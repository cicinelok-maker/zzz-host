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
    """点材料图标，读名称 + 拥有数 + 来源 + **来源按钮坐标** + 来源 boss。

    ## 为什么重写（2026-11-26）

    旧版只返回 `{name, have, sources: [字符串]}`，**丢了按钮坐标**。

    而用户指出：弹窗里那些「[获取]恶名狩猎」**是可点击的按钮**，
    点了会弹「是否立即传送？」→ 确认 → 游戏自己把你送到副本。

    **这意味着副本导航不用硬编码。**

    新版另外拿到：
    · `sources[].cx/cy`  —— 传送按钮坐标（可点）
    · `boss`             —— 描述里的「取自「XXX」」，即 boss→材料 对照
    · `desc`             —— 完整描述
    """
    from core import material_nav as _mnav

    icon = (xy[0], xy[1] + MAT_ICON_DY)
    before = vs.text((0, 0, 1920, 1080))
    inp.click(icon[0], icon[1], wait=2.0)
    vs.frame(force=True)

    pop = _mnav.read_popup(vs)
    if pop is None:
        # 画面没变（点空了）
        return {"name": "", "have": 0, "sources": []}

    result = {
        "name": pop.get("name") or "",
        "have": pop.get("have") or 0,
        "sources": [s["name"] for s in pop.get("sources") or []],
        "buttons": pop.get("sources") or [],       # ★ 带坐标，可点
        "boss": pop.get("boss") or "",
        "desc": pop.get("desc") or "",
    }
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
                    # boss→材料 对照：**游戏自己说的**（描述里「取自「XXX」」）
                    # 比手维护静态表可靠，每次读都是最新的。
                    try:
                        _boss = d.get("boss") or ""
                        if _boss:
                            from core import inventory as _inv2
                            _inv2.record(d["name"], int(d.get("have") or 0),
                                         source=f"{_boss} / " +
                                                "/".join(d.get("sources") or []))
                            _bm = BASE / "state" / "material_boss_map.json"
                            import json as _j3
                            _cur = {}
                            if _bm.exists():
                                try:
                                    _cur = _j3.loads(_bm.read_text(encoding="utf-8"))
                                except Exception:
                                    _cur = {}
                            _cur.setdefault("map", {})[d["name"]] = {
                                "boss": _boss,
                                "sources": d.get("sources") or [],
                            }
                            _bm.write_text(_j3.dumps(_cur, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
                    except Exception:
                        pass
                    # 顺手记库存 —— read_material 已经从弹窗读到「当前拥有 ×N」，
                    # 不记下来就白读了（inventory 是 P2 的数据层）。
                    try:
                        from core import inventory as _inv
                        _inv.record(d["name"], int(d.get("have") or 0),
                                    source="zzz_core material")
                    except Exception:
                        pass
            info["materials"] = mats
        out[key] = info
        print(f"  {key}: 被动={info['passive'] or '?'} "
              f"分支={len(info['branches'])} 材料={info['costs']} "
              f"{'已解锁' if info['unlocked'] else '前置未解锁'}")
    return out


def materials_ok(info: dict) -> tuple[bool, str]:
    """材料够不够。costs 是 [[有, 需], ...]。"""
    if not info.get("unlocked", True):
        return False, "前置天赋未解锁"
    costs = info.get("costs") or []
    if not costs:
        return False, "读不到材料需求"
    for have, need in costs:
        if have < need:
            return False, f"材料不足（{have}/{need}）"
    return True, "材料够"


def upgrade_one(ui: Ui, xy: tuple[int, int], key: str) -> tuple[bool, str]:
    """点开一个核心技圈 → 判断材料 → 升一次。返回 (成没成, 说明)。"""
    vs, inp = ui.vs, ui.inp
    vs.frame(force=True)
    inp.click(xy[0], xy[1], wait=1.8)
    vs.frame(force=True)
    txt = vs.text(R_PANEL)
    if "核心技" not in txt:
        return False, "面板没打开"

    info = parse_panel(txt + " " + vs.text(R_COST))
    ok, why = materials_ok(info)
    if not ok:
        return False, why

    c = vs.find("确定", (600, 780, 1600, 1000))
    if not c:
        c = vs.find("确定", (0, 0, 1920, 1080))
    if not c:
        return False, "找不到「确定」按钮"

    before = info.get("costs")
    inp.click(c["cx"], c["cy"], wait=1.8)
    vs.frame(force=True)

    txt2 = vs.text(R_PANEL)
    info2 = parse_panel(txt2 + " " + vs.text(R_COST))
    after = info2.get("costs")
    if after and before and after != before:
        return True, f"已升（{before} → {after}）"
    return False, "点了但没看到变化"


def do_upgrade(ui: Ui, m: Machine, agent: str, times: int) -> dict:
    """给 A~F 六个圈各升 times 次。"""
    vs, inp = ui.vs, ui.inp
    if not goto_skill_tab(ui, m, agent):
        return {"error": "到不了技能页"}

    live = locate.core_nodes(vs)
    if live:
        print(f"  核心技 OCR 定位到 {len(live)} 个圈")

    report = {}
    for key, xy in CORES.items():
        xy = live.get(key, xy)
        done = 0
        last = ""
        for _ in range(max(1, times)):
            ok, why = upgrade_one(ui, xy, key)
            last = why
            if ok:
                done += 1
                print(f"  {key} 圈：{why}")
            else:
                print(f"  {key} 圈：{why}" + (f"（本次已升 {done} 次）" if done else ""))
                break
            live2 = locate.core_nodes(vs)
            xy = live2.get(key, xy)
        report[key] = {"upgraded": done, "note": last}
        inp.key("esc", wait=1.2)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("read", "material", "upgrade"):
        p = sub.add_parser(c)
        p.add_argument("--agent", default=_DEFAULT_AGENT)
        if c == "material":
            p.add_argument("--goto", type=int, default=-1,
                           help="读完直接传送到第 N 个来源（0=第一个）")
        # **按角色分开存** —— 全局一份会让不同角色的核心技状态互相覆盖，
        # 更糟的是 farm_plan 会拿一个人的状态判断所有人（实跑踩过：
        # 佩洛伊斯 A~F 都解锁 → 所有角色的核心技缺口都不算）。
        p.add_argument("--out", default="")
        if c == "upgrade":
            p.add_argument("--times", type=int, default=1,
                           help="每个核心技最多升几次（默认 1）")
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

    if not args.out:
        args.out = str(BASE / "state" / f"core_status_{args.agent}.json")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    from core.state import stamp as _stamp
    Path(args.out).write_text(json.dumps(_stamp(data), ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\n已写入 {args.out}")
    if args.cmd == "upgrade":
        rep = do_upgrade(ui, m, args.agent, getattr(args, "times", 1) or 1)
        if rep.get("error"):
            print("\n" + rep["error"])
            return 3
        total = sum(v.get("upgraded", 0) for v in rep.values())
        print("\n=== 核心技升级结果 ===")
        for k, v in rep.items():
            print(f"  {k}: 升了 {v.get('upgraded', 0)} 次　{v.get('note', '')}")
        print(f"合计升了 {total} 次")
        if total == 0:
            print("  （一次都没升成 —— 材料不够或前置未解锁，看上面每圈的原因）")
        return 0

    # --goto N：直接传送到第 N 个来源（0=第一个）
    if args.cmd == "material" and getattr(args, "goto", -1) >= 0:
        from core import material_nav as _mnav2
        for _k, _v in data.items():
            if _k.startswith("_") or not isinstance(_v, dict):
                continue
            _mats = _v.get("materials") or []
            if not _mats:
                continue
            _m = _mats[0]
            print(f"\n=== 传送到「{_m['name']}」的第 {args.goto} 个来源 ===")
            # **必须从图标重新开弹窗** —— read_material 读完按了 ESC，
            # 缓存的按钮坐标已经失效（弹窗没了，点到的是下层界面）。
            _icon = (MAT_X[0], 926 + MAT_ICON_DY)
            _res = _mnav2.goto_by_icon(ui, _icon, args.goto)
            if _res:
                print(f"  ✔ 已到达：{_res}")
                return 0
            print("  ✘ 传送失败")
            return 4

    if args.cmd == "material":
        print("\n材料来源汇总：")
        for k, v in data.items():
            # **跳过元数据** —— stamp() 加的 _ts 是字符串，
            # 不加这个判断会炸 AttributeError: str has no attribute get（实测踩过）
            if k.startswith("_") or not isinstance(v, dict):
                continue
            for mat in v.get("materials") or []:
                print(f"  {mat['name']}（拥有{mat['have']}） → "
                      f"{' / '.join(mat['sources']) or '未读到来源'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())