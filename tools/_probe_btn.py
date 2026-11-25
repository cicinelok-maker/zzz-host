"""验证：[获取] xxx 是不是可点击的按钮？

## 用户的说法（2026-11-26 01:29）

> 你那个点进去那个材料的图片，不是会弹出那个能获取的界面吗，
> 其实那个界面就是那获取的那两个地方，其实是个按钮来的。
> 你能点进去之后，它就会给你传送到那个获取的界面，或者能获取它的地方

## 要验什么

1. 弹窗里 `[获取] 恶名狩猎` 这类文字，OCR 能不能拿到**坐标**
2. 点那个坐标，游戏会不会真的传送到对应界面

## 为什么要紧

如果成立，那**所有副本导航都不用硬编码**：
  想刷刻命残蜕 → 进核心技面板 → 点材料图标 → 点「[获取] 恶名狩猎」→ 到了

比维护 16 个副本的坐标路径可靠得多。
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui  # noqa: E402
from core.machine import Machine  # noqa: E402
import zzz_core  # noqa: E402

AGENT = sys.argv[1] if len(sys.argv) > 1 else "佩洛伊斯"


def main():
    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)

    if not zzz_core.goto_skill_tab(ui, m, AGENT):
        print("到不了技能页")
        return 3

    # 点 E 圈（有材料需求）
    live = zzz_core.locate.core_nodes(vs)
    xy = live.get("E", zzz_core.CORES["E"])
    print(f"点 E 圈 @{xy}")
    inp.click(xy[0], xy[1], wait=1.8)
    vs.frame(force=True)
    txt = vs.text(zzz_core.R_PANEL)
    if "核心技" not in txt:
        print("面板没打开")
        return 4

    # 找材料数字的位置
    import re
    items = vs.items(zzz_core.R_PANEL)
    print(f"\n面板内 {len(items)} 条 OCR：")
    for it in items:
        print(f"  {it.get('text','')[:24]!r} @({it.get('cx')},{it.get('cy')})")

    # 点第一个纯数字（材料数量）上方的图标
    target = None
    for it in items:
        if re.match(r"^\d+$", (it.get("text") or "").strip()):
            target = it
            break
    if not target:
        print("找不到材料数字")
        return 4

    icon_x, icon_y = target["cx"], target["cy"] - zzz_core.MAT_ICON_DY * -1
    icon_y = target["cy"] + zzz_core.MAT_ICON_DY          # DY 是 -36
    print(f"\n点材料图标 @({icon_x},{icon_y})（数字 @({target['cx']},{target['cy']}) 上方 36px）")
    inp.click(icon_x, icon_y, wait=2.0)
    vs.frame(force=True)

    pop_items = vs.items((0, 0, 1920, 1080))
    print(f"\n弹窗内 {len(pop_items)} 条 OCR（**看 [获取] 有没有坐标**）：")
    for it in pop_items:
        t = (it.get("text") or "")
        mark = "  ← 按钮候选" if "获取" in t or "前往" in t else ""
        print(f"  {t[:28]!r} @({it.get('cx')},{it.get('cy')}){mark}")

    # 找「[获取]」的坐标
    btns = [it for it in pop_items if "获取" in (it.get("text") or "")]
    if not btns:
        print("\n✘ 没有「获取」字样的 OCR 条目 —— 可能按钮是图标不是文字")
        inp.key("esc", wait=1.2)
        return 0

    print(f"\n找到 {len(btns)} 个「获取」按钮：")
    for b in btns:
        print(f"  {b['text'][:24]!r} @({b['cx']},{b['cy']})")

    # 点第一个，看会不会传送
    b = btns[0]
    print(f"\n点第一个「{b['text'][:20]}」@({b['cx']},{b['cy']})，看会不会传送…")
    before = vs.text((0, 0, 1920, 1080))
    inp.click(b["cx"], b["cy"], wait=3.0)
    try:
        vs.wait_still(quiet=0.3, timeout=3.0)
    except Exception:
        pass
    vs.frame(force=True)
    after = vs.text((0, 0, 1920, 1080))
    from core import anchors
    print(f"  点之前画面长度 {len(before)}，之后 {len(after)}")
    print(f"  当前界面：{anchors.describe(vs)}")
    print(f"  画面文字前 200 字：{after[:200]!r}")
    changed = after != before
    print(f"  画面变了：{changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
