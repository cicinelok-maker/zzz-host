"""养成总控：一次跑完所有能做的养成动作。

## 顺序设计

按「不消耗稀缺资源 → 消耗」排：

    1. 音擎强化 + 改装      只吃蓄电池/丁尼，最便宜
    2. 角色等级培训 + 晋升   只吃调查员记录/认证章
    3. 技能转化 + 升级       吃认证章
    4. 核心技                （未打通，跳过）
    5. 驱动盘：换装决策      不消耗资源，只是换上更好的
    6. 驱动盘：升级          吃镀剂
    7. 刷本 + 拆解           吃电量，产出新盘和材料

每一步失败不影响后面的。

## 用法

    python tools/zzz_daily.py 佩洛伊斯              # 只出计划
    python tools/zzz_daily.py 佩洛伊斯 --run        # 真跑
    python tools/zzz_daily.py 佩洛伊斯 --run --no-farm   # 不刷本
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))
from core.game_cfg import FARM_COST  # 唯一权威来源（core/game_cfg.py）

from core.paths import one_dragon_python, one_dragon_env
PY = one_dragon_python()
ENV = one_dragon_env()
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

def run(name: str, args: list[str], timeout: int = 1800,
        quiet: bool = False) -> tuple[bool, str]:
    env = dict(os.environ)
    env.update(ENV)
    t0 = time.time()
    print(f"\n--- {name} ---", flush=True)
    try:
        r = subprocess.run([PY, "-u"] + args, cwd=str(BASE), env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        ok = r.returncode == 0
        print(f"  {'OK' if ok else 'NG'}  {time.time() - t0:.0f}s  rc={r.returncode}")
        if not ok:
            tail = [l for l in out.splitlines()
                    if l.strip() and "INFO" not in l and not l.startswith("[")]
            for l in tail[-4:]:
                print(f"    {l.strip()[:100]}")
        return ok, out
    except subprocess.TimeoutExpired:
        print("  超时")
        return False, "超时"


# 每步「做成了什么」的判定规则：(正则, 描述)
# rc=0 只说明进程没崩，不代表真做成了事——之前的教训
OUTCOME_RULES = {
    "音擎养成": [(r"强化了一次", "强化"), (r"点改装", "改装")],
    "角色等级": [(r"已升级", "升级"), (r"点晋升", "晋升")],
    "材料转化": [(r"已确认转化", "转化")],
    "技能升级": [(r"已升级", "升级")],
    "核心技": [(r"核心技.*?(?:已解锁|已升级|节点)", "核心技"),
                (r"当前\s*[A-F]", "读到状态")],
      "驱动盘": [(r"号位已换装", "换装")],
}


def judge(label: str, out: str) -> tuple[int, list[str]]:
    """从输出里数「实际做成了几件事」。返回 (次数, 说明列表)"""
    total = 0
    notes = []
    for pat, desc in OUTCOME_RULES.get(label, []):
        n = len(re.findall(pat, out))
        if n:
            total += n
            notes.append(f"{desc}×{n}")
    return total, notes


def charge_now() -> int:
    """读电量。走 zzz_resource --json，不再正则解析文本。"""
    from core.charge_plan import read_battery_via_cli
    return read_battery_via_cli(PY, str(HERE / "zzz_resource.py"), str(BASE))


def run_from_targets(agents: list[str], run_it: bool, max_n: int = 0) -> int:
    """按顺序逐个跑。返回失败个数。"""
    import subprocess
    if max_n > 0:
        agents = agents[:max_n]
    print("=" * 62)
    print(f"批量养成：{len(agents)} 个角色")
    print("=" * 62)
    for i, a in enumerate(agents, 1):
        print()
        print(f"[{i}/{len(agents)}] {a}")
        print("-" * 62)
        cmd = [PY, "-u", str(HERE / "zzz_daily.py"), a]
        if run_it:
            cmd.append("--run")
        r = subprocess.run(cmd, cwd=str(BASE))
        if r.returncode != 0:
            print(f"  ⚠ {a} 返回 {r.returncode}，继续下一个")
    print()
    print("=" * 62)
    print("批量结束。看进度：python tools/zzz_who.py")
    print("=" * 62)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-targets", action="store_true",
                    help="按 targets.json 里的角色列表逐个跑（不用指定角色名）")
    ap.add_argument("--max", type=int, default=0,
                    help="配合 --from-targets：今天最多跑几个（0=全跑）")
    ap.add_argument("--force-unknown", action="store_true",
                    help="角色不在库里也继续（按强攻模板判定，可能不准）")
    ap.add_argument("agent", nargs="?",
                    help="角色名。用 --from-targets 时可以省略")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="从上次中断的地方继续（读 state/run_checkpoint.json）")
    ap.add_argument("--focus-wait", type=float, default=300.0,
                    help="窗口失焦后等多少秒（默认 300），超时存断点退出")
    ap.add_argument("--no-farm", action="store_true")
    ap.add_argument("--skip", default="", help="跳过的步骤，逗号分隔：wengine,level,skill,core,disc,farm")
    ap.add_argument("--wengine-times", type=int, default=8, help="音擎批量轮数")
    ap.add_argument("--level-times", type=int, default=10, help="等级批量轮数")
    ap.add_argument("--need-skill", action="store_true", help="技能材料也不够")
    ap.add_argument("--need-core", action="store_true", help="核心技材料也不够")
    args = ap.parse_args()

    # --from-targets：从 targets.json 读角色列表批量跑
    if getattr(args, "from_targets", False):
        tj = BASE / "targets.json"
        if not tj.exists():
            print(f"✘ 没有 {tj.name}")
            print("   建一个：{\"note\": \"说明\", \"agents\": [\"佩洛伊斯\"]}")
            return 2
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
            agents = [x for x in (d.get("agents") or []) if isinstance(x, str)]
        except Exception as e:
            print(f"✘ 读不了 targets.json：{e}")
            return 2
        if not agents:
            print("✘ targets.json 里的 agents 是空的 —— 没有角色要养")
            print("   填上角色名，例如：{\"agents\": [\"佩洛伊斯\"]}")
            return 0
        return run_from_targets(agents, args.run, getattr(args, "max", 0))

    if not args.agent:
        print("✘ 没指定角色。两种用法：")
        print("   python tools/zzz_daily.py 佩洛伊斯 --run")
        print("   python tools/zzz_daily.py --from-targets --run")
        return 2
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

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    print(f"养成总控：{args.agent}")
    print(f"{'执行' if args.run else '计划'}模式")

    # ---------- ①②③ 盘点 / 缺口 / 电量（真跑时才读游戏）----------
    battery = -1
    gap_plan = None
    slots_now = []
    if args.run:
        print("\n--- 盘点 ---")
        ok, out = run("状态", [str(HERE / "zzz_status.py"), args.agent,
                            "--json"], 1800)
        st_p = BASE / "state" / f"status_{args.agent}.json"
        if st_p.exists():
            try:
                st = json.loads(st_p.read_text(encoding="utf-8"))
                slots_now = st.get("slots") or []
                print(f"  有效副词条 {st.get('blue_total', '?')} 条，"
                      f"质量分 {st.get('total', '?')}")
            except Exception:
                pass
        battery = charge_now()
        print(f"  电量 {battery}/240")

        print("\n--- 缺口 + 电量规划 ---")
        try:
            from core.charge_plan import report as _crep
            for line in _crep(max(battery, 0)).splitlines():
                print(f"  {line}")
            from core.farm_gap import plan as _fgap, report as _frep
            _slots = [{"slot": x.get("slot"), "set": x.get("set"),
                       "main": x.get("main"), "eff": x.get("eff")}
                      for x in slots_now]
            gap_plan = _fgap(args.agent, _slots, max(battery, 0),
                             need_skill=args.need_skill,
                             need_core=args.need_core)
            for line in _frep(gap_plan).splitlines():
                print(f"  {line}")
        except Exception as e:
            print(f"  （缺口分析跳过：{e}）")

    steps = [
        # 2026-11-24 改成 auto：指名角色 → 判断该装哪块 → 换装 → 升满
        # 原来的 up --lowest 只升当前装备的，不会换装
        ("音擎养成", "wengine", [str(HERE / "zzz_wengine.py"), "auto",
                              "--agent", args.agent, "--times",
                              str(args.wengine_times)], 4800),
        ("角色等级", "level", [str(HERE / "zzz_level.py"), "up",
                            "--agent", args.agent, "--auto", "--times",
                            str(args.level_times)], 4800),
        ("材料转化", "skill", [str(HERE / "zzz_convert.py"), "--all", "--confirm"], 1800),
        ("技能升级", "skill", [str(HERE / "zzz_skill.py"), "upgrade",
                            "--agent", args.agent], 2400),
        # 2026-11-24 补：核心技之前漏在步骤外，但 --skip 里却列了 core
        ("核心技", "core", [str(HERE / "zzz_core.py"), "read", "--agent", args.agent], 1800),
        # 驱动盘那步挪到刷本之后（见下），这样刷到的盘当轮就能处理，
        # 而且一轮只训一次盘。
    ]

    # 断点续跑：读上次没做完的步骤
    _done_before = []
    if getattr(args, "resume", False):
        try:
            from core import pause as _pause
            _ck = _pause.load(args.agent)
            if _ck:
                _done_before = list(_ck.get("done") or [])
                print(f"\n从断点续跑：已完成 {len(_done_before)} 步 {_done_before}")
                print(f"  剩余 {len(_ck.get('pending') or [])} 步")
        except Exception as _e:
            print(f"\n⚠ 读断点失败：{_e}，从头跑")

    # ---- 刷本：**放在最前**（2026-11-25 用户要求）----
    # 刷本是唯一的资源获取步骤（花电量，掉盘/掉材料）。
    # 放最后的话，前面所有升级步骤只能吃仓库剩的，吃不到当天新刷的。
    if "farm" not in skip and not args.no_farm:
        n = charge_now()
        print(f"\n--- 刷本 --- 电量 {n}")
        if args.run and n >= FARM_COST:
            # 2026-11-24 合并：od_farm.py 的独有参数已并进 od_material_farm.py，
            # 两个总控统一走同一个刷本入口，避免行为不一致。
            # 用缺口计划选副本（不是写死拂晓行纪）
            dungeon = "机师与叛甲"
            times = 1
            if gap_plan and gap_plan.get("farms"):
                dungeon = gap_plan["farms"][0]["dungeon"]
                times = max(1, gap_plan["farms"][0].get("times", 1))
                print(f"    按缺口选：{dungeon} × {times}")
            run("刷本", [str(HERE / "od_material_farm.py"), "--patrol", dungeon,
                        "--times", str(times), "--run"], 3600)
            # 2026-11-24 修：zzz_mark.py 点的是仓库底部弃置按钮（已失效，是灰的）。
            # 改走实测可用的链路：升级→判定→标记(R键)→拆解。
            # 刷本拿到素材后再转化一次（材料可双向转化，缺什么补什么）
            run("刷后转化", [str(HERE / "zzz_convert.py"), "--all", "--confirm"], 1800)
        elif not args.run:
            print("  [计划] 电量够就刷本 → 标记弃置 → 拆解")
        else:
            print(f"  电量 {n} < {FARM_COST}，跳过刷本")


    for label, key, cmd, timeout in steps:
        if key in skip:
            print(f"\n--- {label} --- 跳过")
            continue
        if label in _done_before:
            print(f"\n--- {label} --- 断点里已完成，跳过")
            continue
        if not args.run:
            print(f"\n--- {label} --- [计划] {' '.join(cmd[0].split(chr(92))[-1:])}")
            continue

        # **失焦不等于失败** —— 用户可能只是切去看个消息。
        # 等他切回来，从这个步骤重跑（不是从整轮重跑）。
        _attempt = 0
        while True:
            _attempt += 1
            try:
                ok, out = run(label, cmd, timeout)
                break
            except Exception as _e:
                _ename = type(_e).__name__
                if "FocusLost" not in _ename and "FocusLost" not in str(_e):
                    raise
                try:
                    from core import pause as _pause
                    from core import focus as _focus
                    import live as _live
                    _w = _live.find_window()
                    _hwnd = _w.get("hwnd") if _w else 0
                    if not _pause.on_focus_lost(_hwnd, args.focus_wait, label):
                        raise
                except Exception:
                    print(f"  窗口没回来，存断点退出")
                    from core import pause as _pause
                    _pause.save(args.agent, _done_before, 
                                [x[0] for x in steps if x[0] not in _done_before
                                 and x[0] != label] + [label], "FocusLost")
                    return 6
                if _attempt >= 3:
                    print(f"  {label} 试了 {_attempt} 次还是失焦，跳过")
                    break

        n, notes = judge(label, out)

        # 每步成功就落盘断点 —— 这样硬 Ctrl+C（甚至关窗口）也不丢进度。
        # 只在内存里记的话，中断处理里拿不到 main() 的局部变量。
        if ok:
            _done_before.append(label)
            try:
                from core import pause as _pause
                _pend = [x[0] for x in steps if x[0] not in _done_before]
                if "farm" not in skip:
                    _pend.append("刷本")
                if "disc" not in skip:
                    _pend.append("驱动盘")
                _pause.save(args.agent, _done_before, _pend, "进行中")
            except Exception:
                pass
        if n == 0:
            why = ""
            for kw in ("材料不足", "打不开", "选不中", "不在 disc_meta", "找不到"):
                if kw in out:
                    why = kw
                    break
            print("    [!] 没做成事" + (f"（{why}）" if why else "（可能材料/资源不足）"))
        else:
            print(f"    [OK] 实际完成：{'  '.join(notes)}")

    # ---- 驱动盘：刷本之后统一处理一次 ----
    # 内含：盘点 → 缺口 → 调律 → 训练（带初始判定+止损）→ 换装 → 回收
    # 只训一次，且处理的是「刚刷到的盘 + 已有的盘」
    if "disc" not in skip:
        if args.run:
            ok, out = run("驱动盘", [str(HERE / "zzz_disc_daily.py"), args.agent,
                                     "--run", "--no-farm"], 5400)
            n, notes = judge("驱动盘", out)
            if n == 0:
                print("    [!] 驱动盘这步没做成事")
            else:
                print(f"    [OK] 实际完成：{'  '.join(notes)}")
        else:
            print(f"\n--- 驱动盘 --- [计划] zzz_disc_daily {args.agent} --no-farm")

    # 收尾：记账 + 汇报
    if args.run:
        try:
            from zzz_disc_daily import read_status, append_progress
            st2 = read_status(args.agent)
            sl2 = st2.get("slots") or []
            blue2 = sum(x.get("blue") or 0 for x in sl2)
            total2 = round(sum(x.get("eff") or 0 for x in sl2), 1)
            blue0 = sum(x.get("blue") or 0 for x in slots_now)
            total0 = round(sum(x.get("eff") or 0 for x in slots_now), 1)
            append_progress({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "agent": args.agent,
                "蓝条": blue2, "质量分": total2,
                "动作": ["daily"],
                "位号": [{"slot": x.get("slot"), "set": x.get("set"),
                          "eff": x.get("eff"), "blue": x.get("blue")}
                         for x in sl2],
            })
            print(f"\n=== 今日成果 ===")
            print(f"  有效副词条 {blue0} → {blue2}（{blue2 - blue0:+d}）")
            print(f"  质量分     {total0} → {total2}（{total2 - total0:+.1f}）")
            print(f"  距小毕业 28 还差 {round(28 - total2, 1)}")
            # 汇报飞书
            import subprocess as _sp
            _msg = (f"【{args.agent} 每日养成】\n"
                    f"有效副词条 {blue0} → {blue2}（{blue2 - blue0:+d}）\n"
                    f"质量分 {total0} → {total2}（{total2 - total0:+.1f}）\n"
                    f"距小毕业 28 还差 {round(28 - total2, 1)}")
            if (HERE / "feishu.py").exists():
                _sp.run([str(PY), "-u", str(HERE / "feishu.py"), "send", _msg],
                        cwd=str(BASE), capture_output=True, timeout=90)
        except Exception as e:
            print(f"  （记账/汇报跳过：{e}）")

    # 收尾：体检
    if args.run:
        run("体检", [str(HERE / "zzz_status.py"), args.agent, "--json"], 1800)
        print("\n" + "=" * 50)
        print("全部步骤完成")
    return 0


if __name__ == "__main__":
    # Ctrl+C 不等于丢工作 —— 存个断点，下次 --resume 接着跑。
    # 以前的版本直接死，做到一半的步骤全丢，而且不知道该从哪接。
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print("=" * 60)
        print("⏹  中断了（Ctrl+C）")
        print("=" * 60)
        try:
            from core import pause as _pause
            _agent = ""
            # 从 argv 里猜角色名（第一个不像参数的）
            import sys as _s
            for _a in _s.argv[1:]:
                if not _a.startswith("-"):
                    _agent = _a
                    break
            _ck = pause.CKPT if hasattr(pause, "CKPT") else None
            print(f"  已完成的步骤不会重跑 —— 断点存在 state/run_checkpoint.json")
            print(f"  续跑：python tools/zzz_daily.py {_agent} --run --resume")
            print()
            print("  （如果你是在跑完整流程前中断的，没有断点文件，直接重跑即可）")
        except Exception as _e:
            print(f"  （存断点失败：{_e}）")
        sys.exit(130)                    # 130 = SIGINT 的约定退出码