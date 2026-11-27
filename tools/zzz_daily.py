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
    except OSError as e:
        # **`PY` 是空串时抛 WinError 87**（RT-03）—— 只 catch 了 TimeoutExpired，
        # 于是崩在任何配置提示之前。
        if not PY:
            msg = "没找到 OneDragon 的 python —— 先跑 `python tools/check_config.py`"
            print(f"  {msg}")
            return False, msg
        print(f"  启动子进程失败：{type(e).__name__}: {e}")
        return False, f"{type(e).__name__}: {e}"


# 每步「做成了什么」的判定规则：(正则, 描述)
# rc=0 只说明进程没崩，不代表真做成了事——之前的教训
OUTCOME_RULES = {
    # **规则必须对着各工具真实打印的文本来写**（BUG-089）。
    #
    # 原来 7 条里至少 4 条的正则在实际输出里**一次都不会出现**：
    #   `强化了一次` / `点改装` / `已升级` / `点晋升` / `号位已换装` …
    # 于是 `judge()` 恒返回 0 → 「实际完成」永远是 0 →
    # **`zzz_grind` 看不到任何进展，那个「刷到毕业」的循环永远不会收敛**。
    #
    # 三元素的规则 `(正则, 描述, 分组号)`：分组号指「次数」在哪个捕获组里。
    # 工具经常一行报「强化 5 次」，只数行数会得 1，必须把数字取出来。
    "音擎养成": [(r"完成：强化\s*(\d+)\s*次", "强化", 1),
                 (r"完成：有效操作\s*(\d+)\s*次", "强化", 1)],
    "角色等级": [(r"完成，升级\s*(\d+)\s*次", "升级", 1),
                 (r"✔\s*已点升级", "升级", 0)],
    "材料转化": [(r"已确认转化", "转化", 0)],
    "技能升级": [(r"已升级", "升级", 0)],
    "核心技":   [(r"合计升了\s*(\d+)\s*次", "核心技", 1),
                 (r"✔\s*已到达", "核心技", 0)],
    "核心技读取": [(r"已解锁", "已解锁", 0)],
    "驱动盘":   [(r"✔\s*已调", "调律", 0),
                 (r"✔\s*主词条", "换装", 0)],
}


def judge(label: str, out: str) -> tuple[int, list[str]]:
    """从输出里数「实际做成了几件事」。返回 (次数, 说明列表)"""
    total = 0
    notes = []
    for rule in OUTCOME_RULES.get(label, []):
        # 三元素：(正则, 描述, 分组号) —— 从「强化 5 次」里取出 5
        if len(rule) == 3:
            pat, desc, grp = rule
        else:
            pat, desc = rule
            grp = 0
        if grp:
            nums = [int(x) for x in re.findall(pat, out) if str(x).isdigit()]
            n = sum(nums) if nums else 0
        else:
            n = len(re.findall(pat, out))
        if n:
            total += n
            notes.append(f"{desc}×{n}")
    return total, notes


def _farm_count_today() -> int:
    """今天已经刷过几次本。

    ## **读不了返回 -1，不是 0**（RT-08）

    原来是 `try: ... except: pass; return 0` —— 而
    「文件读不了」和「今天还没刷」在调用方看来一样，
    于是额度闸门静默失效，**同一天重复刷本**（多花 60~200 电）。

    现在 `-1` = 不知道。调用方要么当成「可能刷过」保守处理，要么报出来。
    """
    from core import farm_log as _fl
    n, why = _fl.count_today_safe()
    if why:
        print(f"  ⚠ {why}")
        print(f"     **不知道今天刷过没** —— 额度闸门按「可能刷过」处理")
    return n


def _farm_record(dungeon: str, times: int) -> None:
    """记一次刷本。用**共享模块**写，schema 只有一个来源。"""
    try:
        from core import farm_log as _fl
        _fl.append(dungeon=dungeon, times=times, ok=True, source="zzz_daily")
    except Exception as _e:
        print(f"  （记刷本日志失败：{_e}）")


