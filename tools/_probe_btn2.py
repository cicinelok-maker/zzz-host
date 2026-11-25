"""验证用户说的：[获取] xxx 是可点击按钮，点了会传送到获取界面。

上一版探针踩的坑：我把「数字上方 36px」当成图标位置，
但实际材料图标在 y≈890（`MAT_X=(135,265)` + `MAT_ICON_DY=-36`），
和「消耗材料」那几个数字不在同一处。

**这次直接复用 `zzz_core.read_material` 的坐标和流程**，
只是把「弹窗的 OCR 条目（带坐标）」全部打出来，看 [获取] 有没有坐标。
"""
import sys
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

    live = zzz_core.locate.core_nodes(vs)
    # 用 E（有材料需求：刻命残蜕 1/3、高维数据 7/15）
    xy = live.get("E") or zzz_core.CORES["E"]
    print(f"点 E 圈 @{xy}")
    inp.click(xy[0], xy[1], wait=2.0)
    vs.frame(force=True)
    txt = vs.text(zzz_core.R_PANEL)
    print(f"面板文本前 120 字: {txt[:120]!r}")
    if "消考材料" in txt or "消耗材料" in txt:
        print("  ✔ 确认在核心技強化面板（有「消耗材料」）")
    else:
        print("  ⚠ 没看到「消耗材料」，可能不在强化面板")

    # 用 read_material 的坐标：MAT_X = (135, 265), y = 926, icon y = 926 + MAT_ICON_DY
    for mx in zzz_core.MAT_X:
        icon = (mx, 926 + zzz_core.MAT_ICON_DY)
        print(f"\n点材料图标 @{icon}（MAT_X={mx}, 926 + {zzz_core.MAT_ICON_DY}）")
        before = vs.text((0, 0, 1920, 1080))
        inp.click(icon[0], icon[1], wait=2.2)
        vs.frame(force=True)
        pop = vs.text((0, 0, 1920, 1080))
        if pop == before:
            print("  点了没反应（画面没变）")
            continue

        items = vs.items((0, 0, 1920, 1080))
        print(f"  弹窗内 {len(items)} 条 OCR：")
        has_get = False
        for it in items:
            t = (it.get("text") or "").strip()
            if not t:
                continue
            mark = ""
            if "获取" in t:
                mark = "   ← ★ 按钮候选（有坐标，可点）"
                has_get = True
            print(f"    {t[:30]!r} @({it.get('cx')},{it.get('cy')}){mark}")

        if has_get:
            # 找「获取」条目，点它
            btn = next(it for it in items if "获取" in (it.get("text") or ""))
            print(f"\n  点「{btn['text'][:20]}」@({btn['cx']},{btn['cy']}) 看会不会传送…")
            _b4 = vs.text((0, 0, 1920, 1080))
            inp.click(btn["cx"], btn["cy"], wait=3.5)
            try:
                vs.wait_still(quiet=0.3, timeout=3.0)
            except Exception:
                pass
            vs.frame(force=True)
            from core import anchors
            _af = vs.text((0, 0, 1920, 1080))
            print(f"    传送后界面：{anchors.describe(vs)}")
            print(f"    画面变了：{_af != _b4}")
            print(f"    文字前 200：{_af[:200]!r}")
            # 退回来
            inp.key("esc", wait=1.2)
        else:
            print("  弹窗里没有「获取」字样 —— 按钮可能是纯图标")
        inp.key("esc", wait=1.2)
        break

    return 0


if __name__ == "__main__":
    sys.exit(main())
