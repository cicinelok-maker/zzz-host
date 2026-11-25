"""电量规划：今天能刷几次、先刷哪个、什么时候回满。

## 为什么需要（用户 2026-11-25）

「还有电量规划和刷本按缺口你也继续」

现在的做法是「有多少刷多少、固定刷列表第一个」。
但电量和材料都是有限资源，应该按**缺口**分配：

```
有 200 电量，角色缺的是「6 号位主词条攻击力的拂晓盘」+「技能材料」
→ 应该：60 刷区域巡防（出拂晓） + 140 刷实战模拟室（出技能材料）
→ 而不是全刷区域巡防
```

## 电量机制（实测）

```
上限        240
回体速率    6 分钟 / 1 点
满血回满    24 小时
区域巡防    60 / 次
专业挑战室  40 / 次
实战模拟室  20 / 卡（1~5 卡）
```

## 规划逻辑

1. 算「回满还要多久」
2. 按缺口优先级分配电量
3. 算出每种本刷几次
4. 剩余电量留着（不硬花）

## 缺口优先级

```
主词条错        ← 最高（换一块盘就 +30% 乘区）
空位            ← 次高（4 件套可能没激活）
弱位号          ← 中（有效 < 2.0）
技能/核心材料     ← 看缺口
音擎            ← 已满就跳
```
"""
from __future__ import annotations

from core.game_cfg import (
    CHARGE_MAX, COST_PATROL, COST_CHALLENGE, COST_SIM, MAX_CARDS,
)

# 回体速率（分钟/点），实测
MINUTES_PER_CHARGE = 6


def time_to_full(current: int) -> dict:
    """距离电量满还要多久。"""
    lack = max(0, CHARGE_MAX - current)
    total_min = lack * MINUTES_PER_CHARGE
    return {
        "lack": lack,
        "minutes": total_min,
        "hours": round(total_min / 60, 1),
        "readable": (f"{total_min // 60} 小时 {total_min % 60} 分"
                     if total_min >= 60 else f"{total_min} 分"),
    }


def affordable(battery: int) -> dict:
    """这点电量各能刷几次。"""
    return {
        "区域巡防": battery // COST_PATROL,
        "专业挑战室": battery // COST_CHALLENGE,
        "实战模拟室(1卡)": battery // COST_SIM,
        "实战模拟室(5卡)": battery // (COST_SIM * MAX_CARDS),
    }


def report(battery: int) -> str:
    """一段给人看的电量说明。"""
    t = time_to_full(battery)
    a = affordable(battery)
    lines = [f"电量 {battery}/{CHARGE_MAX}"]
    if battery >= CHARGE_MAX:
        lines.append("  ✔ 已满，现在就该花掉（满了不回复）")
    else:
        lines.append(f"  距满 {t['lack']} 点，还要 {t['readable']}")
    lines.append(f"  够刷：区域巡防 {a['区域巡防']} 次 / "
                 f"专业挑战室 {a['专业挑战室']} 次 / "
                 f"模拟室 {a['实战模拟室(5卡)']} 次(5卡)")
    return "\n".join(lines)

def read_battery_via_cli(python: str, script: str, cwd: str,
                         timeout: int = 1200) -> int:
    """跑 zzz_resource check --json 拿电量。读不到返回 -1。

    三个工具（zzz_daily / zzz_grind / zzz_disc_daily）都用这个，
    不要再各自正则解析文本输出 —— 改一下 print 格式就全挂。
    """
    import json
    import subprocess
    try:
        r = subprocess.run([python, "-u", script, "check", "--json"],
                           cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith('{"ok"'):
                d = json.loads(line)
                v = (d.get("data") or {}).get("battery")
                return int(v) if isinstance(v, int) and v >= 0 else -1
    except Exception:
        pass
    return -1