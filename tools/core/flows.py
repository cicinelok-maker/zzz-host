"""决策表：把「当前界面 + 目标」映射到动作序列，集中管理。

好处：界面流程改动只改这张表，不用满代码找散落的点击。

用法
====
    from core.flows import FLOWS, run_flow
    run_flow(ui, "打开驱动仓库")
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .vision import Region


@dataclass
class Step:
    """一个原子步骤"""
    action: str                     # click_text / click_xy / wheel / press / wait
    target: str = ""                # 文字或按键名
    xy: tuple[int, int] | None = None
    region: Region | None = None
    expect: tuple[str, ...] = ()    # 完成后期望出现的文字
    expect_region: Region | None = None
    n: int = 1                      # wheel/press 的次数
    wait: float = 0.4
    optional: bool = False


@dataclass
class Flow:
    name: str
    steps: list[Step] = field(default_factory=list)
    note: str = ""


# ---------- 常用区域 ----------
R_TITLE = (0, 0, 900, 220)
R_PANEL = (1100, 100, 1910, 1000)
R_DETAIL = (1400, 180, 1910, 960)


FLOWS: dict[str, Flow] = {
    "打开筛选": Flow("打开筛选", [
        Step("click_xy", xy=(135, 922), wait=1.2,
             expect=("稀有度",), expect_region=R_PANEL),
    ], note="点左下角漏斗"),

    "选套装": Flow("选套装", [
        Step("click_text", target="点击选择", region=R_PANEL, wait=1.2,
             expect=("所选套装",), expect_region=R_PANEL),
    ], note="点「点击选择」打开网格（「套装」只是标题）"),

    "确认筛选": Flow("确认筛选", [
        Step("click_text", target="确认筛选", region=R_PANEL, wait=1.2,
             expect=("驱动仓库[",), expect_region=R_TITLE),
    ]),

    "关闭面板": Flow("关闭面板", [
        Step("press", target="b", wait=1.0),
        Step("mouse_mode", wait=0.2),
    ]),
}


def run_flow(ui, name: str, *, verbose: bool = True) -> bool:
    """执行一条流程，每步按 expect 校验。"""
    flow = FLOWS.get(name)
    if flow is None:
        print(f"  [flow] 未定义的流程「{name}」")
        return False
    if verbose:
        print(f"  [flow] {name}  ({flow.note})")
    for i, st in enumerate(flow.steps, 1):
        ok = _do_step(ui, st)
        if not ok and not st.optional:
            if verbose:
                print(f"    [flow] 第 {i} 步失败：{st.action} {st.target} {st.xy}")
            return False
    return True


def _do_step(ui, st: Step) -> bool:
    a = st.action
    if a == "click_text":
        if st.region is None:
            return False
        ui.inp.click_text = getattr(ui.inp, "click_text", None)  # 兼容
        hit = ui.vs.find(st.target, st.region)
        if not hit:
            return False
        ui.inp.click(hit["cx"], hit["cy"], wait=st.wait)
    elif a == "click_xy":
        if not st.xy:
            return False
        ui.inp.click(st.xy[0], st.xy[1], wait=st.wait)
    elif a == "wheel":
        ui.inp.wheel(-st.n if st.n else -1, wait=st.wait)
    elif a == "press":
        ui.inp.pad_tap(st.target, wait=st.wait)
    elif a == "mouse_mode":
        ui.inp.mouse_mode(wait=st.wait)
    elif a == "wait":
        time.sleep(st.wait)
    else:
        return False

    if st.expect and st.expect_region:
        ok = ui.vs.wait_for(st.expect_region, *st.expect, timeout=6.0)
        return ok
    return True
