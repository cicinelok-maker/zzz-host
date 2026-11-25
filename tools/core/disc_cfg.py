"""驱动盘相关的一切常量：区域、阈值、坐标。**唯一权威来源**。

## 为什么需要这个文件

体检发现三类冲突（2026-11-24）：

1. `R_DETAIL` 在 8 个文件里有 8 种不同的值
   —— 其实是**不同界面详情位置不同**，但名字一样，极易误用：
        驱动仓库 / 拆解页   右侧 (1400,180,1910,960)
        驱动盘定制页        左中 (500,120,900,980)
        音擎详情页          左中 (400,120,1100,760)

2. `KEEP_MIN` 两个值：zzz_disc_cycle=5.0、zzz_disc_train=2.0
3. `THRESHOLD` 两个值：uifp=4.0、zzz_mark=2.0

## 使用方式

    from core.disc_cfg import REGIONS, THRESHOLDS, XY

    vs.text(REGIONS["驱动仓库"]["detail"])
    if eff >= THRESHOLDS["keep"]: ...

## 重要：读盘统一用全屏

实测最稳的读法是**读全屏再按关键词切**（`read_full` 里的做法），
因为详情区位置随界面变，而全屏文字顺序是可靠的：

    ... 拂晓行纪[1] | 等级15/15 | 主属性 | 生命值 | 2200
        | 副属性 | 攻击力+2 | 9% | ... | 套装效果 | ...
"""
from __future__ import annotations

# ---------------------------------------------------------------- 区域
REGIONS = {
    # 驱动仓库：详情在右侧
    "驱动仓库": {
        "detail": (1400, 180, 1910, 960),
        "subs": (1420, 510, 1900, 810),
        "grid": (60, 120, 1000, 980),
        "list": (60, 200, 1000, 940),
        "top": (0, 100, 700, 180),
    },
    # 驱动盘拆解页：详情在右侧，网格占左半
    "驱动盘拆解页": {
        "detail": (1400, 180, 1910, 960),
        "subs": (1420, 510, 1900, 810),
        "grid": (60, 120, 1100, 980),
        "top": (0, 0, 1200, 120),
        "bottom_bar": (0, 900, 900, 1080),
    },
    # 驱动盘定制页：详情在**左中**，和上面两个完全不同
    "驱动盘定制": {
        "detail": (500, 120, 900, 980),
        "subs": (520, 400, 900, 800),
        "list": (60, 200, 1000, 940),
        "bottom": (0, 880, 1920, 1080),
    },
    # 音擎详情页
    "音擎详情": {
        "detail": (400, 120, 1100, 760),
        "list": (60, 140, 620, 990),
        "panel": (240, 160, 1920, 960),
    },
    # 筛选面板（叠加在右半，左边网格可见并实时刷新）
    "驱动盘筛选面板": {
        "panel": (1140, 90, 1920, 1080),
        "bottom": (1300, 780, 1920, 1000),
    },
}

# ---------------------------------------------------------------- 阈值
# 口径B：有效词条 = 存在(1) + 升级次数，次选算 0.5
THRESHOLDS = {
    # 单块盘的判定（口径B）
    "keep": 5.0,        # >= 5.0 留
    "junk": 3.0,        # <  3.0 废（可拆）
    # 3.0 ~ 5.0 之间算过渡

    # 角色总量目标（口径B）
    "graduation": 28.0,     # 小毕业
    "combat_ready": 32.0,   # 实战够用
    "max": 37.0,            # 大毕业

    # 安全阀
    "max_dismantle_ratio": 0.5,
    # 调律门槛：当前这块潜力低于这个才值得花母盘去调
    "tune_floor": 2.5,   # 一次最多拆总数的 50%
}

