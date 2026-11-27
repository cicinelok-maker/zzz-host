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

# **截图目录用绝对路径，并且自己建**（RT-09）。
#
# 原来是 `r"od_test\shots\dis_filtered_ok.png"` —— **相对路径**，
# 而且全仓没有任何代码创建 `od_test/shots`（`core/__init__.py` 只建
# `state` 和 `od_test`）。`Image.save` 到不存在的目录 ->
# `FileNotFoundError`，**而且发生在 `--run` 闸门之前** ——
# 文档推荐的「先看计划」直接崩。
SHOTS = BASE / "od_test" / "shots"


def _shot(vs, name: str) -> None:
    """存一张截图。**失败不影响主流程** —— 截图是辅助，不是目的。"""
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        Image.fromarray(vs.crop((0, 0, 1920, 1080))[:, :, ::-1]).save(
            str(SHOTS / name))
    except Exception as e:
        print(f"  （截图 {name} 失败：{e}）")
def mesh(vs):
    return len([it for it in vs.items((60, 120, 1100, 980))
                if it["text"].startswith("等级")])


def main() -> int:
    ap = argparse.ArgumentParser()
    from core.game_cfg import DEFAULT_AGENT
    ap.add_argument("agent", nargs="?", default=DEFAULT_AGENT)
    # **必须显式加 --run 才会真拆**（BUG-009）。
    # 原来这个工具没有任何开关，跑起来就直接拆到底，
    # 而 AGENTS.md 还写着「先跑不带 --run 的版本看计划」——对它是假的。
    ap.add_argument("--run", action="store_true",
                    help="真的拆解。不加只统计「会拆多少张」")
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
    _shot(vs, "dis_filtered_ok.png")

    # **闸门：不加 --run 就只看数字，不进选择/拆解**（BUG-009）
    n_will = mesh(vs)
    if not args.run:
        out.append(f"[计划] 会拆 {n_will} 张（已弃置）")
        out.append("       加 --run 才真拆。拆解不可逆，先看清数量。")
        # **说清楚计划模式动了什么**（RT-09）：上面为了数「已弃置」
        # 点开了漏斗、勾了「已弃置」再 ESC —— 不是只读，筛选状态变了。
        out.append("       （计划模式开过筛选面板来数「已弃置」——"
                   "筛选状态被改过，仓库数据没动）")
        open(OUT, "w", encoding="utf-8").write("\n".join(out))
        print("\n".join(out))
        return 0
    if n_will <= 0:
        out.append("[计划] 没有已弃置的盘，不拆")
        open(OUT, "w", encoding="utf-8").write("\n".join(out))
        print("\n".join(out))
        return 0

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
    _shot(vs, "dis_selected.png")

    # 3) 拆解
    d = vs.find("拆解", (1400, 800, 1920, 1050))
    out.append(f"拆解按钮：{bool(d)}")
    if d:
        inp.click(d["cx"], d["cy"], wait=2.5)
        vs.frame(force=True)
        out.append("点拆解后：" + vs.text((0, 0, 1200, 200))[:80])
        _shot(vs, "dis_confirm.png")
        c2 = vs.find("确认", (600, 450, 1500, 950))
        out.append(f"确认按钮：{bool(c2)}")
        if c2:
            inp.click(c2["cx"], c2["cy"], wait=3.5)
            vs.frame(force=True)
            out.append("拆完：" + vs.text((0, 0, 1400, 300))[:120])
            _shot(vs, "dis_done.png")
            log.log("拆解", "完成", ok=True)

    open(OUT, "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out))
    print(log.summary())

    # BUG-009：不再无条件返回 0。
    # 原来拆解一步都没成功也返 0，调用方会以为拆完了。
    _done = any("拆完：" in x for x in out)
    if not _done:
        print("  ✘ 没有走到「拆完」那一步 —— 本次没有确认拆解成功")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())