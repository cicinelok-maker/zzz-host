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

from core import atomic as _aw
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

    # **耗时估计要照实写**（2026-11-27 实测 342 秒）。
    #
    # 原来写「30~60 秒」—— 差了 5~10 倍。用户等 1 分钟就开始怀疑卡死，
    # 而实际要将近 6 分钟：列表要滚 10+ 轮，每轮一次网格 OCR + 一次界面判定。
    print("扫代理人列表…（实测约 6 分钟：要滚 10+ 屏，每屏都要 OCR）")
    print("  （中途可以按 Ctrl+C，已扫到的会保留在文件里）")
    roster = list_agents(ui, m)
    if not roster:
        print("✘ 一个也没扫到。检查：游戏开着吗？在 1920x1080 吗？")
        print("   先跑：python tools/zzz_launch.py")
        return 4

    STATE.mkdir(parents=True, exist_ok=True)
    _aw.write_json(ROSTER, roster, indent=1)
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
        print()
        print("以上是**角色库**（64 个），不是你的账号角色。")
        print("要看账号上实际有哪些：python tools/zzz_who.py --scan")
        # exit 0：输出是有用内容。exit 2 表示「配置缺失/参数错误」，
        # 那会让 agent 当成失败去重试（朋友报的 bug A）。
        return 0

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


# ============================================================ 进度曲线

PROGRESS = STATE / "disc_progress.json"


def _load_progress(agent: str) -> list[dict]:
    """读 disc_progress.json 里这个角色的记录，按时间排序。"""
    if not PROGRESS.exists():
        return []
    _txt = PROGRESS.read_text(encoding="utf-8", errors="replace")
    if not _txt.strip():
        return []
    try:
        d = json.loads(_txt)
    except Exception as e:
        # **坏文件要说一声**（BUG-067 的同一个毛病）。
        print(f"  ⚠ {PROGRESS.name} 读不了（{e}）—— 历史显示为空")
        return []

    # **`d` 可能不是 list**（BUG-076）。
    #
    # `disc_progress.json` 的约定是 list，但历史上/别处写过 dict 形态。
    # 而 `for x in d` 在 dict 上迭代的是**键字符串** ——
    # `isinstance(x, dict)` 全假 → rows 恒空 → 历史**永远显示「还没有记录」**。
    # 用户只会觉得「我的记录丢了」。
    if isinstance(d, dict):
        # 常见形状：{"records": [...]} / {"<角色名>": [...]} / 单条记录
        for _key in ("records", "history", "items", "data"):
            if isinstance(d.get(_key), list):
                d = d[_key]
                break
        else:
            _v = d.get(agent)
            if isinstance(_v, list):
                d = _v
            elif "agent" in d or "质量分" in d:
                d = [d]          # 整个文件就是一条记录
            else:
                print(f"  ⚠ {PROGRESS.name} 是对象而不是列表，认不出记录在哪 —— 历史为空")
                return []
    if not isinstance(d, list):
        print(f"  ⚠ {PROGRESS.name} 的内容是 {type(d).__name__}，不是列表 —— 历史为空")
        return []
    rows = [x for x in d if isinstance(x, dict) and x.get("agent") == agent]
    rows.sort(key=lambda x: str(x.get("ts") or ""))
    return rows


def _parse_ts(ts: str):
    from datetime import datetime
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _bar(val: float, target: float, width: int = 14) -> str:
    """进度条。超过目标就全满。"""
    if target <= 0:
        return "░" * width
    n = int(round(min(val / target, 1.0) * width))
    return "█" * n + "░" * (width - n)


