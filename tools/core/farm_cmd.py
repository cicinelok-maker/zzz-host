"""副本名 → od_material_farm 参数：**唯一的实现，给多个工具共用**。

## 为什么要有这个模块

原本 `zzz_gap.do_farm` 和 `zzz_daily` 的刷本步骤各写了一份「副本名 → 参数」的判断。

**这正好是我这一轮反复踩的坑** —— 同一个知识写在两个地方就会漂移：
- 属性表：`zzz_gap.CHIP_ATTR` 和 `materials.json` 各一份 → 「感电/电击」不一致
- 芯片副本名：模板在 `materials.json`，但 `zzz_gap` 没用它

**所以抽成 `core/farm_cmd.py`，两边都调它。**

## 路由表

```
恶名狩猎·XXX         → --hunt XXX
实战模拟室·代理人晋升   → --training 代理人晋升
实战模拟室·代理人技能   → --training 代理人技能
实战模拟室·音擎改装    → --training 音擎改装
实战模拟室·基础材料    → --training 基础材料
专业挑战室            → --challenge
其他（区域巡防）       → --patrol XXX
```
"""
from __future__ import annotations

import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
TOOLS = BASE / "tools"

# od_material_farm 支持的训练类型
TRAININGS = ("代理人晋升", "代理人技能", "音擎改装", "基础材料")


def farm_cmd(dungeon: str, times: int, run: bool = True,
             python: str | None = None) -> list[str]:
    """副本名 → od_material_farm 的完整命令行。

    `run=False` 时不带 `--run`（只出计划）。
    """
    import sys
    py = python or sys.executable
    d = (dungeon or "").strip()
    cmd = [py, str(TOOLS / "od_material_farm.py")]

    if d.startswith("恶名狩猎"):
        name = d.split("·", 1)[1] if "·" in d else d
        cmd += ["--hunt", name]
    elif d.startswith("专业挑战室"):
        cmd += ["--challenge"]
    else:
        hit = next((k for k in TRAININGS if k in d), "")
        if hit:
            cmd += ["--training", hit]
        else:
            name = d.split("·", 1)[1] if d.startswith("区域巡防·") else d
            cmd += ["--patrol", name]

    cmd += ["--times", str(max(1, int(times)))]
    if run:
        cmd.append("--run")
    return cmd
