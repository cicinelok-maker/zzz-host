"""精化扫描规则：减少误报，只报真正有风险的。

## 第一版的问题

| 规则 | 第一版 | 问题 |
|---|---|---|
| A rolls | 1 处 | 误报：那是 `estimate_cost` 在钳制卡片数，不是 rolls |
| B 兜底 | 0 处 | ✔ |
| C 标题判定 | 3 处 | 误报倾向：「驱动盘筛选」这个标题实测**能**读到 |
| D 点击不验证 | 95 处 | 噪音太大：大部分点击（点一张盘只为读它）本来就不需要验证 |
| E 坐标注释 | 23 处 | 纯格式要求，价值低 |

## 精化后的规则

- **A**：只在函数名含 `roll` 的上下文里查
- **C**：只报「面板内部的小标题」（音擎推荐那种），已知能读到的不报
- **D**：只报**导航类点击**（点拆解/回收/推荐/筛选/智能弃置/装备/替换）后不验证的
- **E**：去掉（改成建议，不算问题）
"""
from __future__ import annotations

import pathlib

import re
from pathlib import Path
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

BASE = pathlib.Path(__file__).resolve().parent.parent
TOOLS = BASE / "tools"
CORE = TOOLS / "core"

# 实测能正常读到的面板标题（不要报警）
READABLE_TITLES = {"驱动盘筛选", "音擎筛选", "驱动盘拆解", "智能弃置", "音擎回收"}

# 导航类动作：点完必须确认到了新界面
NAV_WORDS = ["拆解", "回收", "推荐", "筛选", "智能弃置", "装备", "替换",
             "强化", "进阶", "确认", "转换", "获取"]


def py_files():
    for f in sorted(TOOLS.glob("*.py")) + sorted(CORE.glob("*.py")):
        if f.name.startswith(("audit_", "_", "selftest_")):
            continue
        yield f


def rule_a(text: str):
    """rolls 类函数里返回最少 1。"""
    hits = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not re.match(r"\s*def (rolls?|rolls_of|upgrades)\(", line):
            continue
        # 看函数体里有没有 max(1,
        for k in range(i + 1, min(len(lines), i + 15)):
            if re.match(r"\s*def ", lines[k]):
                break
            if "max(1," in lines[k]:
                hits.append((k + 1, lines[k].strip()[:70]))
    return hits


# 规则 B：破坏性动作绝不做 or 兜底
# 历史 bug：hit = find("替换") or find("卸下") —— 找不到「替换」就点了「卸下」，
# 把装备卸下来了。破坏性动作不许兜底。
DESTRUCTIVE = ["卸下", "拆解", "删除", "放弃", "清空", "重置", "取消",
               "分解", "回收", "出售"]


def rule_b(text: str):
    hits = []
    for line_no, line in enumerate(text.splitlines(), 1):
        code = line.split("#")[0]
        if " or " not in code:
            continue
        if "find(" not in code and "find_all(" not in code:
            continue
        for d in DESTRUCTIVE:
            if f'"{d}"' in code or f"'{d}'" in code:
                hits.append((line_no, code.strip()[:72], d))
                break
    return hits


def rule_c(text: str):
    """用面板标题判定面板开没开，且该标题不在「实测能读到」的名单里。"""
    hits = []
    for line_no, line in enumerate(text.splitlines(), 1):
        code = line.split("#")[0]
        if not re.search(r"in\s+(?:ui\.)?vs\.debug_text\(\)", code):
            continue
        q = re.findall(r'["\']([^"\']{2,10})["\']', code)
        if not q:
            continue
        word = q[0]
        if word in READABLE_TITLES:
            continue
        # 只关心「像面板标题」的词
        if any(t in word for t in ("面板", "推荐", "详情", "定制", "强化")):
            hits.append((line_no, code.strip()[:72], word))
    return hits


