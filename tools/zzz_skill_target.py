"""技能升级目标等级：按角色岗位给性价比推荐。

## 用户指出的

**「不同角色有推荐的性价比技能等级升级」**

不是所有技能都堆到 12——那样芯片成本翻几倍，收益很小。
不同岗位的主次技能不一样。

## 常见推荐（按岗位）

    强攻（主C）  普攻 12、特殊技 12、连携技 12、闪避 8、支援技 8
    异常        特殊技 12、连携技 12、普攻 10、闪避 8、支援技 8
    击破        特殊技 12、连携技 12、闪避 8、普攻 8、支援技 6
    支援        特殊技 12、连携技 10、支援技 8、普攻 6、闪避 6
    防护        特殊技 12、连携技 10、闪避 8、普攻 6、支援技 6

技能一共 5 个：
    普通攻击 / 闪避 / 支援技 / 特殊技 / 连携技

## 用法

    python tools/zzz_skill_target.py 佩洛伊斯        # 看目标
    python tools/zzz_skill_target.py --all           # 全部
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent

SKILLS = ["普通攻击", "闪避", "支援技", "特殊技", "连携技"]

# 岗位 → {技能: 目标等级}
TARGETS = {
    "强攻": {"普通攻击": 12, "特殊技": 12, "连携技": 12, "闪避": 8, "支援技": 8},
    "异常": {"特殊技": 12, "连携技": 12, "普通攻击": 10, "闪避": 8, "支援技": 8},
    "击破": {"特殊技": 12, "连携技": 12, "闪避": 8, "普通攻击": 8, "支援技": 6},
    "支援": {"特殊技": 12, "连携技": 10, "支援技": 8, "普通攻击": 6, "闪避": 6},
    "防护": {"特殊技": 12, "连携技": 10, "闪避": 8, "普通攻击": 6, "支援技": 6},
    "命破": {"特殊技": 12, "连携技": 12, "普通攻击": 10, "闪避": 8, "支援技": 8},
}
DEFAULT_ROLE = "强攻"


def load() -> tuple[dict, dict]:
    meta = json.loads((HERE / "disc_meta.json").read_text(encoding="utf-8")).get("角色") or {}
    st = {}
    base = HERE.parent / "state"
    for p in base.glob("status_*.json"):
        name = p.stem.replace("status_", "")
        try:
            st[name] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return meta, st


def cur_levels(agent: str, st: dict) -> dict[str, int]:
    d = st.get(agent) or {}
    skills = d.get("skills") or {}
    out = {}
    for name, v in (skills.items() if isinstance(skills, dict) else []):
        digits = re.sub(r"\D", "", str(v))
        out[name] = int(digits[:2]) if len(digits) >= 2 else 0
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", nargs="?")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    meta, st = load()
    names = [args.agent] if args.agent else sorted(meta)
    if not names:
        print("没有角色数据")
        return 2

    for n in names:
        cfg = meta.get(n) or {}
        role = cfg.get("岗位", DEFAULT_ROLE).split("/")[0]
        tgt = TARGETS.get(role, TARGETS[DEFAULT_ROLE])
        cur = cur_levels(n, st)
        print(f"\n{n}（{role}）")
        if not cur:
            print("  没体检过，读不到当前技能等级")
            print(f"  目标：{'  '.join(f'{k}{v}' for k, v in tgt.items())}")
            continue
        gap_total = 0
        for s in SKILLS:
            have = cur.get(s, 0)
            want = tgt.get(s, 8)
            gap = max(0, want - have)
            gap_total += gap
            flag = "✔" if gap == 0 else f"差 {gap} 级"
            print(f"  {s:<6} {have:>2}/{want:<2}  {flag}")
        print(f"  合计还差 {gap_total} 级技能")
    return 0


if __name__ == "__main__":
    sys.exit(main())