# ---------------------------------------------------------------- 坐标
XY = {
    # 驱动仓库
    "仓库_拆解按钮": (365, 930),

    # 拆解页
    "拆解页_漏斗": (84, 1031),
    "拆解页_智能弃置": (561, 1028),
    "拆解页_拆解": (1716, 900),
    "拆解页_右上批量操作": (1708, 1031),

    # 筛选面板
    "筛选_已弃置": (1425, 441),
    "筛选_重置": (1431, 1028),
    "筛选_排除筛选": (1754, 900),
    "筛选_数量1": (1334, 900),
    "筛选_数量2": (1428, 900),
    "筛选_数量3": (1523, 900),
    "筛选_数量4": (1617, 899),

    # 筛选面板顶部排序（用户提示，2026-11-24）
    "筛选_排序下拉": (1362, 164),
    "筛选_排序_等级": (1341, 307),
    "筛选_排序_方向": (1810, 162),   # 点一次=高→低，两次=低→高

    # 筛选面板里的属性选项（展开副词条后）
    "词条_攻击力": (1424, 727),
    "词条_攻击力百分比": (1705, 727),
    "词条_穿透值": (1425, 842),
    "词条_暴击率": (1705, 842),
    "词条_暴击伤害": (1424, 900),
    "词条_异常精通": (1705, 900),

    # 弹窗确认（实测截图量出来的，OCR 找不准）
    "弃置确认": (1128, 679),
    "拆解确认": (1107, 644),

    # 装备页空位（没有等级标签，只能写死）
    "空位1": (1231, 309),
    "空位5": (1663, 534),
}

# 通用界面区域（和 anchors/machine 保持一致）
COMMON = {
    "bottom": (0, 900, 1920, 1080),
    "bottom_right": (700, 990, 1920, 1080),
    "top": (0, 0, 1200, 120),
    "full": (0, 0, 1920, 1080),
}

# ---------------------------------------------------------------- 读盘
import re  # noqa: E402

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import disc_stats as ds  # noqa: E402


def parse_full_screen(txt: str) -> dict:
    """从全屏 OCR 文本里解析一块盘。

    这是**唯一可靠的读盘方式**：
        详情区位置随界面变（仓库右侧 / 定制页左中），
        但全屏文字顺序是稳定的：
            拂晓行纪[1] | 等级15/15 | 主属性 | 生命值 | 2200
                | 副属性 | 攻击力+2 | 9% | ... | 套装效果 | ...
    """
    m = re.search(r"([\u4e00-\u9fa5]{2,6})\[(\d)\]", txt)
    setname = m.group(1) if m else ""
    slot = int(m.group(2)) if m else 0
    ml = re.search(r"等级\s*(\d+)\s*/\s*(\d+)", txt)
    level = int(ml.group(1)) if ml else 0
    cap = int(ml.group(2)) if ml else 15

    subs = []
    if "副属性" in txt:
        seg = txt.split("副属性", 1)[1]
        seg = re.split(r"套装效果|套装|查看", seg)[0]
        parts = [p.strip() for p in seg.split("|") if p.strip()]
        i = 0
        while i < len(parts):
            nm = parts[i]
            if i + 1 < len(parts) and re.fullmatch(
                    r"[+\-]?\d+(?:\.\d+)?%?", parts[i + 1]):
                subs.append((nm, parts[i + 1]))
                i += 2
            else:
                mm = re.match(r"(.+?)\s*([+\-]?\d+(?:\.\d+)?%?)$", nm)
                if mm and not re.fullmatch(r"[+\-]?\d+(?:\.\d+)?%?$", nm):
                    subs.append((mm.group(1).strip(), mm.group(2)))
                i += 1
    from core.zh import canonical_set
    return {"set": canonical_set(setname), "slot": slot, "level": level,
            "cap": cap, "subs_raw": subs}


def effective(subs_raw, good, half) -> tuple[float, list]:
    """算有效值。口径B：存在(1) + 升级次数，次选减半。"""
    from core import vocab as _vb
    eff = 0.0
    rows = []
    for nm, val in subs_raw:
        bare = re.sub(r"\+\d+", "", nm).strip()
        if not bare or _vb.stat_name_of(bare) not in _vb.STATS:
            continue
        pv = ds.parse_value(val)
        if not pv:
            continue
        num, pct = pv
        name, rolls = ds.resolve(nm, num, pct)
        if name == "?":
            continue
        w = ds.is_effective(name, good, half)
        eff += (1 + rolls) * w
        rows.append({"name": name, "value": num, "pct": pct,
                     "rolls": rolls, "weight": w})
    return round(eff, 1), rows
