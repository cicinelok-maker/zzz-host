"""扫描器自测：故意造坏样本，确认每个规则真的能抓到。

## 为什么需要

扫描器报 0 处，可能是：
1. 代码真的干净
2. 扫描器坏了/规则写错了

两者必须能区分。这个脚本往临时目录塞几个已知的坏写法，
检查对应规则是否报警。全过才说明扫描器可信。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("ap", HERE / "audit_patterns.py")
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)

spec2 = importlib.util.spec_from_file_location("asf", HERE / "audit_stale_frame.py")
asf = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(asf)

# ---- 坏样本
BAD_ROLLS = '''
def rolls(s: str) -> int:
    m = re.search(r"\\+(\\d+)", s or "")
    return max(1, int(m.group(1))) if m else 1
'''

GOOD_ROLLS = '''
def rolls(s: str) -> int:
    m = re.search(r"\\+(\\d+)", s or "")
    return int(m.group(1)) if m else 0
'''

BAD_FALLBACK = '''
hit = ui.vs.find("替换", R_BOTTOM) or ui.vs.find("卸下", R_BOTTOM)
'''

GOOD_FALLBACK = '''
hit = ui.vs.find("替换", R_BOTTOM) or ui.vs.find("装备", R_BOTTOM)
'''

BAD_TITLE = '''
if "音擎推荐" in vs.debug_text():
    return True
'''

GOOD_TITLE = '''
if "代理人专属" in vs.debug_text():
    return True
'''

BAD_STALE = '''
m.go_to("装备页")
xy = slot_xy(vs, slot)
'''

GOOD_STALE = '''
m.go_to("装备页")
vs.frame(force=True)
xy = slot_xy(vs, slot)
'''

CASES = [
    ("规则A rolls max(1)", ap.rule_a, BAD_ROLLS, True),
    ("规则A 正确写法不报", ap.rule_a, GOOD_ROLLS, False),
    ("规则B 破坏性兜底", ap.rule_b, BAD_FALLBACK, True),
    ("规则B 非破坏性兜底不报", ap.rule_b, GOOD_FALLBACK, False),
    ("规则C 标题判定", ap.rule_c, BAD_TITLE, True),
    ("规则C 特征词不报", ap.rule_c, GOOD_TITLE, False),
    ("旧帧 无刷新", asf.scan, BAD_STALE, True),
    ("旧帧 有刷新不报", asf.scan, GOOD_STALE, False),
]

print("=" * 66)
print("扫描器自测")
print("=" * 66)
ok = fail = 0
for label, fn, sample, should_hit in CASES:
    try:
        if fn is asf.scan:
            # scan 要文件，写到临时文件
            tmp = HERE / "_selftest_tmp.py"
            tmp.write_text(sample, encoding="utf-8")
            hits = fn(tmp)
            tmp.unlink()
        else:
            hits = fn(sample)
        got = len(hits) > 0
        good = got == should_hit
        mark = "✔" if good else "✗"
        exp = "应报警" if should_hit else "不应报警"
        print(f"  {mark} {label:<26} {exp}　实际 {'报警' if got else '未报警'}"
              + (f"（{len(hits)} 条）" if hits else ""))
        ok += 1 if good else 0
        fail += 0 if good else 1
    except Exception as e:
        print(f"  ✗ {label:<26} 异常 {e}")
        fail += 1

print()
print(f"通过 {ok}/{len(CASES)}")
if fail:
    print("→ 扫描器本身有问题，报 0 处不可信")
else:
    print("→ 扫描器可信：能抓到坏写法，也不会误报好写法")
