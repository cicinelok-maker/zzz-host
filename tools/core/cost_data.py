"""养成成本数据的**单一来源**（E2）。

## 为什么单独一个文件

`ASCEND_CERT` 原来在 `zzz_farm_plan.py` 和 `zzz_cost.py` 里**各写了一份**：

    zzz_farm_plan.py:108   ASCEND_CERT = {20: 4, 30: 20, 40: 20, 50: 30}
    zzz_cost.py:28         ASCEND_CERT = {20: 4, 30: 20, 40: 20, 50: 30}

两份一模一样的常量 = 两份会漂移的真相。改一处忘另一处，
就变成「规划按 A 算、成本按 B 算」，而两边都不报错。

## **还发现数值本身和数据文件对不上**

`tools/materials.json` 的「认证章」段（`_数据源` 写着
「zzz.gg/jp 角色页（7 个角色交叉）」—— 是查证过的）：

    初阶 4 · 高阶 32 · 专属 30        合计 **66**

而代码里是 4 + 20 + 20 + 30 = **74**。**差 8 张**。

审计给的建议是「从 materials.json 生成」，但两者的**分档方式不同**：
代码按等级（20/30/40/50 四档），数据文件按层（初阶/高阶/专属 三层）。
把 66 摊到 4 个档位需要臆造一个映射 —— 那还不如不改。

**所以这里做两件事**：
1. 把常量收成**一份**（就这个文件），两边 import
2. `check_against_materials()` 会在运行时报出差额，让差异**可见**，
   而不是让它继续躺在两个文件里没人发现

真正要把 74 改成 66、以及档位怎么分，要作者按游戏实测定 ——
见 BLOCKED.md 的 E2 条目。
"""
from __future__ import annotations

import json
import pathlib

_TOOLS = pathlib.Path(__file__).resolve().parent.parent
MATERIALS = _TOOLS / "materials.json"

#: 职级晋升认证章（每个档位需要多少张，累计）
#: **数值待作者核实**：合计 74，而 materials.json 合计 66（差 8）。
ASCEND_CERT: dict[int, int] = {20: 4, 30: 20, 40: 20, 50: 30}


def materials_cert_total() -> int:
    """`materials.json` 里「认证章」三层的合计。读不到返回 -1。"""
    try:
        d = json.loads(MATERIALS.read_text(encoding="utf-8"))
        layers = (d.get("认证章") or {}).get("分层") or []
        return sum(int(x.get("数量") or 0) for x in layers)
    except Exception:
        return -1


def check_against_materials() -> list[str]:
    """和 `materials.json` 对账，返回问题列表（空 = 一致 / 查不了）。"""
    want = materials_cert_total()
    if want < 0:
        return []
    got = sum(ASCEND_CERT.values())
    if got == want:
        return []
    return [
        f"认证章合计对不上：代码 {got} 张，materials.json {want} 张"
        f"（差 {got - want}）",
        "两个来源分档方式不同（按等级 vs 按层），需要作者按实测定档位。",
    ]
