"""养成收敛循环：一直跑到目标达成或资源耗尽。

## 和 zzz_daily 的区别

    zzz_daily   跑一轮所有养成动作
    zzz_grind   反复跑 zzz_daily，直到达标 / 资源耗尽 / 轮数用完

## 收敛条件（任一满足就停）

    1. 有效词条 ≥ 目标（默认小毕业 28）
    2. 连续 N 轮没有任何进展
    3. 轮数用完
    4. 电量不够且没开 --wait

## 用法

    python tools/zzz_grind.py 佩洛伊斯                       # 只出计划
    python tools/zzz_grind.py 佩洛伊斯 --run                  # 真跑
    python tools/zzz_grind.py 佩洛伊斯 --run --rounds 10
    python tools/zzz_grind.py 佩洛伊斯 --run --wait-charge    # 电量不够就等回体
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
from core.journal import Journal

from core.paths import one_dragon_python, one_dragon_env
PY = one_dragon_python()
ENV = one_dragon_env()
GRADES = {"小毕业": 28.0, "实战够用": 32.0, "大毕业": 37.0}



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

def run(args: list[str], timeout: int = 3600) -> tuple[bool, str]:
    env = dict(os.environ)
    env.update(ENV)
    try:
        r = subprocess.run([PY, "-u"] + args, cwd=str(BASE), env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return False, "超时"


def status(agent: str, max_age: float = 0) -> dict:
    """读角色状态。

    ## `max_age > 0` 时，文件够新就直接用，**不重读游戏**

    原来这里**每次调用都先跑一遍 `zzz_status.py`**（实测约 100 秒）再读文件。
    而它在收敛循环里被调了 3 处：开头 1 次、**每轮 1 次**、结尾 1 次 ——
    `--rounds 5` 就是 7 次 × 100 秒 ≈ **700 秒白花**。

    更关键的是：每轮那次是在 `zzz_daily --run` 之后立刻调的，
    而 `zzz_daily` 收尾本来就会跑一次体检把 status 写新 ——
    **重读等于把刚算出来的东西再算一遍。**

    现在：文件 `_ts` 在 `max_age` 秒内就直接用；否则才重读。
    """
    p = BASE / "state" / f"status_{agent}.json"
    if max_age > 0 and p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            ts = d.get("_ts") or ""
            if ts:
                t0 = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                if time.time() - t0 <= max_age:
                    return d
        except Exception:
            pass                        # 时间戳读不了就走慢路径
    run([str(HERE / "zzz_status.py"), agent, "--json"], 1800)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def charge() -> int:
    """读电量。走 zzz_resource --json，不再正则解析文本。"""
    from core.charge_plan import read_battery_via_cli
    return read_battery_via_cli(PY, str(HERE / "zzz_resource.py"), str(BASE))


# 材料不足 → 该刷的副本（照着 zzz_farm_plan 的 DUNGEON 表）
GAP_TO_FARM = {
    "特化芯片": ["--training", "代理人技能", "--mission", "共鸣测试", "--cards", "5"],
    "认证章":   ["--training", "基础材料", "--cards", "5"],
    "高维数据": ["--challenge", "空域戒戍者"],
    "音擎蓄电池": ["--patrol", "机师与叛甲"],
}


def find_gaps(out: str) -> list[str]:
    """从 zzz_daily 的输出里找出「材料不足」的类别。

    ## **必须按行判断，不能整段判断**（BUG-092）

    原来是：

    ```python
    if key in out and ("不足" in out or "不够" in out):
        found.append(key)
    ```

    两个条件在**整段输出里各自成立**就算命中。于是这段输出：

    ```
    音擎：高维数据 3 个（够）
    技能强化：材料不足
    ```

    `"高维数据" in out` 为真、`"不足" in out` 也为真 →
    **高维数据被误判成不足** → `fill_gaps()` 去刷空域戒戍者 →
    **白花电量刷一个并不缺的本**。

    现在要求「类别名」和「不足/不够」出现在**同一行**里。
    """
    found: list[str] = []
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    for key in GAP_TO_FARM:
        # 同一行里既有类别名、又有「不足/不够」才算
        if any(key in ln and ("不足" in ln or "不够" in ln) for ln in lines):
            found.append(key)
    if not found:
        # 兜底：只有**单独一行说「材料不足」而没说是什么材料**时才猜。
        # 猜错了顶多多刷一次；不猜的话技能材料缺口永远补不上。
        if any("材料不足" in ln for ln in lines):
            found.append("特化芯片")
    return found


def fill_gaps(gaps: list[str], log) -> None:
    """按缺口去刷本补齐。"""
    import subprocess
    import os
    from core.paths import one_dragon_python, one_dragon_env
    PY = one_dragon_python()
    ENV = dict(os.environ)
    ENV = one_dragon_env()
    for g in gaps:
        args = GAP_TO_FARM.get(g)
        if not args:
            continue
        print(f"  → 自动补齐：{g}，刷 {args[0]} {args[1]}")
        cmd = [PY, "-u", str(HERE / "od_material_farm.py")] + args + \
              ["--times", "1", "--run"]
        try:
            r = subprocess.run(cmd, cwd=str(BASE), env=ENV, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=3600)
            ok = "挑战完成" in (r.stdout or "") or "成功" in (r.stdout or "")
            print(f"    补齐{'成功' if ok else '失败'}")
            log.log(f"补齐_{g}", "刷本", ok=ok)
        except Exception as e:
            print(f"    补齐异常：{e}")


def report_feishu(lines: list[str]) -> None:
    """把这一轮的结果发飞书。失败不影响主流程。"""
    import subprocess
    import os
    PY = sys.executable
    try:
        if not (HERE / "feishu.py").exists():
            return
        subprocess.run([PY, "-u", str(HERE / "feishu.py"), "send", "\n".join(lines)],
                       cwd=str(BASE), capture_output=True, timeout=60)
    except Exception:
        pass


def main() -> int:
    log = Journal("grind")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-unknown", action="store_true",
                    help="角色不在库里也继续（按强攻模板判定，可能不准）")
    ap.add_argument("agent")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--target", type=float, default=GRADES["小毕业"])
    ap.add_argument("--wait-charge", action="store_true")
    ap.add_argument("--patience", type=int, default=2, help="连续几轮没进展就停")
    args = ap.parse_args()
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


    print(f"{'=' * 55}")
    print(f"收敛循环：{args.agent}　目标 {args.target} 条有效词条")
    print(f"轮数上限 {args.rounds}　无进展容忍 {args.patience} 轮")
    print(f"{'=' * 55}")

    # **计划模式彻底不碰游戏**（RT-REPORT N-7）。
    #
    # 实测：`zzz_grind` 计划模式跑 **440.7 秒**，产出 `0.0 → 0.0`。
    # 根因不是「循环里读了游戏」，而是**循环外也读**：
    #   · 这行 `status()`      → 起子进程跑 zzz_status，实测 66 秒
    #   · 每轮开头 `charge()`  → 起子进程跑 zzz_resource，实测 48~85 秒
    # 于是 66 + 8 轮 × 48 ≈ 450 秒，和实测 440 秒对得上。
    # 而计划模式每轮都 `continue`，这些读**一个都没用上**。
    if not args.run:
        print("\n[计划] 不读游戏（下面这些是执行模式才会做的）：")
        print(f"  1. 盘点 {args.agent} 的当前状态（约 66 秒）")
        print(f"  2. 最多 {args.rounds} 轮：查电量 → 跑 zzz_daily --run"
              f" → 材料不够就补刷 → 重新盘点")
        print(f"  3. 连续 {args.patience} 轮没进展就停")
        print(f"  目标 {args.target} 条有效词条")
        print("\n要真跑：加 --run")
        return 0

    st = status(args.agent)
    base_total = st.get("total", 0)
    print(f"起点：{base_total} 条　空位 "
          f"{[s for s in range(1, 7) if s not in {x['slot'] for x in st.get('slots') or [] if x.get('set')}]}")

    last_total = base_total
    stagnant = 0
    for i in range(1, args.rounds + 1):
        print(f"\n{'#' * 55}\n# 第 {i} 轮\n{'#' * 55}")
        n_charge = charge()
        print(f"电量 {n_charge}")

        if not args.run:
            print("  [计划] 跑 zzz_daily 一轮")
            continue

        if n_charge >= 0 and n_charge < FARM_COST:
            if args.wait_charge:
                print("  电量不够，等回体…")
                run([str(HERE / "zzz_resource.py"), "wait",
                     "--need", str(FARM_COST)], 36000)
            else:
                print("  电量不够，跳过刷本（其他步骤照跑）")

        ok, out = run([str(HERE / "zzz_daily.py"), args.agent, "--run"], 7200)
        made = len(re.findall(r"实际完成", out))
        print(f"  本轮做成 {made} 个步骤")

        # 失败自动补齐：材料不足就去刷对应的本，然后再跑一次 daily
        gaps = find_gaps(out)
        if gaps and made < 3:
            print(f"  检测到材料缺口：{gaps}")
            fill_gaps(gaps, log)
            print("  补齐后再跑一轮…")
            ok2, out2 = run([str(HERE / "zzz_daily.py"), args.agent, "--run"], 7200)
            made += len(re.findall(r"实际完成", out2))
            out = out + out2

        # `zzz_daily --run` 收尾刚跑过体检，status 是新鲜的 ——
        # 10 分钟内直接用，省一次约 100 秒的重读
        st = status(args.agent, max_age=600)
        total = st.get("total", 0)
        print(f"  当前 {total} 条（起点 {base_total}）")

        # 每轮自动汇报（发飞书，失败不影响主流程）
        try:
            report_feishu([
                f"【养成轮次 {i}】{args.agent}",
                f"做成 {made} 个步骤，当前 {total} 条（起点 {base_total}，目标 {args.target}）",
                f"电量 {n_charge}",
                f"{'★ 已达成目标' if total >= args.target else '未达成，继续'}",
            ])
        except Exception:
            pass

        if total >= args.target:
            print(f"\n✔ 达成目标：{total} ≥ {args.target}")
            break

        if total <= last_total:
            stagnant += 1
            print(f"  无进展 {stagnant}/{args.patience}")
            if stagnant >= args.patience:
                print(f"\n连续 {stagnant} 轮没进展，停止")
                break
        else:
            stagnant = 0
        last_total = total

    st = status(args.agent)
    final = st.get("total", 0)
    print(f"\n{'=' * 55}")
    print(f"结束：{base_total} → {final} 条（目标 {args.target}）")
    if final < args.target:
        print(f"还差 {args.target - final:.1f} 条")
    print(f"{'=' * 55}")
    return 0


if __name__ == "__main__":
    sys.exit(main())