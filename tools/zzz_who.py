"""角色选择器：列出所有能养的角色 + 各自进度，用来「点名字」。

## 用户 2026-11-25

> 现在大闭环做完是不是我点一个角色的名，然后就能每日这样的定时养成，
> 直到他完全毕业

**原来没有这个入口** —— 只能 `python tools/zzz_daily.py <角色名> --run`，
得自己记住 64 个名字。

## 这个工具干什么

```
python tools/zzz_who.py                 列出所有角色 + 进度（不联网）
python tools/zzz_who.py 佩洛伊斯         看一个角色的详情和建议
python tools/zzz_who.py --ready         只列「还有提升空间」的
python tools/zzz_who.py --graduated     只列「已毕业」的
```

## 进度从哪来

`state/status_<角色>.json`（`zzz_status` 写的）。
没有状态文件的角色标「未盘点」。

**不联网、不碰游戏**，纯本地读文件，秒出。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core.agent_cfg import cfg_of, known, element_of  # noqa: E402
from core.disc_cfg import THRESHOLDS  # noqa: E402

STATE = BASE / "state"
GRAD = THRESHOLDS["graduation"]
COMBAT = THRESHOLDS["combat_ready"]
MAXT = THRESHOLDS["max"]


def _warn_unknown(agent: str) -> None:
    """角色不在库里时的警告。说清「哪里不准」和「怎么补」。"""
    print()
    print("=" * 66)
    print(f"⚠ 「{agent}」不在角色库里（disc_meta.json）")
    print("="  * 66)
    print("  · 仍然会读取：装备、等级、副词条、质量分 —— 这些不依赖配装知识")
    print("  · 会不准的：「主词条对不对」按【强攻】模板判定")
    print("  · 补数据：在 tools/disc_meta.json 的「角色」下加一段，")
    print(f"      至少给「定位」和「属性」，例如：")
    print(f'        "{agent}": {{"定位": "强攻", "属性": "以太"}}')
    print("=" * 66)
    print()

def status_of(agent: str) -> dict | None:
    """读 status 文件。没有返回 None。"""
    p = STATE / f"status_{agent}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def progress_of(agent: str) -> dict:
    """返回 {total, blue, slots, 已盘点, 缺口}。"""
    st = status_of(agent)
    if not st:
        return {"盘点": False, "total": 0.0, "blue": 0,
                "bad_main": [], "empty": [], "weak": []}
    slots = st.get("slots") or []
    unread = set(st.get("unread") or [])
    total = round(sum((s.get("eff") or 0) for s in slots), 1)
    blue = sum((s.get("blue") or 0) for s in slots)
    bad = [s["slot"] for s in slots
           if s.get("main_verdict") == "bad" and s["slot"] not in unread]
    empty = [s["slot"] for s in slots
             if not s.get("set") and s["slot"] not in unread]
    weak = [s["slot"] for s in slots
            if s.get("main_verdict") != "bad" and s.get("set")
            and (s.get("eff") or 0) < 2.0 and s["slot"] not in unread]
    return {"盘点": True, "total": total, "blue": blue,
            "bad_main": bad, "empty": empty, "weak": weak,
            "unread": sorted(unread)}


def tier(total: float) -> tuple[str, str]:
    """(等级, 图标)。"""
    if total >= MAXT:
        return "大毕业", "★★★"
    if total >= COMBAT:
        return "实战够用", "★★"
    if total >= GRAD:
        return "小毕业", "★"
    return "未毕业", "·"


def list_all(only: str = "") -> int:
    rows = []
    for n in known():
        pr = progress_of(n)
        t, mark = tier(pr["total"])
        rows.append((n, pr, t, mark))

    # 排序：已盘点的按分数降序，未盘点的排后面
    rows.sort(key=lambda x: (not x[1]["盘点"], -x[1]["total"]))
    if only == "ready":
        rows = [r for r in rows if r[1]["盘点"] and r[1]["total"] < GRAD]
    elif only == "graduated":
        rows = [r for r in rows if r[1]["盘点"] and r[1]["total"] >= GRAD]

    print("=" * 78)
    print(f"角色养成进度　（小毕业线 {GRAD} / 实战 {COMBAT} / 大毕业 {MAXT}）")
    print("=" * 78)
    print(f"{'角色':<12}{'定位':<6}{'属性':<6}{'质量分':<8}{'蓝条':<5}{'阶段':<10}{'缺口'}")
    print("-" * 78)
    for n, pr, t, mark in rows:
        c = cfg_of(n)
        elem = element_of(n) or "?"
        if not pr["盘点"]:
            print(f"{n:<12}{c['定位']:<6}{elem:<6}{'—':<8}{'—':<5}{'未盘点':<10}")
            continue
        gap = []
        if pr["bad_main"]:
            gap.append(f"主词条×{len(pr['bad_main'])}")
        if pr["empty"]:
            gap.append(f"空位×{len(pr['empty'])}")
        if pr["weak"]:
            gap.append(f"弱位×{len(pr['weak'])}")
        if pr.get("unread"):
            gap.append(f"读失败×{len(pr['unread'])}")
        print(f"{n:<12}{c['定位']:<6}{elem:<6}{pr['total']:<8}{pr['blue']:<5}"
              f"{mark + t:<10}{' '.join(gap) or '—'}")

    n_ready = sum(1 for r in rows if r[1]["盘点"])
    print()
    print(f"  共 {len(rows)} 个　已盘点 {n_ready} 个")
    if n_ready:
        print(f"  下一步：python tools/zzz_daily.py <角色名> --run")
    return 0


def detail(agent: str, force_unknown: bool = False) -> int:
    # 角色名校验：能纠正就纠正，纠正不了就报错（exit 3）
    try:
        from core.agent_cfg import resolve_agent
        n = resolve_agent(agent, allow_unknown=force_unknown)
        if n != agent:
            print(f"（「{agent}」→「{n}」）")
    except Exception as e:
        print(f"✘ {e}")
        return 3
    # 不在库里就明确警告（说清哪不准、怎么补）
    from core.agent_cfg import is_known
    if not is_known(n):
        _warn_unknown(n)
    # 用**纠正后**的名字取配置（否则又会走模板回退，白纠正）
    c = cfg_of(n, warn=False)
    pr = progress_of(n)
    print("=" * 70)
    print(f"「{n}」")
    print("=" * 70)
    print(f"  定位   {c['定位']}")
    print(f"  属性   {element_of(n) or '?'}")
    print(f"  四件套 {c.get('四件套') or '—'}  +  "
          f"{(c.get('两件套候选') or ['—'])[0]}")
    print(f"  4/5/6  {c['主词条'].get('4')} / {c['主词条'].get('5')} / "
          f"{c['主词条'].get('6')}")
    print(f"  有效   {c['有效副词条']}")
    print()

    if not pr["盘点"]:
        print("  ⚠ 还没盘点过。先跑：")
        print(f"     python tools/zzz_status.py {n} --json")
        return 0

    t, mark = tier(pr["total"])
    print(f"  质量分 {pr['total']}　蓝条 {pr['blue']}　{mark} {t}")
    print(f"  距小毕业还差 {round(GRAD - pr['total'], 1)}")
    print()
    if pr["bad_main"]:
        print(f"  ★ 主词条错：{pr['bad_main']}（优先换）")
    if pr["empty"]:
        print(f"  · 空位：{pr['empty']}")
    if pr["weak"]:
        print(f"  · 弱位号：{pr['weak']}")
    if pr.get("unread"):
        print(f"  ⚠ 读取失败：{pr['unread']}（重跑 status）")
    if not (pr["bad_main"] or pr["empty"] or pr["weak"]):
        print("  ✔ 没有明显缺口")
    print()
    print(f"  养成一轮：python tools/zzz_daily.py {n} --run")
    print(f"  跑到毕业：python tools/zzz_grind.py {n} --run --target {GRAD}")
    return 0


# ============================================================ 账号角色扫描

ROSTER = STATE / "agent_roster.json"


def load_roster() -> dict:
    """读扫出来的账号角色表 {名字: 等级}。"""
    if not ROSTER.exists():
        return {}
    try:
        return json.loads(ROSTER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def do_scan() -> int:
    """扫账号上有哪些角色，写 state/agent_roster.json。需要游戏开着。"""
    try:
        from core import Vision, Input, Ui
        from core.machine import Machine
        from pick_agent import list_agents
    except Exception as e:
        print(f"✘ 加载失败：{e}")
        return 2

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)

    print("扫代理人列表…（可能需要 30~60 秒）")
    roster = list_agents(ui, m)
    if not roster:
        print("✘ 一个也没扫到。检查：游戏开着吗？在 1920x1080 吗？")
        print("   先跑：python tools/zzz_launch.py")
        return 4

    STATE.mkdir(parents=True, exist_ok=True)
    ROSTER.write_text(json.dumps(roster, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(f"✔ 扫到 {len(roster)} 个角色，已写入 state/agent_roster.json")
    print()
    return show_menu()


def show_menu(roster: dict | None = None) -> int:
    """输出聊天友好的菜单：一行一个角色，带序号和进度。"""
    if roster is None:
        roster = load_roster()

    if not roster:
        # 没扫过：退化成列角色库，并提示要先扫
        print("还没扫过账号角色。先跑：")
        print("  python tools/zzz_who.py --scan")
        print()
        print("（下面是角色库里的全部角色，不代表你的账号有这些）")
        print()
        names = known()
        for i, n in enumerate(names, 1):
            c = cfg_of(n)
            print(f"{i:>2}. {n}　{c['定位']}·{element_of(n) or '?'}")
        return 2

    # 有 roster：按进度排，未盘点排后面
    rows = []
    for n in roster:
        pr = progress_of(n)
        t, mark = tier(pr["total"])
        rows.append((n, pr, t, mark))
    rows.sort(key=lambda x: (not x[1]["盘点"], -x[1]["total"]))

    print(f"你的账号有 {len(rows)} 个角色：")
    print()
    for i, (n, pr, t, mark) in enumerate(rows, 1):
        c = cfg_of(n)
        role = f"{c['定位']}·{element_of(n) or '?'}"
        if not pr["盘点"]:
            print(f"{i:>2}. {n}　{role}　未盘点")
            continue
        gap = []
        if pr["bad_main"]:
            gap.append(f"主词条错{len(pr['bad_main'])}个")
        if pr["empty"]:
            gap.append(f"空位{len(pr['empty'])}个")
        tail = ("　" + " ".join(gap)) if gap else ""
        print(f"{i:>2}. {n}　{role}　{pr['total']:.1f}/{GRAD:g}　{mark}{t}{tail}")

    print()
    print("要养哪个？直接说名字就行（例如「养佩洛伊斯」）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="角色养成进度一览")
    ap.add_argument("--force-unknown", action="store_true",
                    help="角色不在库里也继续（按强攻模板判定，可能不准）")
    ap.add_argument("agent", nargs="?", help="看某个角色的详情")
    ap.add_argument("--ready", action="store_true", help="只列未毕业的")
    ap.add_argument("--graduated", action="store_true", help="只列已毕业的")
    ap.add_argument("--scan", action="store_true",
                    help="扫账号上有哪些角色（需游戏开着）")
    ap.add_argument("--menu", action="store_true",
                    help="输出聊天友好的角色菜单")
    args = ap.parse_args()

    if args.scan:
        return do_scan()
    if args.menu:
        return show_menu()
    if args.agent:
        return detail(args.agent, force_unknown=args.force_unknown)
    only = "ready" if args.ready else ("graduated" if args.graduated else "")
    return list_all(only)


if __name__ == "__main__":
    sys.exit(main())