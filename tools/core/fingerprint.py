"""界面指纹：用「区分度」判定当前在哪个页面，而不是命中一个词就认。

## 为什么需要

之前的锚点是「必须包含某些文字」，问题在于**父子页面标题会重叠**：
代理人列表、装备页、技能详情页顶部都有「代理人攻略」，
所以一个 must=("代理人攻略",) 会同时命中四个页面。

## 指纹怎么做

每个页面录一份**完整文字集合**，然后算区分度：

    tf(screen, text)    这个文字在该页面出现
    df(text)            这个文字出现在几个页面

    text 是「独有特征」= 只在一个页面出现（df == 1）
    text 是「共用垃圾」= 出现在很多页面（df 大）

  detect() 给每个页面打分：
        得分 = 命中的独有特征数 × 3
             + 命中的共有特征数 × 1
             - 命中了别的页面的独有特征数 × 2

    取最高分，且必须领先第二名一定差距，否则判为「不确定」。

这样技能页和代理人列表页即使都有「代理人攻略」，
也会因为它们各自还有一堆独有文字（简略描述 / 培养建议 …）而区分开。

## 用法

    python tools/fingerprint.py capture 代理人列表    # 录入当前页面
    python tools/fingerprint.py show                 # 看已录入的指纹与独有特征
    python tools/fingerprint.py detect               # 判定当前页面
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))
# 不硬编码本机路径 —— 用 core.paths 探测（别人的 OneDragon 不在这）
try:
    from core.paths import one_dragon_home as _odh
    _od = _odh()
    if _od:
        for _sub in ("src", "plugins"):
            _p = str(__import__("pathlib").Path(_od) / _sub)
            if __import__("pathlib").Path(_p).is_dir():
                sys.path.insert(0, _p)
except Exception:
    pass

STORE = TOOLS.parent / "state" / "fingerprints.json"

# 这些词太常见，任何页面都可能出现，不参与判定
NOISE = {"UID", "EMPTY", "+", "-", "0", "1", "2", "3", "4", "5", "6",
         "7", "8", "9", "R", "S", "A", "B", "T", "LS", "RS", "LB", "RB",
         "ON", "OFF", "NEW", ": ", "()", "C", "D", "E", "F", "II"}


def _normalize_digits(t: str) -> str:
    """把数字换成 #，让动态数值不影响页面识别"""
    return re.sub(r"\d+", "#", t)


def _norm(t: str) -> str:
    t = t.strip()
    # 纯符号/超短的过滤掉；含数字的做归一化
    if re.search(r"\d", t):
        return _normalize_digits(t)
    return t


def _usable(t: str) -> bool:
    t = _norm(t)
    if not t or t in NOISE:
        return False
    if re.fullmatch(r"[\d.:%/\s]+", t):
        return False          # 纯数字/符号
    if len(t) < 2:
        return False
    return True


def load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def capture(vs, name: str, samples: int = 3) -> dict:
    """录入当前页面的指纹。

    多次采样取**交集**：只在某一次出现的文字（距离「19.5m」、商品名、
    临时提示等）会被过滤掉，留下的才是页面骨架。
    """
    import time as _t
    sets = []
    for i in range(max(1, samples)):
        vs.frame(force=True)
        cur = set()
        for it in vs.items((0, 0, 1920, 1080)):
            t = _norm(it["text"])
            if _usable(t):
                cur.add(t)
        if cur:
            sets.append(cur)
        _t.sleep(0.35)
    if not sets:
        print(f"  「{name}」没读到任何文字")
        return load()
    stable = set.intersection(*sets) if len(sets) > 1 else sets[0]
    dropped = len(set.union(*sets)) - len(stable)
    data = load()
    data[name] = sorted(stable)
    save(data)
    print(f"  已录入「{name}」：稳定 {len(stable)} 条（滤掉 {dropped} 条不稳定）")
    return data


def doc_freq(data: dict) -> Counter:
    """每个文字出现在几个页面里"""
    df = Counter()
    for screen, texts in data.items():
        for t in set(texts):
            df[t] += 1
    return df


# 容易混的页面加「必备特征」：缺了直接判死，不参与打分
REQUIRED = {
    "音擎详情": ("音擎效果",),
    "驱动盘定制": ("驱动盘定制", "拆解"),
    "装备页": (),                 # 靠 MUST_NOT 排除
    "代理人培训": ("代理人培训",),
    "音擎强化面板": ("自动添加",),
    "技能强化面板": ("技能强化",),
    "材料转化": ("材料转化",),
    "调律界面": ("调律",),
}

# 这些页面不能出现某些词（父子页面共标题时的补充判据）
MUST_NOT = {
    "装备页": ("音擎效果", "驱动盘定制"),
}


def passes_required(name: str, seen: set[str]) -> bool:
    req = REQUIRED.get(name) or ()
    if req and not all(any(r in t for t in seen) for r in req):
        return False
    ban = MUST_NOT.get(name) or ()
    if ban and any(any(b in t for t in seen) for b in ban):
        return False
    return True


def detect(vs, data: dict | None = None, verbose: bool = False):
    """给每个页面打分，返回 (页面名, 得分, 是否可信)"""
    data = data or load()
    if not data:
        return None, 0, False
    vs.frame(force=True)
    seen = {_norm(it["text"]) for it in vs.items((0, 0, 1920, 1080))}
    df = doc_freq(data)

    scores: dict[str, float] = {}
    for name, texts in data.items():
        own = set(texts)
        if not own:
            continue
        if not passes_required(name, seen):
            scores[name] = -999
            continue
        hit = 0
        for t in own & seen:
            hit += 3 if df[t] == 1 else 1
        # 按比例归一化：文字多的页面不再天然占优
        score = hit / len(own) * 100
        # 命中了别的页面的独有特征 → 扣分
        penalty = 0
        for other, otexts in data.items():
            if other == name:
                continue
            for t in set(otexts) & seen:
                if df[t] == 1:
                    penalty += 2
        scores[name] = round(score - penalty, 1)

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if not ranked:
        return None, 0, False
    best, bs = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    # 分数下限：页面还没录全时，某个页面的特征可能被别的页面蹭到，
    # 导致误判（实测音擎仓库被认成装备页）。分不够高就不下结论。
    # 比例分下，阈值用 40；第二名差距至少 8 分才算可信
    confident = bs >= 40 and (bs - second) >= 8
    if verbose:
        for n, s in ranked[:5]:
            print(f"    {n:<14} {s}")
    return best, bs, confident


def describe(vs, data: dict | None = None) -> str:
    name, score, ok = detect(vs, data)
    if name is None:
        return "未知界面"
    return name if ok else f"不确定(可能 {name}, 分{score})"