def _cached_battery() -> int:
    """读缓存的电量，**不碰游戏**。没有/过期返回 -1。

    RT 实测：计划模式一次 `charge_now()` 要 48~85 秒，
    把「10 秒出计划」拖成 76.5 秒。计划模式只需要大概知道电量，用缓存就够。
    """
    try:
        import json as _j
        import time as _t
        from pathlib import Path as _P
        cache = _P(BASE) / "state" / "resource_cache.json"
        if not cache.exists():
            return -1
        d = _j.loads(cache.read_text(encoding="utf-8"))
        batt = int(d.get("battery", -1))
        ts = d.get("_ts") or d.get("ts") or ""
        if batt < 0 or not ts:
            return -1
        # 超过 2 小时当作过期（电量 6 分钟回 1 点，2 小时能差 20 点）
        t0 = _t.mktime(_t.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
        if abs(_t.time() - t0) > 7200:
            return -1
        return batt
    except Exception:
        return -1


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


def _snap_all(agent: str) -> dict:
    """把各系统的当前状态抓一份快照，用于跑前/跑后对比。

    **读不到的写 None，不要写 0** —— 「0」和「没读到」混了会得出假结论。
    """
    snap = {}

    # 驱动盘 / 技能 / 角色等级 —— 都在 status_<角色>.json
    try:
        from zzz_disc_daily import read_status as _rs
        st = _rs(agent) or {}
        slots = st.get("slots") or []
        snap["驱动盘_蓝条"] = sum(x.get("blue") or 0 for x in slots) if slots else None
        # 主词条无效的位号价值按 0（硬门槛）
        snap["驱动盘_质量分"] = (round(sum(
            0.0 if x.get("main_verdict") == "bad" else (x.get("eff") or 0)
            for x in slots), 1) if slots else None)
        _sk = st.get("skills")
        if isinstance(_sk, dict) and _sk:
            _tot = 0
            for v in _sk.values():
                import re as _re
                _d = _re.sub(r"\D", "", str(v))
                _tot += int(_d[:2]) if len(_d) >= 2 else 0
            snap["技能_总等级"] = _tot
        else:
            snap["技能_总等级"] = None
        snap["角色等级"] = st.get("char_level") or None
    except Exception as _e:
        print(f"    （抓驱动盘/技能快照失败：{_e}）")

    # 核心技 —— costs 里还差多少
    try:
        from core.state import check_fresh as _cf
        from pathlib import Path as _P
        _cp = BASE / "state" / f"core_status_{agent}.json"
        if not _cp.exists():
            _cp = BASE / "state" / "core_status.json"
        if _cp.exists():
            import json as _j
            _cd = _j.loads(_cp.read_text(encoding="utf-8"))
            _cf(_cd, "core", f"核心技({agent})")
            _lack = 0
            for _k, _v in _cd.items():
                if _k.startswith("_") or not isinstance(_v, dict):
                    continue
                for _pair in (_v.get("costs") or []):
                    try:
                        _h, _n = int(_pair[0]), int(_pair[1])
                    except Exception:
                        continue
                    if _h < _n:
                        _lack += _n - _h
            snap["核心技_总缺口"] = _lack
        else:
            snap["核心技_总缺口"] = None
    except Exception:
        snap["核心技_总缺口"] = None

    # 音擎
    try:
        import json as _j2
        _wp = BASE / "state" / f"wengine_{agent}.json"
        if _wp.exists():
            _wd = _j2.loads(_wp.read_text(encoding="utf-8"))
            snap["音擎_等级"] = _wd.get("level") or _wd.get("等级")
        else:
            snap["音擎_等级"] = None
    except Exception:
        snap["音擎_等级"] = None

    # 材料库存
    try:
        from core import inventory as _inv
        _items = {k: v for k, v in _inv.snapshot().items() if k != "_ts"}
        snap["库存_种类"] = len(_items) if _items else None
        snap["库存_总数"] = (sum(int((v or {}).get("有", 0)) for v in _items.values())
                            if _items else None)
    except Exception:
        snap["库存_种类"] = None
        snap["库存_总数"] = None

    return snap


def _diff(before: dict, after: dict) -> list[tuple[str, object, object]]:
    """对比两份快照。只返回有变化的（None 不算变化）。"""
    out = []
    for k in before:
        b, a = before.get(k), after.get(k)
        if b is None or a is None:
            continue
        if a != b:
            out.append((k, b, a))
    return out


def _farm_cmd(dungeon: str, times: int) -> list[str]:
    """副本名 → od_material_farm 参数。

    **实现统一在 `core/farm_cmd.py`** —— 这里只做转发。
    （原来这份判断在 `zzz_gap` 和这里各写了一遍，属于「同一知识两处维护」，
      而我这轮已经因为这类漂移踩了两次坑：属性表「感电/电击」、芯片副本名。）
    """
    from core.farm_cmd import farm_cmd
    return farm_cmd(dungeon, times, run=True)


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
    ap.add_argument("--convert", action="store_true",
                    help="真的跑材料转化（会消耗低阶技能材料，不可逆）。"
                         "不加则跳过这一步")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="从上次中断的地方继续（读 state/run_checkpoint.json）")
    ap.add_argument("--focus-wait", type=float, default=300.0,
                    help="窗口失焦后等多少秒（默认 300），超时存断点退出")
    ap.add_argument("--no-farm", action="store_true")
    ap.add_argument("--again", action="store_true",
                    help="今天已经刷过也要再刷（电量回满了想继续刷时用）")
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

    # **校验 --skip 的键**（BUG-058）。
    #
    # 键是英文的（wengine/level/skill/core/disc/farm），
    # 但原来不校验：写 `--skip 驱动盘` 也能过，然后
    # `if "disc" not in skip` 仍为真 —— **一步都没跳过，而且没有任何提示**。
    #
    # 用户以为跳过了驱动盘，实际照跑。
    _VALID_SKIP = {"wengine", "level", "skill", "core", "disc", "farm"}
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    _bad = skip - _VALID_SKIP
    if _bad:
        print(f"  ✘ --skip 里有认不出的键：{sorted(_bad)}")
        print(f"     可用的：{sorted(_VALID_SKIP)}")
        print(f"     （用英文键，不是中文步骤名）")
        return 2
    if args.skip:
        print(f"  将跳过：{sorted(skip)}")

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

        # **跑之前先拍一张快照**（BUG-068 相关）。
        #
        # 收尾那段用 `_snap_before` 和 `_snap_after` 对比「本轮变化」，
        # 但 `_snap_before` **从来没被赋值过** —— 于是那个 try 每次都走 except，
        # 打印「（全系统对比跳过：name '_snap_before' is not defined）」。
        #
        # 也就是说：**「本轮变化（全部系统）」这个功能从未工作过**，
        # 而且因为包在 try 里，谁也没发现。
        try:
            _snap_before = _snap_all(args.agent)
            _nb = sum(1 for v in _snap_before.values() if v is not None)
            print(f"  已记录跑前快照（{_nb}/{len(_snap_before)} 项可读）")
        except Exception as _e:
            _snap_before = {}
            print(f"  （跑前快照失败：{_e}）")

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

    # 「没做成事」的计数：用来决定退出码（BUG-087）
    _noprog = {"steps": 0, "tried": 0}
    steps = [
        # 2026-11-24 改成 auto：指名角色 → 判断该装哪块 → 换装 → 升满
        # 原来的 up --lowest 只升当前装备的，不会换装
        ("音擎养成", "wengine", [str(HERE / "zzz_wengine.py"), "auto",
                              "--agent", args.agent, "--times",
                              str(args.wengine_times)], 4800),
        ("角色等级", "level", [str(HERE / "zzz_level.py"), "up",
                            "--agent", args.agent, "--auto", "--times",
                            str(args.level_times)], 4800),
        # **材料转化会消耗低阶材料（BUG-008）。**
        # 原来写死 `--all --confirm`，只要 `--run` 就自动转 5 种技能材料。
        # 现在不加 `--convert` 就置 None（下面的循环会跳过）。
        ("材料转化", "skill",
         [str(HERE / "zzz_convert.py"), "--all", "--confirm"]
         if args.convert else None, 1800),
        ("技能升级", "skill", [str(HERE / "zzz_skill.py"), "upgrade",
                            "--agent", args.agent], 2400),
        # 2026-11-24 补：核心技之前漏在步骤外，但 --skip 里却列了 core
        # 2026-11-26 改：以前调 read（只读不升），文档却写「读取/升级」。
        # 现在 zzz_core.py 真有了 upgrade 子命令，改成真升。
        ("核心技", "core", [str(HERE / "zzz_core.py"), "upgrade",
                          "--agent", args.agent, "--times", "1"], 2400),
        # 升完再读一次，把 A~F 状态写进 state/core_status.json
        ("核心技读取", "core_read", [str(HERE / "zzz_core.py"), "read",
                              "--agent", args.agent], 1800),
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
        # **计划模式不读游戏**（RT-REPORT N-4 / N-5）。
        #
        # 原来这里无条件 `charge_now()` —— 它要起一个子进程跑
        # `zzz_resource.py`，实测一次 48~85 秒。
        # 于是「计划模式 10 秒出结果」实测是 **76.5–440.7 秒**（7.6–44 倍），
        # 而且计划模式还会因为这次读盘写出 `resource_cache.json`。
        #
        # 计划模式只需要「知道要不要刷」，不需要精确电量：
        # 有缓存就用缓存（标注可能过期），没有就说「真跑时才读」。
        if args.run:
            n = charge_now()
            print(f"\n--- 刷本 --- 电量 {n}")
        else:
            n = _cached_battery()
            if n >= 0:
                print(f"\n--- 刷本 --- [计划] 缓存电量 {n}（可能过期，真跑会重读）")
            else:
                print("\n--- 刷本 --- [计划] 不读游戏（电量未知，加 --run 才读）")
        # **今天已经刷过就不再刷**（BUG-091）。
        #
        # 原来完全不记「刷过没」—— `zzz_daily --run` 一天跑两次就刷两次，
        # 第二天的电量被提前烧掉。而这是「每日养成」工具，
        # 每天的额度应该只花一次。
        #
        # 加 `--again` 可以强制再刷（电量回满了想继续刷就用它）。
        _already = _farm_count_today()
        if args.run and _already and not getattr(args, "again", False):
            print(f"  今天已经刷过 {_already} 次了 —— 跳过（要再刷加 --again）")
            n = -1
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
            # **按副本名路由参数** —— 原来一律 `--patrol`，
            # 只能刷区域巡防；芯片/认证章/高维数据/周本全都刷不了。
            # **传 --again**：额度已经在本函数上面查过了（`_already`），
            # 而 `od_material_farm` 自己也有一道闸门（E31）。
            # 不传的话会因为「今天已刷」被自己拦下来。
            _ok_farm = run("刷本", _farm_cmd(dungeon, times) + ["--again"], 3600)
            if _ok_farm[0]:
                # **不在这里记账**（E31）：`od_material_farm` 刷成功后会自己记。
                # 两边都记会双计 —— 那样「今天刷了几次」直接翻倍，
                # 额度闸门就变成「第二次就拦住」了。
                pass
            # 2026-11-24 修：zzz_mark.py 点的是仓库底部弃置按钮（已失效，是灰的）。
            # 改走实测可用的链路：升级→判定→标记(R键)→拆解。
            # 刷本拿到素材后再转化一次（材料可双向转化，缺什么补什么）
            # BUG-008：会消耗低阶材料，不加 --convert 就跳过
            if args.convert:
                run("刷后转化",
                    [str(HERE / "zzz_convert.py"), "--all", "--confirm"], 1800)
            else:
                print("  [跳过] 刷后转化（会消耗低阶材料，加 --convert 才做）")
        elif not args.run:
            print("  [计划] 电量够就刷本 → 标记弃置 → 拆解")
        else:
            print(f"  电量 {n} < {FARM_COST}，跳过刷本")


    for label, key, cmd, timeout in steps:
        if key in skip:
            print(f"\n--- {label} --- 跳过")
            continue
        if cmd is None:
            # 步骤表用 None 表示「本次不跑」（比如没加 --convert 的材料转化）。
            # 必须先判掉 —— 下面会 cmd[0] 取文件名、还会 run(label, cmd, ...)。
            print(f"\n--- {label} --- 跳过（本次未启用）")
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
        # **记下「没做成事」的次数**（BUG-087）—— 以前这个 n 只用来打印，
        # 退出码永远是 0，上层完全看不出来。
        if n == 0:
            _noprog["steps"] += 1
        _noprog["tried"] += 1

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
                _noprog["steps"] += 1
            _noprog["tried"] += 1
            if n == 0:
                print("    [!] 驱动盘这步没做成事")
            else:
                print(f"    [OK] 实际完成：{'  '.join(notes)}")
        else:
            print(f"\n--- 驱动盘 --- [计划] zzz_disc_daily {args.agent} --no-farm")

    # 收尾：记账 + 汇报
    if args.run:
        # **对比全部系统，不只驱动盘。**
        # 以前只报 蓝条/质量分，其他六个系统的成果全丢 —— 用户看不出进度。
        try:
            _after = _snap_all(args.agent)
            _chg = _diff(_snap_before, _after)
            print("\n=== 本轮变化（全部系统）===")
            if not _chg:
                print("  （没有可对比的变化 —— 要么没做成事，要么两边都没读到）")
            for _k, _b, _a in _chg:
                print(f"  {_k:<14} {_b} → {_a}")
            if _snap_before.get("材料库存_总数") is not None:
                from core import inventory as _iv
                _ag = _iv.age_hours()
                if _ag is not None and _ag > 48:
                    print(f"  ⚠ 材料库存是 {_ag:.0f} 小时前的记录，可能已经不准")
        except Exception as _e:
            print(f"  （全系统对比跳过：{_e}）")

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
    # **真跑模式下，一步都没做成 -> 退出码 1**（BUG-087）。
    #
    # 原来无条件 return 0：哪怕每个步骤都打印「[!] 没做成事」，
    # 退出码也是 0（成功）—— 上层完全看不出来。
    #
    # 只在「**所有**步骤都没做成」时返 1：一步跳过、其他步骤有进展，
    # 仍是成功的一天。
    if args.run and _noprog["tried"] and _noprog["steps"] == _noprog["tried"]:
        print(f"  退出码 1：{_noprog['tried']} 个步骤全都「没做成事」")
        return 1
    # **正常收尾要清断点**（RT-10）。
    # 原来 `pause.clear()` 全仓零调用 —— 断点永久有效，
    # 下次 --resume 会把全部步骤当「已完成」跳过然后返回 0。
    # （日期校验是第二道闸，两道都要有。）
    if args.run:
        try:
            from core import pause as _pause_clr
            _pause_clr.clear()
        except Exception:
            pass
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
            # **这里原来写的是 `pause`，而作用域里只有 `_pause`**（RT-10）——\n            # NameError 被外层 except 吞掉，只打印「存断点失败」。\n            # 而且 `_ck` 本身没被用到：断点是在步骤循环里存的。\n            _ck = _pause.CKPT if hasattr(_pause, "CKPT") else None
            print(f"  已完成的步骤不会重跑 —— 断点存在 state/run_checkpoint.json")
            print(f"  续跑：python tools/zzz_daily.py {_agent} --run --resume")
            print()
            print("  （如果你是在跑完整流程前中断的，没有断点文件，直接重跑即可）")
        except Exception as _e:
            print(f"  （存断点失败：{_e}）")
        sys.exit(130)                    # 130 = SIGINT 的约定退出码
