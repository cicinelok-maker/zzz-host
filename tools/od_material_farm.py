"""按材料缺口刷本：写一条体力计划并执行。

## 支持的分类（OneDragon 实测支持）

    实战模拟室   训练类型：代理人技能 / 基础材料 / 代理人方案培养 …
    区域巡防     副本类型：机师与叛甲 / 高塔与巨炮 …（按套装名映射）
    专业挑战室   挑战名称
    恶名狩猎     目标名称

## 用法

    python tools/od_material_farm.py --training 代理人技能 --times 2          # 只看计划
    python tools/od_material_farm.py --training 代理人技能 --times 2 --run    # 真跑
    python tools/od_material_farm.py --challenge 深蚀回路 --run
    python tools/od_material_farm.py --from-gaps                              # 按当前缺口自动选
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from core.game_cfg import DEFAULT_AGENT as _DEFAULT_AGENT

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
from core.paths import one_dragon_env
# OD_HOME 可配置（paths.json 或环境变量），默认退回 OneDragon 目录
OD = Path(one_dragon_env().get("OD_HOME")
          or os.environ.get("OD_HOME")
          or str(Path(__file__).resolve().parent.parent))
GROUP = "one_dragon"


def build_plans(args) -> list[tuple[str, str, int]]:
    """返回 [(分类, 类型名, 次数)]"""
    plans = []
    n = max(1, args.times)
    if args.training:
        plans.append(("实战模拟室", args.training, n))
    patrol_name = args.patrol_type or args.patrol
    if patrol_name:
        # **用 `patrol_name`，不是 `args.patrol`**（BUG-078）。
        #
        # 上一行刚算出「`--patrol-type` 优先」的结果，
        # 这一行又退回 `args.patrol`。于是用户只传
        # `--patrol-type 机师与叛甲` 时，计划里记的副本名是**空的**，
        # 刷本必然失败，而且不报错。
        plans.append(("区域巡防", patrol_name, n))
    if args.challenge:
        plans.append(("专业挑战室", args.challenge, n))
    if args.hunt:
        plans.append(("恶名狩猎", args.hunt, n))
    return plans


def from_gaps() -> list[tuple[str, str, int]]:
    """按 material_sources.json 和当前状态给出刷本计划"""
    # **判存在再读**（BUG-079）。原来直接 read_text，
    # 文件不在就抛 FileNotFoundError + 30 行 traceback ——
    # 而那只是「还没盘点过」，不是程序坏了。
    #
    # 顺带：这份 `table` 原来读出来**一个字都没用**（死变量），
    # 真正的判据在下面两段（skill_status / core_status）。
    # 所以这里不读它，只检查它在不在。
    _ms = BASE / "state" / "material_sources.json"
    if not _ms.exists():
        print(f"  ⚠ 还没有 {_ms.name} —— 缺口判断会不完整")
        print("     先跑：python tools/zzz_gap.py <角色名>")
    plans = []

    # 技能材料缺口
    st = BASE / "state" / "skill_status.json"
    if st.exists():
        data = json.loads(st.read_text(encoding="utf-8"))
        short = [k for k, v in data.items()
                 if isinstance(v, dict) and not v.get("ok", True)]
        if short:
            plans.append(("实战模拟室", "代理人技能", 2))

    # 核心技缺口
    #
    # **按角色读**（E34）。原来读的是全局 `state/core_status.json` ——
    # 而 `zzz_core.py` 写的是 `state/core_status_<角色>.json`。
    # 全局那个文件**从来没被创建过**，所以这段代码**一直没生效**：
    # 核心技没满的角色也不会被排进刷本计划。
    #
    # （`zzz_farm_plan.py:131` 早就改成按角色读了，这里漏了。）
    _found_core = False
    for cs in sorted((BASE / "state").glob("core_status_*.json")):
        try:
            data = json.loads(cs.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for key, v in data.items():
            if not isinstance(v, dict):
                continue
            costs = v.get("costs") or []
            try:
                if len(costs) >= 2 and costs[1][0] < costs[1][1]:
                    plans.append(("专业挑战室", "深蚀回路", 2))
                    _found_core = True
                    break
            except (TypeError, IndexError):
                continue
        if _found_core:
            break
    return plans


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--training", default="", help="实战模拟室类型名")
    ap.add_argument("--patrol", default="", help="区域巡防副本名")
    ap.add_argument("--challenge", default="", help="专业挑战室名称")
    ap.add_argument("--hunt", default="", help="恶名狩猎目标")
    ap.add_argument("--times", type=int, default=2)
    ap.add_argument("--mission", default="", help="子副本名（实战模拟室-代理人技能要传角色名）")
    ap.add_argument("--cards", type=int, default=5,
                    help="实战模拟室怪物卡数量 1-5（越多资源越多，电量也越多）")
    ap.add_argument("--level", default="默认等级", help="挑战等级")
    ap.add_argument("--from-gaps", action="store_true", help="按当前缺口自动选")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--again", action="store_true",
                    help="今天已经刷过了还刷（默认会拦）")
    ap.add_argument("--instance", type=int, default=1)
    # 2026-11-24 从 od_farm.py 合并过来的参数（避免两个刷本工具重复）
    ap.add_argument("--agent", default=_DEFAULT_AGENT,
                    help="角色名（用于按岗位推导副本类型）")
    ap.add_argument("--patrol-type", default="",
                    help="区域巡防：直接给副本类型名，覆盖 --patrol")
    ap.add_argument("--plan-only", action="store_true",
                    help="写计划配置但不启动刷本（会改 OneDragon 的配置，不用开游戏）")
    ap.add_argument("--loop", action="store_true",
                    help="刷到电量耗尽（默认 False：只刷 --times 次）")
    ap.add_argument("--use-backup", action="store_true",
                    help="电量不足时使用储蓄电量")
    args = ap.parse_args()

    # **额度闸门放在这里 —— 刷本的唯一收口**（E31）。
    #
    # 原来「每天只刷一次」只写在 `zzz_daily` 里，而 `od_material_farm` 是
    # 真正执行刷本的那个工具，**它自己不看额度**。于是：
    #   · 直接跑 `od_material_farm --run`
    #   · 或者从 `zzz_farm_plan --run` 进来
    # 都会把当天的电量再烧一遍。
    #
    # 现在闸门在最底层，任何入口都绕不过去。
    if args.run and not getattr(args, "again", False):
        try:
            from core import farm_log as _fl
            _today, _why = _fl.count_today_safe()
            if _why:
                print(f"  ⚠ {_why}")
                print(f"     **不知道今天刷过没** —— 按「可能刷过」处理，不拦")
            elif _today > 0:
                print(f"  ✘ 今天已经刷过 {_today} 次（额度闸门）")
                print(f"     再刷一遍会把明天的电量提前烧掉。确实要刷就加 --again。")
                return 4
        except Exception as _e:
            print(f"  （额度检查跳过：{_e}）")

    # **显式指定的不能因为加了 --from-gaps 就被丢掉**（BUG-079）。
    #
    # 原来是二选一：`from_gaps() if args.from_gaps else build_plans(args)`。
    # 于是 `--from-gaps --patrol 机师与叛甲` 里那个 `--patrol` **静默消失**，
    # 用户以为自己指定了副本，实际跑的是缺口算出来的另一个。
    #
    # 现在：显式的在前，缺口补在后（去重）。
    plans = build_plans(args)
    if args.from_gaps:
        _gap = from_gaps()
        if _gap:
            print(f"  缺口补了 {len(_gap)} 项：{[g[1] for g in _gap]}")
        for _g in _gap:
            if _g not in plans:
                plans.append(_g)
    if not plans:
        print("  没有要刷的（既没给参数，缺口也算不出来）")

    # **周本有次数上限**（恶名狩猎每周 3 次），刷完就刷不到东西。
    # 不查的话：调进去游戏显示「次数已用完」，工具报「没做成事」，
    # 用户以为工具坏了，反复重试。**资源上限和工具故障要能分开报。**
    try:
        from core import weekly as _wk
        _total_battery = 0
        for _cat, _name, _n in plans:
            if _cat in ("恶名狩猎", "哨站后勤"):
                _ok, _why = _wk.can_run(_cat)
                _cost = _wk.cost_for_next(_cat) if _ok else -1
                print(f"  {_cat}：{_why}")
                if _ok and _cost > 0:
                    _total_battery += _cost * max(1, _n)
                    print(f"    （这次要花 {_cost} 电/次 × {max(1, _n)} 次）")
        if _total_battery > 0:
            print(f"  周本预计花 {_total_battery} 电量（免费额度已用完）")
    except Exception as _e:
        print(f"  （周本次数检查跳过：{_e}）")
    if not plans:
        print("没指定要刷什么。用 --training / --challenge / --hunt，或 --from-gaps")
        return 2

    print("计划：")
    for cat, name, n in plans:
        print(f"  {cat} · {name} ×{n}")

    # **`mission_name` 空着写进去 = 计划跑不起来**（P0-3 / P0-4）。
    #
    # 下面 `ChargePlanItem(..., mission_name=getattr(args, "mission", ""))` ——
    # 参数是传了的，但 `--mission` **默认空串**。
    #
    # 而「实战模拟室」需要子副本名（代理人技能要传角色名），
    # 「专业挑战室」「恶名狩猎」也需要具体的关卡名。
    # 空着写进 OneDragon 的计划里，**启动后会立刻失败**，而这里什么都不说。
    #
    # 现在：这些类别缺 `mission_name` 就直接拒绝，并说清楚该传什么。
    _NEED_MISSION = {"实战模拟室", "专业挑战室", "恶名狩猎"}
    _miss = [c for c, _n, _t in plans if c in _NEED_MISSION]
    if _miss and not getattr(args, "mission", ""):
        print(f"  ✘ {'、'.join(sorted(set(_miss)))} 需要子副本名，但没传 --mission")
        print(f"     实战模拟室-代理人技能：--mission 要传**角色名**")
        print(f"     其他：--mission 传具体关卡名")
        print(f"     例：python tools/{Path(__file__).name} "
              f"--training 代理人技能 --mission 佩洛伊斯 --times 2")
        print(f"     （不加 --mission 也会写进 OneDragon 的计划，但**启动后必然失败**）")
        return 2

    # **`--plan-only` 必须真的只打印**（RT-07）。
    #
    # 下面那段会 `cfg.plan_list.clear()` 然后 `cfg.save()` ——
    # **清空 OneDragon 里现有的体力计划**，再写成本次的。
    #
    # 而 `--plan-only` 的判断原来在这段**之后**（L224）——
    # 于是「只出计划」照样把你手工配好的计划清掉了。
    # 用户只是想看一眼，结果配置没了。
    #
    # 现在：`--plan-only` 在这里直接返回，**一个字节都不碰**。
    #
    # 三种模式的区别：
    #   --plan-only   只打印，不改任何配置
    #   （默认）       写进 OneDragon 的计划，但不启动
    #   --run         写进去并启动
    if getattr(args, "plan_only", False):
        print("\n（--plan-only：只打印，**没有改 OneDragon 的计划配置**）")
        print("  要写进去并启动：去掉 --plan-only，加 --run")
        return 0

    sys.path.insert(0, str(OD / "src"))
    sys.path.insert(0, str(OD / "plugins"))
    from zzz_od.context.zzz_context import ZContext
    from zzz_od.application.charge_plan.charge_plan_app_factory import ChargePlanAppFactory
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem

    ctx = ZContext()
    ctx.init()
    factory = ChargePlanAppFactory(ctx)
    cfg = factory.create_config(args.instance, GROUP)
    cfg.plan_list.clear()
    for cat, name, n in plans:
        cfg.add_plan(ChargePlanItem(
            tab_name="训练",
            category_name=cat,
            mission_type_name=name,
            mission_name=getattr(args, "mission", ""),
            card_num=str(args.cards),
            level=getattr(args, "level", "默认等级"),
            run_times=0,
            plan_times=n,
            auto_battle_config="全配队通用",
            predefined_team_idx=0,
        ))
    try:
        # 默认不循环：--times N 就是刷 N 次，刷完停。
        # 之前写死 True，导致 --times 1 也会把电量全跑光（实测 240 → 0）。
        cfg.loop = bool(getattr(args, "loop", False))
        cfg.daily_reset_plan_times = True
    except Exception:
        pass
    cfg.save()
    print(f"\n已写入 {len(cfg.plan_list)} 条计划：")
    for it in cfg.plan_list:
        print(f"  {it.category_name} · {it.mission_type_name} ×{it.plan_times}")

    if args.plan_only or not args.run:
        print("\n（只写配置。加 --run 才真正开跑）")
        return 0

    from zzz_od.application.charge_plan.charge_plan_app import ChargePlanApp
    if not ctx.run_context.start_running():
        print("运行上下文启动失败")
        return 3
    app = ChargePlanApp(ctx)
    result = app.execute()
    ctx.run_context.stop_running()

    # **必须检查 result.success，不能只打印对象。**
    #
    # 实测：`--training 代理人技能 --times 1 --run` 返回 exit 0，
    # 打印 `<OperationResult object at 0x...>`，**但电量一点没扣（198→199，只是自然恢复）**。
    # 也就是说「跑完了」是假的 —— 它压根没进副本，然后 exit 0 骗过了调用方。
    #
    # 这类「exit 0 但什么都没做」最难查：上层以为成功，继续往下走。
    _ok = bool(getattr(result, "success", False))
    if _ok:
        print(f"\n执行成功：{getattr(result, 'status', '')}")
    else:
        _why = getattr(result, "status", "") or str(result)
        print(f"\n✘ 执行失败：{_why}")
        # 这个返回码要能让上层区分「没跑」和「跑成了」
        return 4

    # 真跑完了才记周本次数
    try:
        from core import weekly as _wk
        for _cat, _name, _n in plans:
            if _cat in ("恶名狩猎", "哨站后勤"):
                _wk.record(_cat)
                _u = _wk.used(_cat)
                print(f"  记一次 {_cat}：本周 {_u}/{_wk.LIMITS.get(_cat, '?')}")
    except Exception as _e:
        print(f"  （记周本次数失败：{_e}）")
    # **刷成功后记账**（E31）：闸门的依据就是这个文件。
    try:
        from core import farm_log as _fl2
        _fl2.append(dungeon=str(getattr(args, 'patrol', '') or ''),
                    times=sum(n for _c, _n, n in plans), ok=True,
                    source='od_material_farm')
    except Exception as _e:
        print(f'  （记账失败：{_e}）')
    return 0


if __name__ == "__main__":
    sys.exit(main())
