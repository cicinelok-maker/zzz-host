"""高级 UI 动作：把「看」和「动」组合成有语义的操作。

设计要点
========
* 所有读取都限定区域（见 core/vision.py 的性能说明）
* 每个动作后面尽量带校验，避免「按了但没生效」的假成功
* 滚动到目标、点击直到生效、按 B 脱离未知界面，这些常用套路都封装好了
"""
from __future__ import annotations

import time

from .vision import Vision, Region
from .input import Input


class Ui:
    def __init__(self, vision: Vision | None = None, inp: Input | None = None):
        self.vs = vision or Vision()
        self.inp = inp or Input()

    # ---------- 生命周期 ----------
    def start(self) -> None:
        """准备工作：前台 + 键鼠态"""
        import live
        live.foreground(self.vs.win)
        time.sleep(0.3)
        self.inp.mouse_mode()
        self.vs.frame(force=True)

    # ---------- 点击 ----------
    def click_text(self, keyword: str, region: Region, *, exact: bool = False,
                   wait: float = 0.35, quiet: bool = True) -> bool:
        hit = self.vs.find(keyword, region, exact=exact)
        if not hit:
            if quiet:
                print(f"  [ui] 区域内没找到「{keyword}」")
            return False
        self.inp.click_item(hit, wait=wait)
        return True

    def click_and_wait(self, keyword: str, region: Region,
                       expect_region: Region, expect,
                       timeout: float = 8.0) -> bool:
        if not self.click_text(keyword, region):
            return False
        keys = (expect,) if isinstance(expect, str) else tuple(expect)
        ok = self.vs.wait_for(expect_region, *keys, timeout=timeout)
        if not ok:
            print(f"  [ui] 点了「{keyword}」但没等到 {keys}")
        return ok

    def click_until(self, keyword: str, region: Region,
                    expect_region: Region, expect: str,
                    tries: int = 3, wait: float = 0.4) -> bool:
        """点不到预期结果就重试（界面偶尔不响应第一下）。"""
        for i in range(tries):
            if self.click_text(keyword, region, wait=wait):
                if self.vs.wait_for(expect_region, expect, timeout=4.0):
                    return True
            time.sleep(0.25)
        return False

    def click_template(self, name: str, *, wait: float = 0.5,
                       pad: int = 40, fallback_xy: tuple[int, int] | None = None) -> bool:
        """按模板点固定按钮；找不到就退回坐标（如果有给）。"""
        hit = self.vs.template_at(name, pad=pad)
        if hit:
            self.inp.click(hit[0], hit[1], wait=wait)
            return True
        if fallback_xy:
            self.inp.click(fallback_xy[0], fallback_xy[1], wait=wait)
            return True
        return False

    def click_xy(self, x: int, y: int, wait: float = 0.35) -> None:
        self.inp.click(x, y, wait=wait)

    # ---------- 滚动 ----------
    def scroll_to(self, keyword: str, region: Region, *,
                  watch: Region | None = None, max_notches: int = 12,
                  direction: int = -1) -> bool:
        """滚动列表直到出现目标文字。direction=-1 向下，+1 向上。"""
        watch = watch or region
        for _ in range(max_notches):
            if self.vs.has(watch, keyword):
                return True
            self.inp.wheel(direction, wait=0.4)
            self.vs.frame(force=True)
        return self.vs.has(watch, keyword)

    def scroll_top(self, region: Region, notches: int = 20) -> None:
        """滚回顶部"""
        self.inp.wheel(notches, wait=0.5)
        self.vs.frame(force=True)

    # ---------- 手柄 ----------
    def press(self, button: str, wait: float = 0.45) -> None:
        self.inp.pad_tap(button, wait=wait)

    def press_times(self, button: str, n: int, wait: float = 0.3) -> None:
        self.inp.pad_taps(button, n, wait=wait)

    # ---------- 校验 ----------
    def wait_for(self, region: Region, *keywords: str, timeout: float = 8.0) -> bool:
        return self.vs.wait_for(region, *keywords, timeout=timeout)

    def ensure(self, region: Region, *keywords: str) -> bool:
        return self.vs.has(region, *keywords)

    def back_until(self, region: Region, *keywords: str, limit: int = 8) -> bool:
        """连续按 B 直到出现目标文字（脱离未知界面）。按完切回键鼠态。"""
        for _ in range(limit):
            if self.vs.has(region, *keywords):
                self.inp.mouse_mode()
                return True
            self.inp.pad_tap("b", wait=0.9)
        ok = self.vs.has(region, *keywords)
        self.inp.mouse_mode()
        return ok

    # ---------- 组合动作 ----------
    def click_filter_funnel(self, panel_region: Region, funnel_xy=(135, 922)) -> bool:
        """打开筛选面板：点漏斗 → 验证面板出现"""
        self.inp.click(*funnel_xy, wait=1.4)
        return self.vs.wait_for(panel_region, "稀有度", timeout=4.0) or \
               self.vs.wait_for(panel_region, "套装", timeout=2.0)
