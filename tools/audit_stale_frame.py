"""全代码扫描：找「改完画面后读位置但缓存还没过期」的隐患。

## 精确规则（基于实测的缓存参数）

Vision 有两层缓存：
```
_img       图像缓存，TTL = cache_ms = 120ms
_ocr_cache OCR 文本缓存，TTL = _ocr_ttl = 0.35 秒
```

`frame(force=True)` 会**两个都刷新**（图像重截 + OCR 清空）。

## 所以判定规则

一次「改画面的动作」之后，如果紧接着要「读画面」：

| 情况 | 是否安全 |
|---|---|
| `inp.click(wait >= 0.4)` | ✔ 安全，等的时间超过 OCR TTL |
| `inp.click(wait < 0.4)` 或无 wait | ✘ 危险，读到旧 OCR |
| `inp.key(...)` | 要看 wait |
| `m.go_to(...)` | ✘ 危险——go_to 里的最后一次读帧会把缓存填满，
  紧接着读就是旧内容 |
| 中间有 `frame(force=True)` | ✔ 安全 |

## 为什么要查这个

用户 2026-11-24：「为啥每次都要重点，而且还会失败，就不能固定一个稳定的坐标吗？」

诊断：坐标是稳的（同一点 8/8 成功）。
真因是「改完画面立刻读位置，读到的是上一屏的元素」，
算出来的坐标自然不对。
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TOOLS = BASE / "tools"
CORE = TOOLS / "core"

OCR_TTL = 0.35

# ---- 改画面的动作（带 wait 的会解析出秒数）
CHANGERS = [
    (re.compile(r"\b(?:ui\.)?inp\.click\(([^)]*)\)"), "click"),
    (re.compile(r"\b(?:ui\.)?inp\.key\(([^)]*)\)"), "key"),
    (re.compile(r"\b(?:ui\.)?inp\.wheel\(([^)]*)\)"), "wheel"),
    (re.compile(r"\bm\.go_to\("), "go_to"),
    (re.compile(r"\breset_to_world\("), "reset"),
    (re.compile(r"\bselect_agent\("), "select_agent"),
]

# ---- 读画面的动作
READERS = [
    (re.compile(r"\b(?:vs|ui\.vs)\.find(?:_all)?\("), "find"),
    (re.compile(r"\b(?:vs|ui\.vs)\.items\("), "items"),
    (re.compile(r"\b(?:vs|ui\.vs)\.text(?:_scaled|_verified|_many)?\("), "text"),
    (re.compile(r"\bslot_xy\("), "slot_xy"),
    (re.compile(r"\banchors\.(?:is_|describe)\("), "anchors"),
    (re.compile(r"\blist_discs\(|\blist_engines\("), "list"),
]


def wait_of(args: str) -> float | None:
    """从参数串里解析 wait= 的秒数。"""
    m = re.search(r"wait\s*=\s*([\d.]+)", args)
    if m:
        return float(m.group(1))
    return None


# 已知误报：(文件, 行号) → 原因
# machine.py L382 的 find 在 elif click_text 分支里，是「点击前先找文字」，
# 和 click_xy 分支不是同一条执行路径。
WHITELIST = {
    ("machine.py", 382): "elif 分支，点击前找文字，不是点击后读",
}


def scan(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for i, line in enumerate(lines):
        code = line.split("#")[0]
        changer = None
        wait = None
        for rx, kind in CHANGERS:
            m = rx.search(code)
            if m:
                changer = kind
                if m.lastindex:
                    wait = wait_of(m.group(1) or "")
                break
        if not changer:
            continue
        # go_to / reset / select_agent 一律危险（内部的读帧会填满缓存）
        safe_by_wait = wait is not None and wait >= OCR_TTL + 0.05
        if safe_by_wait:
            continue
        # 往后看 6 行找 reader
        for k in range(i + 1, min(len(lines), i + 7)):
            nxt = lines[k].split("#")[0]
            if "frame(force=True)" in nxt:
                break
            hit = None
            for rx, kind in READERS:
                if rx.search(nxt):
                    hit = kind
                    break
            if hit:
                out.append({
                    "line": i + 1, "code": line.strip()[:62],
                    "changer": changer, "wait": wait,
                    "rline": k + 1, "rkind": hit,
                    "rcode": nxt.strip()[:62],
                })
                break
    return out


def main() -> int:
    files = sorted(TOOLS.glob("*.py")) + sorted(CORE.glob("*.py"))
    all_hits = {}
    for f in files:
        # 跳过审计工具自己、以及自测文件里故意写的坏样本
        if f.name.startswith(("audit_", "_", "selftest_")):
            continue
        hits = [h for h in scan(f)
                if (f.name, h["line"]) not in WHITELIST]
        # 跳过 _legacy
        if "_legacy" in str(f):
            continue
        if hits:
            all_hits[f.name] = hits

    print("=" * 78)
    print("改画面后立即读位置（缓存可能未过期）")
    print("=" * 78)
    if not all_hits:
        print("\n  ✔ 没有发现")
        return 0

    for name, hits in sorted(all_hits.items()):
        print(f"\n{name}　{len(hits)} 处")
        for h in hits:
            w = f"wait={h['wait']}" if h["wait"] is not None else "无 wait"
            print(f"  L{h['line']:<4} {h['changer']}({w})")
            print(f"        └─ L{h['rline']:<4} {h['rkind']}: {h['rcode']}")

    total = sum(len(v) for v in all_hits.values())
    print()
    print(f"→ 共 {total} 处，涉及 {len(all_hits)} 个文件")
    print()
    print("说明：go_to/reset/select_agent 之后的读一律算危险——")
    print("因为它们内部最后一次读帧会把 OCR 缓存填满（TTL 0.35s），")
    print("紧接着的读就是上一屏的内容。")
    # **有问题就返回非 0**（BUG-043）。
    # 原来恒 return 0，而 audit_ship 只认退出码 —— 这一项结构上不可能变红。
    _issues = sum(len(v) for v in all_hits.values()) if isinstance(all_hits, dict) else sum(all_hits)
    if _issues:
        print(f"\n✘ {_issues} 处问题")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
