"""角色名归一化：书名号 / 简称 / 繁简 / OCR 错字。

## 用户提醒（2026-11-25）

> 而且好像还有分全名和简称，还有简体繁体的区别，估计也可能会出bug，小心点

**确实出 bug 了**：写完 64 个角色后发现 `11号` 和 `「11号」` 被当成两个。

## 三类问题

**1 书名号**
```
「11号」 / 「席德」 / 「扳机」     ← wiki 用带括号的名
11号 / 席德 / 扳机                ← 游戏里 OCR 读到的可能不带
```

**2 繁简**
```
蕾米埃爾 / 蕾米埃尔
麗娜 / 丽娜
蒼角 / 苍角
```

**3 有「·」的是不同角色 —— 不能去前缀**
```
比利      A · 物理 · 强攻     ← 初始比利
星徽·比利  S · 物理 · 命破     ← 不同角色！
安比      A · 电 · 击破
零号·安比  S · 电 · 强攻       ← 不同角色！
奥菲丝&「鬼火」  S · 火 · 强攻
```

## 所以归一化要做的是

```
1 去掉书名号「」
2 去掉内部书名号（奥菲丝&「鬼火」→ 奥菲丝&鬼火）
3 繁转简
4 去掉空格
5 查别名表（显式声明的简称）
```

**绝不能做**：去掉「·」之前的部分（会把 星徽·比利 变成 比利）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
META = HERE.parent / "disc_meta.json"

# ---------- 繁 → 简（只收角色名里会出现的字）
_T2S = {
    "麗": "丽", "娜": "娜", "蒼": "苍", "傑": "杰", "爾": "尔",
    "蕾": "蕾", "埃": "埃", "諾": "诺", "維": "维", "萊": "莱",
    "貓": "猫", "簡": "简", "賽": "赛", "亞": "亚", "爾": "尔",
    "葉": "叶", "光": "光", "儀": "仪", "玄": "玄", "橘": "橘",
    "福": "福", "柚": "柚", "愛": "爱", "絲": "丝", "薇": "薇",
    "莉": "莉", "蘿": "萝", "蘭": "兰", "貝": "贝", "露": "露",
    "瓏": "珑", "瑪": "玛", "琲": "琲", "珮": "珮", "綺": "绮",
    "黑": "黑", "銀": "银", "礦": "矿", "鐵": "铁", "鑠": "铄",
    "鴉": "鸦", "鳩": "鸠", "鶴": "鹤", "鶯": "莺", "鸞": "鸾",
    "龍": "龙", "鳳": "凤", "島": "岛", "嶼": "屿", "嶺": "岭",
    "雲": "云", "岿": "岿", "崗": "岗", "關": "关", "門": "门",
    "藍": "蓝", "紅": "红", "綠": "绿", "黃": "黄", "澤": "泽",
    "瀨": "濑", "灣": "湾", "織": "织", "綾": "绫", "繪": "绘",
    "櫻": "樱", "楓": "枫", "樹": "树", "橋": "桥", "瀧": "泷",
    "優": "优", "傑": "杰", "傳": "传", "傑": "杰", "偉": "伟",
    "僅": "仅", "億": "亿", "儀": "仪", "兒": "儿", "內": "内",
    "號": "号", "點": "点", "傑": "杰", "癒": "愈", "離": "离",
    "兩": "两", "冊": "册", "凍": "冻", "劃": "划", "勁": "劲",
}


def _to_simplified(s: str) -> str:
    return "".join(_T2S.get(ch, ch) for ch in s)


def normalize_name(name: str) -> str:
    """角色名归一：去书名号、去空格、繁转简。**不去「·」前缀**。"""
    if not name:
        return ""
    s = str(name).strip()
    # 去所有书名号（包括中间的）
    s = s.replace("「", "").replace("」", "")
    s = s.replace("『", "").replace("』", "")
    s = s.replace("《", "").replace("》", "")
    # 去空格和全角空格
    s = re.sub(r"[\s\u3000]+", "", s)
    # 繁转简
    s = _to_simplified(s)
    return s


_cache: dict | None = None


def _alias_map() -> dict:
    """归一化名 → 库里的正式名。"""
    global _cache
    if _cache is not None:
        return _cache
    out = {}
    try:
        d = json.loads(META.read_text(encoding="utf-8"))
        chars = d.get("角色") or {}
        for official in chars:
            out[normalize_name(official)] = official
        # 显式别名（用户手写的简称 → 正式名）
        for alias, official in (d.get("别名") or {}).items():
            out[normalize_name(alias)] = official
    except Exception:
        pass
    _cache = out
    return out


def canonical_agent(name: str) -> str:
    """把任意写法的角色名映射到库里的正式名。找不到返回归一化后的输入。"""
    n = normalize_name(name)
    if not n:
        return ""
    m = _alias_map()
    if n in m:
        return m[n]
    # **不做「·」尾巴兜底**（RT 实测：canonical_agent('星徽·安比') = '安比'）。
    #
    # 原来会把完整名字拆成尾巴去匹配，等于凭空认定它们同一个人。
    # 代价是「星徽·比利」这种写法不再自动变成「比利」——
    # 但它会**明确失败**，而不是静默挑一个角色去操作。
    #
    # 如果真的存在别名关系，应该在 `_alias_map()` 里显式登记，
    # 而不是靠字符串尾巴猜。
    return n


def report() -> str:
    m = _alias_map()
    lines = [f"角色名索引：{len(m)} 条"]
    # 找归一化后撞车的（不同正式名归一到同一个 key）
    from collections import defaultdict
    rev = defaultdict(list)
    try:
        d = json.loads(META.read_text(encoding="utf-8"))
        for official in (d.get("角色") or {}):
            rev[normalize_name(official)].append(official)
    except Exception:
        pass
    dup = {k: v for k, v in rev.items() if len(v) > 1}
    if dup:
        lines.append(f"  ⚠ 归一化后撞车 {len(dup)} 组：")
        for k, v in dup.items():
            lines.append(f"      {k} ← {v}")
    else:
        lines.append("  ✔ 没有撞车")
    return "\n".join(lines)


def same_agent(a: str, b: str) -> bool:
    """两个名字是不是同一个角色（归一化后比较）。

    用于 OCR 结果 vs 用户输入的比较 —— OCR 可能繁简混用、多个空格。
    """
    if not a or not b:
        return False
    return canonical_agent(a) == canonical_agent(b)


def lenient_match(a: str, b: str, max_dist: int = 1) -> bool:
    """宽松比较：完全相同 / 归一化后相同 / 归一化后编辑距离 <= max_dist。

    用于「OCR 读出来的名字」vs「用户输入的名字」——
    OCR 会把形近字读错（斯→依、洛→落），裸比较会漏。

    不同角色名之间的距离通常 >= 2（佩洛伊斯 vs 洛克茜 = 4），
    所以允许 1 个字错不会误匹配。
    """
    if not a or not b:
        return False
    if a == b or same_agent(a, b):
        return True
    na, nb = normalize_name(a), normalize_name(b)
    if na == nb:
        return True

    # **短名字必须全等**（RT 实测：本↔柳、简↔雅、柳↔照 全是误配）。
    #
    # 单字/双字名之间「差一个字」不是 OCR 抖动，是**另一个角色**：
    #   本 vs 柳   距离 1（替换）→ 原来是 True
    #   安比 vs 安东 距离 1        → 原来是 True
    # 而 `lenient_match` 用来判断「切过去的是不是我要的人」，
    # 误配的后果是**在别人的角色上做破坏性操作**。
    if len(na) <= 2 or len(nb) <= 2:
        # **例外：长的那个 ≥3 字，且短的是它的前缀** ——
        # 这是 OCR 截断（露西 → 露），方向和后果都安全：
        # 只可能把「我要的」认成「它的前缀」，不会把两个不同角色认成同一个。
        # （本↔柳、简↔雅、柳↔照 都不是前缀关系，仍然拦住）
        short, long_ = (na, nb) if len(na) < len(nb) else (nb, na)
        return len(long_) >= 3 and long_.startswith(short)

    if abs(len(na) - len(nb)) > max_dist:
        return False
    # Levenshtein
    if na == nb:
        return True
    la, lb = len(na), len(nb)
    prev = list(range(lb + 1))
    for i, ca in enumerate(na, 1):
        cur = [i]
        for j, cb in enumerate(nb, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
            if cur[-1] > max_dist and i == la:
                pass
        prev = cur
        if min(prev) > max_dist:
            return False
    return prev[-1] <= max_dist
