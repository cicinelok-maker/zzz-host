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
专业挑战室·XXX        → --challenge XXX（**必须带名字**）
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
             python: str | None = None, mission: str = "") -> list[str]:
    """副本名 → od_material_farm 的完整命令行。

    `run=False` 时不带 `--run`（只出计划）。

    ## `mission`：实战模拟室**必须**传

    `od_material_farm` 对 实战模拟室 / 专业挑战室 / 恶名狩猎 强制要求
    `--mission`，缺了直接 exit 2：

        _NEED_MISSION = {"实战模拟室", "专业挑战室", "恶名狩猎"}

    而这里原来**从来不传** —— 于是**所有**实战模拟室的刷本调用
    都是 exit 2，一个都刷不了（芯片/认证章/音擎/经验全中）。

    子任务名来自 `core/mission_map.py`（数据取自 OneDragon 的
    `compendium_data.yml`）。调用方负责算好传进来 ——
    只有 `where_to_farm` 同时知道材料、定位、属性。
    """
    import sys
    py = python or sys.executable
    d = (dungeon or "").strip()
    cmd = [py, str(TOOLS / "od_material_farm.py")]

    if d.startswith("恶名狩猎"):
        name = d.split("·", 1)[1] if "·" in d else d
        cmd += ["--hunt", name]
    elif d.startswith("专业挑战室"):
        # **必须带挑战室名字**（P0-3）。
        #
        # 原来这里是 `cmd += ["--challenge"]` —— **没有值**。
        # 拼出来的命令是：
        #
        #     od_material_farm.py --challenge --times 2 --run
        #
        # argparse 会把 `--times` 当成 `--challenge` 的参数吞掉，
        # 于是 `--times` 消失、挑战室名字变成 `--times` ——
        # 结果「高维数据 / 刻命残蜕」这类**专业挑战室的东西完全刷不了**。
        #
        # 而且它不报错，只是行为不对：用户看到命令跑完了，材料没涨。
        name = d.split("·", 1)[1] if "·" in d else ""
        if not name:
            raise ValueError(
                f"专业挑战室缺少具体名字：{d!r}\n"
                f"  应该写成「专业挑战室·深蚀回路」这样")
        cmd += ["--challenge", name]
    else:
        hit = next((k for k in TRAININGS if k in d), "")
        if hit:
            cmd += ["--training", hit]
        else:
            name = d.split("·", 1)[1] if d.startswith("区域巡防·") else d
            cmd += ["--patrol", name]

    if mission:
        cmd += ["--mission", mission]

    cmd += ["--times", str(max(1, int(times)))]
    if run:
        cmd.append("--run")
    return cmd
