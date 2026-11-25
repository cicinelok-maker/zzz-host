"""缺口 #2 + #3 的实现。

## #2 升级中途止损

现状：`zzz_disc_cycle` 升满再判，浪费镀剂。
改法：每升 3 级读一次，如果累计命中太少就提前放弃。

判定（口径B 下）：
    升级到 Lv3   → 有 1~2 次强化落位
    升级到 Lv6   → 有 2~3 次
    ...
    升级到 Lv15  → 有 5 次

止损规则：
    升完 Lv6（约 2-3 次强化）后，如果有效「升级次数」还是 0 且有效词条 < 2 条
    → 这块盘最多再命中 2-3 次，上限 3~4 条，不如留着镀剂

## #3 调律套装自动推导

现状：`zzz_tune` 要手动指定套装名。
改法：读 `zzz_status` 的套装构成，推出缺什么：
    主套 < 4 件  → 调主套，补缺失的位号
    主套 = 4 件，副套 < 2 件 → 调副套，补缺失的位号
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core.disc_cfg import THRESHOLDS  # noqa: E402
from core.game_cfg import DEFAULT_AGENT as _DEFAULT_AGENT  # 统一默认角色

META = json.loads((HERE / "disc_meta.json").read_text(encoding="utf-8"))


def tune_plan(agent: str, slots: list[dict]) -> dict:
    """从当前装备推出该调什么套装、补哪些位号。

    slots: [{"slot": 1, "set": "拂晓行纪", "level": 15, "eff": 5.5}, ...]
    """
    cfg = (META.get("角色") or {}).get(agent) or {}
    main_set = cfg.get("四件套", "")
    alt = cfg.get("两件套候选") or cfg.get("二件套候选") or []

    have = {s["slot"]: s.get("set") for s in slots if s.get("set")}
    main_slots = [n for n, st in have.items() if st == main_set]
    alt_slots = [n for n, st in have.items() if st in alt]
    empty = [n for n in range(1, 7) if n not in have]

    if len(main_slots) < 4:
        need = 4 - len(main_slots)
        targets = empty + [n for n in range(1, 7) if n not in main_slots and n not in empty]
        return {
            "action": "调主套",
            "set": main_set,
            "slots": targets[:need],
            "reason": f"主套只有 {len(main_slots)} 件，还差 {need} 件",
        }

    if len(alt_slots) < 2:
        need = 2 - len(alt_slots)
        targets = empty + [n for n in range(1, 7)
                           if n not in alt_slots and n not in empty]
        return {
            "action": "调副套",
            "set": alt[0] if alt else "",
            "candidates": alt,
            "slots": targets[:need],
            "reason": f"副套只有 {len(alt_slots)} 件，还差 {need} 件",
        }

    return {
        "action": "不用调",
        "reason": f"4+2 已齐（主 {len(main_slots)} 件 + 副 {len(alt_slots)} 件）",
    }


def should_stop_upgrading(level: int, cap: int, eff: float,
                          eff_rolls: float) -> tuple[bool, str]:
    """升级中途止损判断。

    level      当前等级
    cap        满级（15）
    eff        口径B 有效值
    eff_rolls  有效属性上的升级次数（不含存在分）
    """
    remain = (cap - level) // 3      # 还能升几次
    if level <= 0:
        return False, ""
    # Lv6 之后（约 2~3 次强化落位）仍然一次没命中
    if level >= 6 and eff_rolls == 0:
        return True, f"Lv{level} 已强化 {level//3} 次，有效属性一次没命中"
    # Lv9 之后有效值还很低
    if level >= 9 and eff < THRESHOLDS["junk"] and remain <= 1:
        return True, f"Lv{level} 有效 {eff} 低于及格线，且只剩 {remain} 次"
    return False, ""


def main() -> int:
    """命令行：演示两个功能。"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default=_DEFAULT_AGENT)
    args = ap.parse_args()

    st_path = BASE / "state" / f"status_{args.agent}.json"
    if not st_path.exists():
        print(f"没有 {st_path}")
        return 2
    st = json.loads(st_path.read_text(encoding="utf-8"))
    slots = st.get("slots") or []

    plan = tune_plan(args.agent, slots)
    print(f"=== 调律建议（#3）===")
    print(f"  动作：{plan['action']}")
    if plan.get("set"):
        print(f"  套装：{plan['set']}")
    if plan.get("slots"):
        print(f"  位号：{plan['slots']}")
    print(f"  原因：{plan['reason']}")
    if plan.get("candidates"):
        print(f"  候选：{plan['candidates']}")
    print()

    print("=== 升级止损演示（#2）===")
    for lv in (3, 6, 9, 12):
        for eff_rolls in (0, 1, 2):
            stop, why = should_stop_upgrading(lv, 15, 2.0 + eff_rolls, eff_rolls)
            mark = "停" if stop else "继续"
            print(f"  Lv{lv} 命中{eff_rolls}次 → {mark}"
                  + (f"（{why}）" if why else ""))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())