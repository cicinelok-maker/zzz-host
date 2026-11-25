"""完整拆解流程（实测版）：
    驱动仓库 → 拆解页 → 漏斗 → 勾「已弃置」→ ESC（筛选保留）
    → 快速选择 → 全选已弃置 → 确认 → 右侧拆解 → 确认
"""
import sys
from pathlib import Path
import argparse

HERE_ = Path(__file__).resolve().parent
BASE = HERE_.parent

sys.path.insert(0, str(HERE_))
from core import Vision,Input,Ui,Journal# noqa: E402
from core.machine import Machine# noqa: E402
from pick_agent import select_agent# noqa: E402
from PIL import Image# noqa: E402

OUT = str(BASE / "state" / "dismantle_out.txt")
def mesh(vs):
    return len([it for it in vs.items((60, 120, 1100, 980))
                if it["text"].startswith("等级")])


def main() -> int:
    ap = argparse.ArgumentParser()
    from core.game_cfg import DEFAULT_AGENT
    ap.add_argument("agent", nargs="?", default=DEFAULT_AGENT)
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)
    log = Journal("拆解")
    out = []

    if not select_agent(ui, m, args.agent):
        out.append(f"选不中 {args.agent}")
        open(OUT, "w", encoding="utf-8").write("\n".join(out))
        return 3
    if not m.go_to("驱动盘拆解页"):
        out.append("到不了拆解页")
        open(OUT, "w", encoding="utf-8").write("\n".join(out))
        return 4
    vs.frame(force=True)
    out.append(f"拆解页网格：{mesh(vs)} 张")

    # 1) 漏斗 → 已弃置
    inp.click(84, 1031, wait=2.5)
    vs.frame(force=True)
    ok_panel = "驱动盘筛选" in vs.debug_text()
    out.append(f"筛选面板：{ok_panel}")
    if ok_panel:
        ab = vs.find("已弃置", (1300, 380, 1920, 500))
        if ab:
            inp.click(ab["cx"], ab["cy"], wait=2.0)
            vs.frame(force=True)
            out.append(f"勾已弃置后网格：{mesh(vs)} 张")
        inp.key("esc", wait=2.0)
        vs.frame(force=True)
    out.append(f"ESC 后网格：{mesh(vs)} 张")
    Image.fromarray(vs.crop((0, 0, 1920, 1080))[:, :, ::-1]).save(
        r"od_test\shots\dis_filtered_ok.png")

    # 2) 快速选择 → 全选已弃置 → 确认
    q = vs.find("快速选择", (0, 900, 700, 1080))
    out.append(f"快速选择：{bool(q)}")
    if q:
        inp.click(q["cx"], q["cy"], wait=2.2)
        vs.frame(force=True)
        a = vs.find("全选已弃置", (0, 0, 1920, 1080))
        out.append(f"全选已弃置：{bool(a)}")
        if a:
            inp.click(a["cx"], a["cy"], wait=1.8)
            vs.frame(force=True)
            # 数量在「符合以上条件的驱动盘数量：」右边
            lab = vs.find("符合以上条件", (0, 0, 1920, 1080))
            if lab:
                out.append("数量区：" + vs.text(
                    (lab["cx"] - 30, lab["cy"] - 10,
                     lab["cx"] + 400, lab["cy"] + 50)))
            c = vs.find("确认", (0, 0, 1920, 1080))
            if c:
                inp.click(c["cx"], c["cy"], wait=2.5)
                vs.frame(force=True)
    out.append(f"选中后顶部：{vs.text((0, 0, 1200, 120))[:35]}")
    Image.fromarray(vs.crop((0, 0, 1920, 1080))[:, :, ::-1]).save(
        r"od_test\shots\dis_selected.png")

    # 3) 拆解
    d = vs.find("拆解", (1400, 800, 1920, 1050))
    out.append(f"拆解按钮：{bool(d)}")
    if d:
        inp.click(d["cx"], d["cy"], wait=2.5)
        vs.frame(force=True)
        out.append("点拆解后：" + vs.text((0, 0, 1200, 200))[:80])
        Image.fromarray(vs.crop((0, 0, 1920, 1080))[:, :, ::-1]).save(
            r"od_test\shots\dis_confirm.png")
        c2 = vs.find("确认", (600, 450, 1500, 950))
        out.append(f"确认按钮：{bool(c2)}")
        if c2:
            inp.click(c2["cx"], c2["cy"], wait=3.5)
            vs.frame(force=True)
            out.append("拆完：" + vs.text((0, 0, 1400, 300))[:120])
            Image.fromarray(vs.crop((0, 0, 1920, 1080))[:, :, ::-1]).save(
                r"od_test\shots\dis_done.png")
            log.log("拆解", "完成", ok=True)

    open(OUT, "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out))
    print(log.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())