"""枚举养成指南覆盖的角色（⊞ → 选择代理人 → 滚动读全）。

## 用户纠正（2026-11-26 12:27）

> 网格是能鼠标滚动的

**我上一轮说「养成指南只覆盖 6 个角色」—— 错的。**
那只是第一屏，没滚动。

实测滚动之后：

```
第一屏   挽昼 知更鸟 诺姆 赛维里安 丽娜 简                     (6)
滚 4     妮可 露西 派派 安比 苍角 真斗 可琳 比利 安东 本 波可娜 潘引壶  (12)
滚 8     格莉丝 艾莲 悠真 柳 朱鸢 青衣                        (6)
滚 12    「扳机」仪玄 零号·安比 橘福福 爱丽丝 柚叶 叶瞬光 卢西娅…  (13)
滚 16    爱芮 南宫羽 希希芙 星徽·比利 普罗米娅 希格莉德…        (10)
```

**加起来约 47 个 —— 覆盖面和 disc_meta 的 64 个基本相当。**

## 所以「养成指南能当攻略来源」这个判断**重新成立**

（但要注意：它覆盖的是「有这个版本攻略的」，不是全角色。
 具体缺谁要靠这个工具和 roster 对比。）

## 用法

```powershell
python tools/zzz_guide_agents.py            # 列出养成指南覆盖的角色
python tools/zzz_guide_agents.py --diff     # 和 roster 对比，看缺谁
```

## 顺带：这个网格比顶部那条斜排选择条好用

· 名字和等级都是**水平文字**，OCR 稳（顶部那条是斜的）
· **可以直接点名字切角色**，不用箭头循环、不会进空槽
"""
from __future__ import annotations
from core import atomic as _aw

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

BASE = HERE.parent
OUT = BASE / "state" / "guide_agents.json"

# ⊞ 网格图标（养成指南右上角）
P_GRID = (1715, 55)
# 网格中央（滚轮落点）
P_GRID_CENTER = (900, 600)

SKIP = {"前瞻", "UP", "S", "A", "B", "☆", "★", "NEW"}
# **OCR 噪声黑名单** —— 实测滚完之后混进来这些碎字：
#   中 / 你 / 山世 / 芜业勺 / 苯上因
# 它们是「等级」「已选」这类小标签被读残的结果，不是角色名。
NOISE = {"中", "你", "我", "的", "山世", "芜业勺", "苯上因", "位T++期7",
         "x1", "SO", "4T+++期7"}


def _names(vs) -> list[str]:
    """读当前屏的角色名（排除标签/等级/碎字）。"""
    import re
    out = []
    for it in vs.items((200, 250, 1700, 1000)):
        t = (it.get("text") or "").strip()
        if not t or t in SKIP:
            continue
        if t.startswith("Lv.") or t.startswith("等级"):
            continue
        if not re.fullmatch(r"[\u4e00-\u9fa5·「」]{1,12}", t):
            continue
        if t in NOISE:
            continue
        out.append(t)
    return out


def enumerate_agents(ui, max_scroll: int = 20) -> list[str]:
    """打开 ⊞ 网格，滚到底，收集所有角色名（去重保持顺序）。"""
    vs, inp = ui.vs, ui.inp

    # 打开网格
    inp.move(P_GRID[0], P_GRID[1])
    time.sleep(0.2)
    inp.click(P_GRID[0], P_GRID[1], wait=2.5)
    try:
        vs.wait_still(quiet=0.4, timeout=3.0)
    except Exception:
        pass
    vs.frame(force=True)

    # 先滚回顶部
    inp.move(P_GRID_CENTER[0], P_GRID_CENTER[1])
    time.sleep(0.2)
    for _ in range(15):
        inp.wheel(6, wait=0.35)
    vs.frame(force=True)

    seen: list[str] = []
    last_sig = ""
    for i in range(max_scroll + 1):
        if i > 0:
            inp.move(P_GRID_CENTER[0], P_GRID_CENTER[1])
            inp.wheel(-4, wait=1.1)
            vs.frame(force=True)

        sig = vs.text((200, 250, 1700, 1000))
        if i > 0 and sig == last_sig:
            break                      # 滚到底
        last_sig = sig

        for n in _names(vs):
            if n not in seen:
                seen.append(n)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description="枚举养成指南覆盖的角色")
    ap.add_argument("--diff", action="store_true",
                    help="和 state/agent_roster.json 对比")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from core import Vision, Input, Ui, anchors
    import zzz_guide

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()

    # 回大世界
    for _ in range(4):
        inp.key("esc", wait=1.4)
        vs.frame(force=True)
        if anchors.describe(vs) == "世界":
            break

    print("进养成指南…")
    if not zzz_guide.open_guide(ui):
        print("✘ 进不去")
        return 3

    print("打开 ⊞ 网格并滚动枚举…")
    names = enumerate_agents(ui)
    print(f"✔ 养成指南覆盖 {len(names)} 个角色")
    print()
    for i, n in enumerate(names, 1):
        print(f"  {i:>2}. {n}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    _aw.write_json(OUT, {"agents": names})
    print()
    print(f"已写入 {OUT}")

    if args.diff:
        rp = BASE / "state" / "agent_roster.json"
        if rp.exists():
            try:
                roster = json.loads(rp.read_text(encoding="utf-8"))
            except Exception:
                roster = {}
            rn = set(roster.keys()) if isinstance(roster, dict) else set(roster)
            gn = set(names)
            print()
            print("=== 和 roster 对比 ===")
            miss = sorted(rn - gn)
            print(f"  账号有、养成指南没攻略：{len(miss)} 个")
            for m in miss:
                print(f"    {m}")
            extra = sorted(gn - rn)
            if extra:
                print(f"  养成指南有、账号没扫到：{len(extra)} 个")
                for m in extra:
                    print(f"    {m}")

    if args.json:
        print()
        print(json.dumps({"agents": names}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
