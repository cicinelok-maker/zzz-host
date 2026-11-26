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
    table = json.loads((BASE / "state" / "material_sources.json").read_text(encoding="utf-8"))
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
    cs = BASE / "state" / "core_status.json"
    if cs.exists():
        data = json.loads(cs.read_text(encoding="utf-8"))
        for key, v in data.items():
            if not isinstance(v, dict):
                continue
            costs = v.get("costs") or []
            if len(costs) >= 2 and costs[1][0] < costs[1][1]:
                plans.append(("专业挑战室", "深蚀回路", 2))
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
    ap.add_argument("--instance", type=int, default=1)
    # 2026-11-24 从 od_farm.py 合并过来的参数（避免两个刷本工具重复）
    ap.add_argument("--agent", default=_DEFAULT_AGENT,
                    help="角色名（用于按岗位推导副本类型）")
    ap.add_argument("--patrol-type", default="",
                    help="区域巡防：直接给副本类型名，覆盖 --patrol")
    ap.add_argument("--plan-only", action="store_true", help="只出计划不执行")
    ap.add_argument("--loop", action="store_true",
                    help="刷到电量耗尽（默认 False：只刷 --times 次）")
    ap.add_argument("--use-backup", action="store_true",
                    help="电量不足时使用储蓄电量")
    args = ap.parse_args()

    plans = from_gaps() if args.from_gaps else build_plans(args)

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
    return 0


if __name__ == "__main__":
    sys.exit(main())