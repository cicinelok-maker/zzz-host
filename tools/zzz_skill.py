"""技能 / 核心技 强化：读材料需求 → 判断够不够 → 自动升级。

## 摸清的界面

**技能页**（代理人详情的「技能」标签）
```
五个技能格子，等级显示在下方：
  普通攻击(984,700) 闪避(1158,700) 支援技(1332,700) 特殊技(1503,700) 连携技(1679,700)
  等级形如 09/12、08/12（满 12）
点一个技能 → 技能详情页（有描述/属性两个标签）
详情页右下角「技能强化」@(1716,1030) → 强化面板
```

**强化面板**
```
等级6 » 等级7
   伤害倍率 1539.8% » 1636.1%
   失衡倍率 358.1%  » 371.4%
[材料图标] 34/6          ← 拥有34 / 需要6
丁尼 3832294/18000       ← 拥有 / 需要
[确定]
```

    python tools/zzz_skill.py check                 # 只读：五个技能各缺什么
    python tools/zzz_skill.py upgrade               # 材料够的就升
    python tools/zzz_skill.py upgrade --max 3       # 每个技能最多升 3 级
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, Journal, anchors  # noqa: E402
from core.machine import Machine  # noqa: E402
from pick_agent import select_agent  # noqa: E402
from core import locate  # noqa: E402
from core.game_cfg import DEFAULT_AGENT as _DEFAULT_AGENT  # 统一默认角色

# 五个技能格（图标中心）
SKILLS = {
    "普通攻击": (984, 700),
    "闪避": (1158, 700),
    "支援技": (1332, 700),
    "特殊技": (1503, 700),
    "连携技": (1679, 700),
}
R_PANEL = (400, 200, 1550, 950)
R_LVROW = (400, 700, 1400, 800)


def ensure_world(ui: Ui, max_esc: int = 6) -> bool:
    """一路 ESC 退回大世界。

    技能页/详情页之间互相弹跳，靠「返回上一层」推不准；
    退到最外层再从正向走一遍才稳。
    """
    vs, inp = ui.vs, ui.inp
    for i in range(max_esc):
        vs.frame(force=True)
        if anchors.describe(vs) == "世界":
            print(f"  已退回大世界（ESC ×{i}）")
            return True
        inp.key("esc", wait=1.6)
    vs.frame(force=True)
    ok = anchors.describe(vs) == "世界"
    print(f"  退回大世界 {'✔' if ok else '✖ 当前 ' + anchors.describe(vs)}")
    return ok


def goto_skill_tab(ui: Ui, m: Machine, agent: str) -> bool:
    vs, inp = ui.vs, ui.inp
    # 先退到干净起点，避免从技能页/详情页出发时状态混乱
    ensure_world(ui)
    if not select_agent(ui, m, agent):
        return False
    vs.frame(force=True)   # 换角色后必须刷新
    hits = vs.find_all("技能", (0, 0, 1920, 1080))
    if not hits:
        print("  找不到「技能」标签")
        return False
    # 取最靠下那个（底部标签栏）
    h = max(hits, key=lambda i: i["cy"])
    inp.click(h["cx"], h["cy"], wait=2.0)
    vs.frame(force=True)
    # 技能页特征：五个 xx/12 的数字
    return bool(re.search(r"\d{2}\s*12", vs.text((900, 700, 1800, 800))))


def read_skill_levels(vs: Vision) -> dict[str, str]:
    out = {}
    t = vs.text((900, 700, 1800, 800))
    nums = re.findall(r"(\d{2})\s*\n?\s*12|(\d{2})\s+12", t)
    flat = [a or b for a, b in nums]
    for name, lv in zip(SKILLS, flat):
        out[name] = f"{lv}/12"
    return out


def back_to_grid(ui: Ui, max_esc: int = 3) -> bool:
    """回到技能格子页（底部有五个 xx/12 的那页）。

    升级完会停在技能详情页，那里点格子位置是空白，
    下一轮就会一直操作同一个技能（实测只升了第一个）。
    """
    vs, inp = ui.vs, ui.inp
    for _ in range(max_esc):
        vs.frame(force=True)
        if re.search(r"\d{2}\s*12", vs.text((900, 700, 1800, 800))):
            return True
        inp.key("esc", wait=1.2)
    vs.frame(force=True)
    return bool(re.search(r"\d{2}\s*12", vs.text((900, 700, 1800, 800))))


def open_upgrade_panel(ui: Ui, name: str) -> bool:
    """点技能 → 点技能强化 → 面板打开。

    格子位置优先用 OCR 现场读（实测标签会漂 20+ px），
    读不到才退回写死的 SKILLS 坐标。
    """
    vs, inp = ui.vs, ui.inp
    back_to_grid(ui)                      # 必须先确保在格子页
    idx = list(SKILLS).index(name)
    live = locate.skill_cells(vs)
    xy = live[idx] if idx < len(live) else SKILLS[name]
    inp.click(xy[0], xy[1], wait=1.8)
    vs.frame(force=True)
    hit = vs.find("技能强化", (1200, 950, 1920, 1080))
    if not hit:
        print(f"  {name}：找不到「技能强化」按钮")
        return False
    inp.click(hit["cx"], hit["cy"], wait=2.0)
    vs.frame(force=True)
    return vs.has((400, 130, 1200, 220), "技能强化")


def parse_panel(vs: Vision) -> dict:
    """从强化面板读：等级变化、材料拥有/需要、丁尼拥有/需要"""
    txt = vs.text(R_PANEL)
    lv = re.search(r"等级\s*(\d+)\s*\|\s*等级\s*(\d+)", txt)
    if not lv:
        lv = re.search(r"等级(\d+).*?等级(\d+)", txt)
    mats = re.findall(r"(\d+)\s*/\s*(\d+)", txt)
    have_need = []
    for a, b in mats:
        have_need.append((int(a), int(b)))
    return {
        "from": int(lv.group(1)) if lv else -1,
        "to": int(lv.group(2)) if lv else -1,
        "pairs": have_need,
    }


def judge(pairs: list[tuple[int, int]]) -> tuple[bool, str]:
    """判断材料够不够。第一对是技能材料，第二对是丁尼。"""
    if not pairs:
        return False, "读不到材料"
    ok = all(a >= b for a, b in pairs)
    desc = "，".join(f"{a}/{b}{'✔' if a >= b else '✖'}" for a, b in pairs)
    return ok, desc


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("check", "upgrade"):
        p = sub.add_parser(c)
        p.add_argument("--agent", default=_DEFAULT_AGENT)
        p.add_argument("--max", type=int, default=1, help="每个技能最多升几级")
        p.add_argument("--out", default=str(BASE / "state" / "skill_status.json"))
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    log = Journal(f"技能_{args.cmd}")
    ui.start()
    m = Machine(ui, verbose=False)
    print("起点:", anchors.describe(vs))

    if not goto_skill_tab(ui, m, args.agent):
        print("到不了技能页")
        return 3
    levels = read_skill_levels(vs)
    print(f"\n{args.agent} 技能等级：{levels}")

    report = {}
    for name in SKILLS:
        vs.frame(force=True)
        if not open_upgrade_panel(ui, name):
            report[name] = {"error": "面板打不开"}
            continue
        info = parse_panel(vs)
        ok, desc = judge(info["pairs"])
        report[name] = {"from": info["from"], "to": info["to"],
                        "ok": ok, "materials": desc}
        print(f"  {name:<6} 等级{info['from']}→{info['to']}  {desc}  "
              f"{'可以升' if ok else '材料不足'}")
        log.log(name, f"Lv{info['from']}→{info['to']}",
                ok=ok, detail=desc)

        if args.cmd == "upgrade" and ok:
            c = vs.find("确定", (700, 850, 1500, 950))
            if c:
                inp.click(c["cx"], c["cy"], wait=1.6)
                vs.frame(force=True)
                print(f"      → 已升级")
                log.log(name, "升级", ok=True)
                back_to_grid(ui)
            else:
                print("      找不到「确定」")
        else:
            # 关掉面板
            inp.key("esc", wait=1.2)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\n已写入 {args.out}")

    need = [n for n, r in report.items() if not r.get("ok")]
    if need:
        print(f"材料不足的技能：{need}")
    print()
    print(log.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())