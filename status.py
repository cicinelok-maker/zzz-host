"""一屏看全：运行健康度 / 毕业进度 / 今日缺口 / 材料卡点。

    python status.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import zzz_host as zh  # noqa: E402

HIST = BASE / "state" / "loop_history.jsonl"
FARM = BASE / "out" / "farm_task.json"
TODAY = BASE / "out" / "today.json"


def main() -> int:
    cfg = zh.load_cfg()
    roster = zh.load_roster()
    print(f"\n■ 养成托管状态  {datetime.now():%Y-%m-%d %H:%M}")

    # 运行健康
    if HIST.exists():
        rows = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
        ok = sum(1 for r in rows if r.get("ok"))
        last = rows[-1] if rows else {}
        print(f"\n  运行历史   {len(rows)} 轮 / 全绿 {ok} 轮")
        if last:
            steps = " · ".join("%s%.0fs" % (s["name"], s["sec"]) for s in last.get("steps", []))
            flag = "✔" if last.get("ok") else "✖"
            print(f"  最近一轮   {last.get('at')}  {flag}  {steps}")
        # 连续全绿（从最后一条往前数）
        streak = 0
        for r in reversed(rows):
            if r.get("ok"):
                streak += 1
            else:
                break
        print(f"  连续全绿   {streak} 轮")
    else:
        print("\n  运行历史   尚无记录")

    # 进度
    total = len(roster["roster"])
    full = [c["name"] for c in roster["roster"] if len(c.get("dims", [])) >= 3]
    done = [c["name"] for c in roster["roster"]
            if c.get("level", 0) >= 60 and c.get("core") in ("E", "F")]
    print(f"\n  账本       {total} 个角色（三维齐 {len(full)}，等级达标 {len(done)}）")

    # 卡点
    if FARM.exists():
        t = json.loads(FARM.read_text(encoding="utf-8"))
        print(f"\n  材料卡点   合计 {t.get('total_runs', 0)} 次材料本 ≈ {t.get('stamina', 0)} 电量")
        for it in t.get("items", []):
            print(f"             {it['agent']:<8} 缺 {it['lack']:<3} → 刷 {it['runs']} 次")

    if TODAY.exists():
        t = json.loads(TODAY.read_text(encoding="utf-8"))
        tg = t.get("targets", [])
        if tg:
            print("\n  今日目标")
            for x in tg:
                print(f"             {x['agent']:<8} {x['action']:<24} {x['kind']}")

    if FARM.exists():
        t = json.loads(FARM.read_text(encoding="utf-8"))
        if t.get("total_runs"):
            print("\n  待刷副本（现在可以交给刷本，不用手打）")
            print("    python tools/od_farm.py --run        # 按缺口自己刷")
            print("    python tools/od_farm.py --agent 莱卡恩 --times 10 --run")
            runs = t.get("total_runs")
            sta = t.get("stamina")
            print(f"    合计刷 {runs} 次（约 {sta} 电量）")
            alloc = {}
            for it in t.get("items", []):
                alloc[it["agent"]] = alloc.get(it["agent"], 0) + it["runs"]
            print("    分配：" + "、".join(f"{k} {v} 次" for k, v in alloc.items()))

    print(f"\n  定时任务   每天 20:00（任务名：ZZZ养成托管）")
    print(f"  入口       daily.ps1 · tools/loop.py · graduate.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