def rule_d(text: str):
    """导航类点击之后没有任何验证。"""
    hits = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        code = line.split("#")[0]
        if "find(" not in code:
            continue
        q = re.findall(r'["\']([^"\']{2,8})["\']', code)
        if not q or not any(w in q[0] for w in NAV_WORDS):
            continue
        # 这一行是「找按钮」，下一行通常是点击
        nxt = lines[i + 1].split("#")[0] if i + 1 < len(lines) else ""
        if "inp.click(" not in nxt:
            continue
        # 往后 4 行里有没有验证
        window = "\n".join(l.split("#")[0] for l in lines[i + 2:i + 6])
        verified = any(k in window for k in
                       ("anchors.is_", "click_verify", "click_until",
                        "in_panel(", "in_detail(", "__in_recommend"))
        if not verified:
            hits.append((i + 2, nxt.strip()[:70], q[0]))
    return hits



def rule_e(text: str):
    """用了 inp.click/key/pad_tap 注入输入，但文件里没有 ui.start()。

    历史 bug：zzz_launch.py 直接 Vision(), Input() 然后 inp.click(...)，
    没有 Ui.start() —— 权限闸（is_admin）就覆盖不到它。
    普通权限下的表现：游戏起得来，然后在标题页白等满 120 秒，
    最后报「等进入游戏超时」exit=3，看不出是权限问题。

    闸只保护「走过闸的路径」；这条规则检查「谁没走」。
    """
    import re as _re
    # 有实际输入注入吗（注释掉的不算）
    code_only = "\n".join(l.split("#")[0] for l in text.splitlines())
    if not _re.search(r"\binp\.(click|click_item|key|key_down|key_up|pad_tap|"
                      r"pad_taps|wheel|scroll)\(", code_only):
        return []
    # 有 start() 吗
    if _re.search(r"\.start\(\)", code_only):
        return []
    # 自己定义 Input 的模块（core/input.py）不算
    if "class Input" in code_only:
        return []
    # 已有 is_admin 闸的也不算（zzz_launch 就是这种）
    if "is_admin" in code_only:
        return []
    # 只在「自己构造 Input()」的地方报 ——
    # click.py / locate.py / flows.py / machine.py 都是接收 ui/inp 参数的辅助函数，
    # 调用方已经走过 Ui.start()，不是它们的问题。
    if not _re.search(r"\bInput\(\)", code_only):
        return []
    # 标出第一次注入调用
    for i, line in enumerate(text.splitlines(), 1):
        code = line.split("#")[0]
        if _re.search(r"\binp\.(click|click_item|key|pad_tap)\(", code):
            return [(i, line.strip()[:70])]
    return []


RULES = [
    ("A", "rolls 类函数返回最少 1（口径B 重复计数）", rule_a),
    ("B", "破坏性动作做了 or 兜底（会执行错误动作）", rule_b),
    ("C", "用未验证能读到的面板标题判定", rule_c),
    ("D", "导航类点击后不验证是否到达", rule_d),
    ("E", "注入了按键/点击但没走 Ui.start() 的权限闸", rule_e),
]


def main() -> int:
    results = {k: {} for k, _, _ in RULES}
    for f in py_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        for key, _d, fn in RULES:
            hits = fn(text)
            if hits:
                results[key][f.name] = hits

    for key, desc, _fn in RULES:
        data = results[key]
        total = sum(len(v) for v in data.values())
        print(f"\n{'=' * 74}")
        print(f"规则 {key}：{desc}　{'✔ 无' if total == 0 else f'⚠ {total} 处'}")
        print("=" * 74)
        for name, hits in sorted(data.items()):
            print(f"\n  {name}")
            for h in hits[:8]:
                print(f"    L{h[0]:<4} {' | '.join(str(x) for x in h[1:])}")

    print()
    print("=" * 74)
    for key, desc, _fn in RULES:
        total = sum(len(v) for v in results[key].values())
        print(f"  规则 {key}：{total:>3} 处　{desc}")
    # **有问题就返回非 0**（BUG-043）。
    # 原来恒 return 0，而 audit_ship 只认退出码 —— 这一项结构上不可能变红。
    _issues = sum(len(v) for v in results.values()) if isinstance(results, dict) else sum(results)
    if _issues:
        print(f"\n✘ {_issues} 处问题")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())