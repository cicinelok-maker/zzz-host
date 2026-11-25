"""驱动盘每日养成 —— 为「长期每日」设计，不是一次性。

## 用户要求（2026-11-24）

「我打算驱动盘就是每天这样的长期养成，知道吧？不是一次性的。
就是能不能根据这样来优化整个驱动盘呢？」

## 和一次性流程的区别

一次性：刷本 → 判定 → 换装 → 结束

长期每日：
    ① 盘点现状（6 位号 + 有效词条 + 与目标差距）
    ② 库存评估（仓库候选按「当前值+升级潜力」排序）
    ③ 花电量（刷本出盘，按缺口选副本）
    ④ 训练（升最有潜力的 N 块，不是全升）
    ⑤ 换装（训练后重新算，更优才换）
    ⑥ 弃置拆解（全歪的回收母盘）
    ⑦ 调律（母盘补缺口位号）
    ⑧ 记账（写 progress.json，看趋势）
    ⑨ 汇报（发飞书，今天涨了多少）

## 关键设计

**每天只做「有意义的量」**
- 训练上限 `--train-n`（默认 3 块），不是把所有盘都升满
- 电量花到快见底就停（留 20 点缓冲）
- 刷本次数按电量算，不硬冲

**优先做「收益最高的那一件事」**
不是固定顺序，而是每轮算：
- 有高潜力盘待训练 → 训练
- 训练后比当前装备好 → 换装
- 有全歪盘 → 弃置拆解
- 有母盘且有空位/弱位号 → 调律
- 电量够且候选都不行 → 刷本

**记账看趋势**
每次跑完写一条 `progress.json`：
    {日期, 有效词条, 质量分, 6位号明细, 今日动作, 今日增量}
一周后能看出「每天涨多少」「卡在哪」。

## 用法

    python tools/zzz_disc_daily.py 佩洛伊斯              # 盘点+出计划
    python tools/zzz_disc_daily.py 佩洛伊斯 --run        # 真跑
    python tools/zzz_disc_daily.py 佩洛伊斯 --run --train-n 5
    python tools/zzz_disc_daily.py 佩洛伊斯 --report     # 看趋势
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core.game_cfg import DEFAULT_AGENT, COST_PATROL  # noqa: E402


from core.paths import one_dragon_python, one_dragon_env
PY = one_dragon_python()
ENV = one_dragon_env()
PROGRESS = BASE / "state" / "disc_progress.json"
META = HERE / "disc_meta.json"


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

OFFLINE = False     # --offline 时置 True：只读缓存，不碰游戏


def run(script: str, args: list[str], timeout: int = 3600) -> tuple[bool, str]:
    import os
    env = dict(os.environ)
    env.update(ENV)
    try:
        r = subprocess.run([PY, "-u", str(HERE / script)] + args,
                           cwd=str(BASE), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return False, "超时"


def _cached_int(key: str) -> int:
    """读 state/resource_cache.json 里的整数。没有返回 -1（表示未知，不是 0）。"""
    p = BASE / "state" / "resource_cache.json"
    if not p.exists():
        return -1
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        v = d.get(key)
        return int(v) if isinstance(v, (int, float)) else -1
    except Exception:
        return -1


def _age_text(agent: str) -> str:
    """status 文件是多久以前的。"""
    import time
    p = BASE / "state" / f"status_{agent}.json"
    if not p.exists():
        return "从没盘点过"
    sec = time.time() - p.stat().st_mtime
    if sec < 60:
        return f"{sec:.0f} 秒前"
    if sec < 3600:
        return f"{sec / 60:.0f} 分钟前"
    if sec < 86400:
        return f"{sec / 3600:.1f} 小时前"
    return f"{sec / 86400:.1f} 天前"


def offline_banner(agent: str) -> None:
    """离线模式横幅：把「数据多旧 / 什么不知道」说清楚。"""
    age = _age_text(agent)
    stale = "（可能已不准，建议刷新）" if "小时" in age or "天" in age else ""
    print()
    print("┌" + "─" * 60)
    print("│ 离线模式：只读缓存，没碰游戏")
    print(f"│ 状态：{age}{stale}")
    if _cached_int("battery") < 0:
        print("│ ⚠ 电量未知 —— 下面不会算电量预算")
        print("│   要知道：python tools/zzz_resource.py check")
    else:
        print(f"│ 电量：{_cached_int('battery')}（缓存）")
    if _cached_int("mother") < 0:
        print("│ ⚠ 母盘未知 —— 下面不会算能不能调律")
    else:
        print(f"│ 母盘：{_cached_int('mother')}（缓存）")
    print("└" + "─" * 60)


def read_status(agent: str) -> dict:
    """读 status 的 json。OFFLINE 时只读缓存，不跑 zzz_status。"""
    if not OFFLINE:
        ok, out = run("zzz_status.py", [agent, "--json"], 1800)
    p = BASE / "state" / f"status_{agent}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def read_mother() -> int:
    """读母盘数。走 zzz_resource --json。OFFLINE 时读缓存，返回 -1 表示未知。"""
    if OFFLINE:
        return _cached_int("mother")
    from core.charge_plan import read_battery_via_cli
    ok, out = run("zzz_resource.py", ["check", "--json"], 1200)
    import json as _j
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith('{"ok"'):
            try:
                d = _j.loads(line)
                v = (d.get("data") or {}).get("mother_discs")
                return int(v) if isinstance(v, int) and v >= 0 else -1
            except Exception:
                pass
    return -1


def read_battery() -> int:
    """读电量。OFFLINE 时读缓存，返回 -1 表示未知（**不是 0**）。"""
    if OFFLINE:
        return _cached_int("battery")
    from core.charge_plan import read_battery_via_cli
    return read_battery_via_cli(PY, str(HERE / "zzz_resource.py"), str(BASE))


# 角色配置统一从 core.agent_cfg 取（带职业模板回退）。
# 别再在这里写一个同名函数 —— 会遮蔽真正的实现。
from core.agent_cfg import cfg_of  # noqa: E402


def grade(total: float) -> tuple[str, float]:
    """离小毕业还差多少。"""
    from core.disc_cfg import THRESHOLDS
    target = THRESHOLDS["graduation"]
    return ("已达成" if total >= target else "未达成"), round(target - total, 1)


def load_progress() -> list:
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def append_progress(rec: dict) -> None:
    data = load_progress()
    data.append(rec)
    PROGRESS.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")


def show_report() -> int:
    data = load_progress()
    if not data:
        print("还没有记录。跑一次 `zzz_disc_daily.py <角色> --run` 就会开始记。")
        return 0
    print(f"{'日期':<20}{'有效条':>7}{'质量分':>8}{'增量':>7}  动作")
    print("-" * 70)
    prev = None
    for r in data:
        inc = "" if prev is None else f"{r['质量分'] - prev:+.1f}"
        print(f"{r['ts']:<20}{r['蓝条']:>7}{r['质量分']:>8}{inc:>7}  "
              f"{','.join(r.get('动作') or []) or '-'}")
        prev = r["质量分"]
    if len(data) >= 2:
        first, last = data[0]["质量分"], data[-1]["质量分"]
        days = len({r["ts"][:10] for r in data})
        print(f"\n共 {days} 天，{first} → {last}（{last - first:+.1f}）")
        if days > 1:
            print(f"平均每天 {(last - first) / (days - 1):+.2f} 分")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-unknown", action="store_true",
                    help="角色不在库里也继续（按强攻模板判定，可能不准）")
    ap.add_argument("agent", nargs="?", default=DEFAULT_AGENT)
    ap.add_argument("--run", action="store_true", help="真跑（默认只出计划）")
    ap.add_argument("--no-farm", action="store_true",
                    help="跳过刷本（由外层总编排统一刷）")
    ap.add_argument("--train-n", type=int, default=3, help="每天最多训练几块盘")
    ap.add_argument("--batch-n", type=int, default=2, help="每天最多刷几次本")
    ap.add_argument("--offline", action="store_true",
                    help="只读缓存不碰游戏（秒出，数据可能过期）")
    ap.add_argument("--report", action="store_true", help="看历史趋势")
    ap.add_argument("--keep-battery", type=int, default=20, help="留多少电量不用")
    ap.add_argument("--need-skill", action="store_true", help="技能材料也不够")
    ap.add_argument("--need-core", action="store_true", help="核心技材料也不够")
    args = ap.parse_args()

    global OFFLINE
    OFFLINE = bool(getattr(args, "offline", False))
    if OFFLINE:
        offline_banner(args.agent)
    # 角色名校验：能纠正就纠正，纠正不了就退出（不静默走默认）
    try:
        from core.agent_cfg import resolve_agent
        _canon = resolve_agent(args.agent,
                               allow_unknown=args.force_unknown)
        if _canon != args.agent:
            print(f"（角色名「{args.agent}」→「{_canon}」）")
            args.agent = _canon
        from core.agent_cfg import is_known
        if not is_known(args.agent):
            _warn_unknown(args.agent)
    except Exception as _e:
        print(f"✘ {_e}")
        return 3


    if args.report:
        return show_report()

    print("=" * 64)
    print(f"驱动盘每日养成：{args.agent}")
    print("=" * 64)

    # ---- ① 盘点 ----
    st = read_status(args.agent)
    slots = st.get("slots") or []
    blue = sum(s.get("blue") or 0 for s in slots)
    total = round(sum(s.get("eff") or 0 for s in slots), 1)
    occupied = len([s for s in slots if s.get("set")])
    _unread = st.get("unread") or []
    print(f"\n① 盘点")
    print(f"   位号 {occupied}/6　有效副词条 {blue} 条　质量分 {total}")
    for s in slots:
        _slot = s.get("slot")
        if _slot in _unread:
            print(f"     {_slot}号位 ⚠ 读取失败（不是空位，重跑一次）")
            continue
        print(f"     {_slot}号位 {s.get('set') or '空':<8} Lv{s.get('level') or 0:<2} "
              f"有效 {s.get('eff') or 0}　蓝{s.get('blue') or 0}")
    if _unread:
        print(f"\n   ⚠ {len(_unread)} 个位号读取失败：{_unread}")
        print(f"     下面的数字和建议都不准，先重跑：")
        print(f"       python tools/zzz_status.py {args.agent} --json")
    g, gap = grade(total)
    print(f"   目标 28 条（口径B）→ {g}，还差 {gap}")

    actions = []

    # ---- ② 库存评估 ----
    print(f"\n② 库存评估（按潜力排序）")
    cfg = cfg_of(args.agent)
    main_set = cfg.get("四件套", "")
    print(f"   本套：{main_set}")
    print(f"   （详细候选扫描要跑 zzz_disc_v2，这里只给结论）")

    # ---- ③ 电量 ----
    battery = read_battery()
    print(f"\n③ 电量规划")
    # battery == -1 表示「未知」（离线且没缓存）。**不能让哨兵值进算术** ——
    # 那样会算出「距满 241 点」「够刷 -1 次」这种鬼话。
    if battery < 0:
        print("   电量未知 —— 离线模式且没有缓存")
        print("   要算电量预算：python tools/zzz_resource.py check")
        can_farm = False
    else:
        from core.charge_plan import report as _creport
        for line in _creport(battery).splitlines():
            print(f"   {line}")
        can_farm = battery >= COST_PATROL + args.keep_battery

    # 按缺口算今天该刷哪个本
    print(f"\n③b 按缺口分配")
    if battery < 0:
        print("   跳过（电量未知，算不出能刷几次）")
        print("   先跑：python tools/zzz_resource.py check")
    else:
        from core.farm_gap import plan as _fplan, report as _freport
        _slots = [{"slot": s.get("slot"), "set": s.get("set"),
                   "main": s.get("main"), "eff": s.get("eff")} for s in slots]
        _fp = _fplan(args.agent, _slots, battery,
                     need_skill=args.need_skill, need_core=args.need_core)
        for line in _freport(_fp).splitlines():
            print(f"   {line}")

    # ---- 决策：优先做收益最高的事 ----
    print(f"\n④ 今日动作建议")
    plan = []
    # 用缺口分析（含主词条判定），不是只看有效值
    _bad_main = [s["slot"] for s in slots
                 if s.get("main_verdict") == "bad"]
    _unknown = [s["slot"] for s in slots
                if s.get("main_verdict") == "unknown"]
    # 空位要排除「读失败」的（否则会去补一个本来不空的位号）
    empty = [s for s in slots
             if not s.get("set") and (s.get("slot") not in _unread)]
    weak = [s for s in slots
            if s.get("main_verdict") != "bad"
            and (s.get("eff") or 0) < 2.0 and s.get("set")]

    if _bad_main:
        plan.append(f"★ 先把 {_bad_main} 号位的主词条换对"
                    f"（优先级最高，一块盘就 +30% 乘区）")
    if _unknown:
        plan.append(f"  {_unknown} 号位主词条读不到，先查清楚")
    if empty:
        plan.append(f"补齐空位 {[s['slot'] for s in empty]}（调律或换装）")
    if weak:
        plan.append(f"训练弱位号 {[s['slot'] for s in weak]}（有效<2.0）")
    if args.no_farm:
        plan.append("刷本由外层总编排统一做（--no-farm）")
        can_farm = False
    if can_farm:
        plan.append(f"刷本 {min(args.batch_n, (battery - args.keep_battery) // COST_PATROL)} 次出盘")
    plan.append("弃置全歪盘 → 拆解 → 攒母盘")

    # 调律：用 tune_plan 算「这个位号值不值得花母盘」
    from core.tune_plan import plan_tune
    _mother = read_mother()          # 母盘数
    _tune = plan_tune(slots, max(_mother, 0))
    if _tune["targets"]:
        plan.append(f"调律 {len(_tune['targets'])} 个位号"
                    f"（{[t['slot'] for t in _tune['targets']]}）"
                    f"　母盘 {_mother}")
    else:
        plan.append(f"不调律（{_tune['verdict']}）")

    for i, p in enumerate(plan, 1):
        print(f"   {i}. {p}")

    if _unread:
        print(f"\n   ⚠ 先解决读取失败再动游戏（否则会基于错数据操作）")
        return 2

    if not args.run:
        print(f"\n（计划模式。加 --run 真跑）")
        return 0

    # ---- 真跑 ----
    import os
    os.environ.update(ENV)
    print(f"\n⑤ 执行")

    if can_farm:
        n = min(args.batch_n, (battery - args.keep_battery) // COST_PATROL)
        print(f"   刷本 {n} 次…")
        # 关键：--patrol 要传**副本名**（机师与叛甲/高塔与巨炮），
        # 不是套装名（拂晓行纪）。传错套装名会静默失败、电量一点不扣。
        # 优先用按缺口算出来的副本
        dungeon = "机师与叛甲"
        if _fp.get("farms"):
            dungeon = _fp["farms"][0]["dungeon"]
        print(f"   副本：{dungeon}（{len(dungeons)} 个候选）")
        ok, out = run("od_material_farm.py",
                      ["--patrol", dungeon, "--times", str(n), "--run"], 5400)
        if "挑战完成" not in out:
            print("   ⚠ 刷本可能没真跑（没看到「挑战完成」）")
        actions.append("刷本" if ok else "刷本失败")

    print(f"   训练潜力最高的 {args.train_n} 块…")
    ok, out = run("zzz_disc_train.py",
                  [args.agent, "--train", "--max-steps", "6"], 3600)
    actions.append("训练" if ok else "训练失败")

    print(f"   换装决策…")
    ok, out = run("zzz_plan.py", [args.agent, "--apply"], 3000)
    actions.append("换装" if ok else "换装跳过")

    # 调律（母盘够 + 有目标时才跑）
    if _tune["targets"]:
        # 关键：套装要用 zzz_plan 算出来的「目标套装」，不是「当前套装」。
        # 4 号位当前可能是拂晓、但目标应该是啄木鸟（凑 4+2 的副套）。
        # 用错套装 = 6 个母盘白花。
        _plan_sets = {}
        _pp = BASE / "state" / "plan.json"
        if _pp.exists():
            try:
                import json as _j
                _pd = _j.loads(_pp.read_text(encoding="utf-8"))
                for _it in (_pd.get("plan") or []):
                    if _it.get("slot") and _it.get("set"):
                        _plan_sets[int(_it["slot"])] = _it["set"]
                print(f"   目标套装（来自 zzz_plan）：{_plan_sets}")
            except Exception as _e:
                print(f"   ⚠ 读 plan.json 失败：{_e}，退回当前套装")

        for _t in _tune["targets"]:
            _slot = _t["slot"]
            _cur = next((x.get("set") for x in slots if x.get("slot") == _slot), "")
            _want = _plan_sets.get(_slot) or _cur or _cfg.get("四件套") or ""
            if not _want:
                print(f"   {_slot}号位：不知道要哪个套装，跳过调律")
                continue
            if _cur and _cur != _want:
                print(f"   {_slot}号位：当前 {_cur}，目标 {_want} "
                      f"→ 调「{_want}」")
            print(f"   调律 {_want} {_slot}号位（{_t['reason'][:30]}）…")
            ok_t, out_t = run("zzz_tune.py",
                              [_want, "--slot", str(_slot), "--times", "1"],
                              3600)
            if "调律获得" in out_t or "定向" in out_t:
                print(f"      ✔ 已调")
            else:
                print(f"      ⚠ 没看到产出，可能母盘不足或界面不对")

    print(f"   训盘并回收（判废→拆解）…")
    ok, out = run("zzz_disc_cycle.py",
                  [args.agent, "--train", "--recycle"], 3600)
    actions.append("回收" if ok else "回收跳过")

    # ---- ⑧ 记账 ----
    st2 = read_status(args.agent)
    slots2 = st2.get("slots") or []
    blue2 = sum(s.get("blue") or 0 for s in slots2)
    total2 = round(sum(s.get("eff") or 0 for s in slots2), 1)
    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "agent": args.agent,
        "蓝条": blue2,
        "质量分": total2,
        "动作": actions,
        "位号": [{"slot": s["slot"], "set": s.get("set"),
                  "eff": s.get("eff"), "blue": s.get("blue")} for s in slots2],
    }
    append_progress(rec)

    print(f"\n⑨ 今日成果")
    print(f"   有效副词条 {blue} → {blue2}（{blue2 - blue:+d}）")
    print(f"   质量分 {total} → {total2}（{total2 - total:+.1f}）")
    print(f"   已记入 {PROGRESS.name}")

    # 汇报
    try:
        if (HERE / "feishu.py").exists():
            run("feishu.py", [
            "send",
            f"【驱动盘日报】{args.agent}\n"
            f"有效副词条 {blue} → {blue2}（{blue2 - blue:+d}）\n"
            f"质量分 {total} → {total2}（{total2 - total:+.1f}）\n"
            f"距小毕业 28 还差 {round(28 - total2, 1)}\n"
            f"今日动作：{'、'.join(actions)}",
        ], 120)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())