def history(agent: str) -> int:
    """打印一个角色的养成历史。"""
    rows = _load_progress(agent)
    print("=" * 66)
    print(f"{agent}　养成历史")
    print("=" * 66)

    if not rows:
        print()
        print(f"  还没有记录。跑一轮就有：")
        print(f"     python tools/zzz_daily.py {agent} --run")
        print()
        print("  （记录写在 state/disc_progress.json，每跑一轮追加一条）")
        return 0

    if len(rows) == 1:
        r = rows[0]
        print()
        print(f"  只有 1 条记录（{r.get('ts')}）：{r.get('质量分')} 分")
        print(f"  再跑一轮就能看到变化了。")
        return 0

    # ---- 曲线
    first = rows[0].get("质量分") or 0
    print()
    prev = None
    for r in rows:
        ts = str(r.get("ts") or "")[5:16]
        sc = r.get("质量分") or 0
        blue = r.get("蓝条") or 0
        line = f"  {ts}   {sc:>5.1f}   {_bar(sc, GRAD)}  蓝{blue}"
        if prev is not None:
            d = sc - prev
            if abs(d) > 0.05:
                line += f"   {'▲ +' if d > 0 else '▼ '}{d:.1f}"
        print(line)
        prev = sc

    # ---- 汇总
    last = rows[-1]
    now = last.get("质量分") or 0
    gain = now - first
    print()
    print("-" * 66)
    print(f"  起点 {first:.1f} → 现在 {now:.1f}，{'涨了' if gain >= 0 else '掉了'} {abs(gain):.1f}")

    t0, t1 = _parse_ts(str(rows[0].get("ts") or "")), _parse_ts(str(last.get("ts") or ""))
    if t0 and t1 and t1 > t0:
        days = (t1 - t0).total_seconds() / 86400
        rate = gain / days if days > 0 else 0
        if days < 1:
            print(f"  {days * 24:.1f} 小时涨 {gain:.1f} → 约 {rate:.2f} 分/天")
        else:
            print(f"  {days:.1f} 天涨 {gain:.1f} → 约 {rate:.2f} 分/天")
        if now < GRAD and rate > 0.01:
            eta = (GRAD - now) / rate
            print(f"  距小毕业 {GRAD:g} 还差 {GRAD - now:.1f}，按这个速度约 {eta:.1f} 天")
        elif now >= GRAD:
            print(f"  ✔ 已过小毕业线 {GRAD:g}")
        # 样本少时外推不可靠：一轮里可能同时做了换装+训练+刷本，
        # 那不是可持续的日速率
        if len(rows) <= 3:
            print()
            print(f"  ⚠ 只有 {len(rows)} 条记录，上面的「分/天」是从单次跳跃外推的")
            print("     一次大改造（同时换装+训练+刷本）不是每天都能做到")
            print("     攒够 5 条以上再看速率才准")

    # ---- 位号变化（只报有变化的）
    s0 = {x.get("slot"): x for x in (rows[0].get("位号") or [])}
    s1 = {x.get("slot"): x for x in (last.get("位号") or [])}
    changes = []
    for slot in sorted(set(s0) | set(s1)):
        a, b = s0.get(slot) or {}, s1.get(slot) or {}
        ea, eb = a.get("eff") or 0, b.get("eff") or 0
        if abs(eb - ea) > 0.05:
            sa, sb = a.get("set") or "—", b.get("set") or "—"
            note = ""
            if sa != sb:
                note = f"（{sa} → {sb}）"
            changes.append((slot, ea, eb, eb - ea, note))
    if changes:
        print()
        print("  位号变化：")
        for slot, ea, eb, d, note in changes:
            arrow = "▲ +" if d > 0 else "▼ "
            print(f"    {slot}号位  {ea:.1f} → {eb:.1f}   {arrow}{abs(d):.1f} {note}")

    # ---- 动作历史
    acts = []
    for r in rows:
        a = r.get("动作") or []
        if a:
            acts.append(f"{str(r.get('ts'))[5:16]} {'/'.join(map(str, a))}")
    if acts:
        print()
        print("  每轮做了什么：")
        for a in acts[-8:]:
            print(f"    {a}")
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
    ap.add_argument("--history", action="store_true",
                    help="看养成进度曲线（配合角色名）")
    ap.add_argument("--add-agent", default="",
                        help="把一个角色加进本地覆盖层（不改发布集）")
    ap.add_argument("--role", default="", help="配合 --add-agent：定位")
    ap.add_argument("--element", default="", help="配合 --add-agent：属性")
    args = ap.parse_args()

    # --add-agent：加进本地覆盖层（state/characters.local.json）
    if args.add_agent:
        from core import characters as _chars
        _c = {}
        if args.role:
            _c["定位"] = args.role
        if args.element:
            _c["属性"] = args.element
        if not _c:
            print("至少给 --role 和 --element")
            print("  例：python tools/zzz_who.py --add-agent 新角色 --role 异常 --element 以太")
            return 2
        print(_chars.add(args.add_agent, _c))
        print()
        print("有效副词条/主词条/套装还没填，缺口判定会用职业模板兜底。")
        print(f"要更准就编辑 {_chars.LOCAL}")
        return 0

    if args.history:
        if not args.agent:
            print("要指定角色：python tools/zzz_who.py 佩洛伊斯 --history")
            return 2
        try:
            from core.agent_cfg import resolve_agent
            n = resolve_agent(args.agent, allow_unknown=args.force_unknown)
        except Exception as e:
            print(f"✘ {e}")
            return 3
        return history(n)
    if args.scan:
        return do_scan()
    if args.menu:
        return show_menu()
    if args.agent:
        # **别静默忽略 --ready / --graduated**（BUG-056）。
        #
        # 这两个是「列名单」用的过滤器，和「看某个角色详情」是两条路。
        # 原来的顺序是 `if args.agent: return detail(...)` 在前，
        # 于是 `zzz_who 佩洛伊斯 --ready` 里那个 `--ready` **什么都不做** ——
        # 用户以为加了过滤，其实看的是详情。
        if args.ready or args.graduated:
            _f = "--ready" if args.ready else "--graduated"
            print(f"⚠ 指定了角色「{args.agent}」，{_f} 这个过滤不生效")
            print(f"   要看名单：python tools/zzz_who.py {_f}")
            print(f"   要看详情：python tools/zzz_who.py {args.agent}")
            print()
        return detail(args.agent, force_unknown=args.force_unknown)
    only = "ready" if args.ready else ("graduated" if args.graduated else "")
    return list_all(only)


if __name__ == "__main__":
    sys.exit(main())