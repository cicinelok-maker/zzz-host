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
        """准备工作：权限闸 + 前台 + 键鼠态

        **权限闸放这里**：所有会动游戏的工具都经过 Ui.start()。
        `is_admin()` 是确定性查询，不依赖任何注入结果 ——
        而 `SendInput` 的返回值在 UIPI 拦截下是看不出来的（返回 1）。
        """
        from .input import InputBlocked, is_admin
        if not is_admin():
            # 打印干净的消息 + SystemExit(2)，不抛裸异常 ——
            # 那样新手看到 400 行堆栈，最后那段话被埋在最底下。
            # SystemExit 不打印 traceback，退出码也对。
            print("✘ 需要管理员权限")
            print("  没有管理员权限时，Windows UIPI 会静默丢弃所有按键/点击，")
            print("  工具不报错，而是白等到超时（实测 150~254 秒）。")
            print()
            print("  正确用法：右键终端 → 以管理员身份运行")
            print("  或跑项目根的：.\\admin.ps1")
            print("    它会自动提权重开，并列出常用命令")
            raise SystemExit(2)
        import live
        live.foreground(self.vs.win)
        # 抢前台之后游戏有焦点切换 + 淡入动画。固定 sleep(0.3) 不够 ——
        # 第一帧常常是过渡画面，describe() 会判成「未知界面」，
        # 而 reset_to_world 拿到「未知」就会立刻按 ESC，
        # ESC 在大世界是「打开菜单」，越按越不像 → 反复重试（实测多花 28 秒）。
        # 用 wait_still 等画面真的不动，比猜一个固定秒数可靠。
        try:
            self.vs.wait_still(quiet=0.25, timeout=2.5)
        except Exception:
            time.sleep(0.5)          # wait_still 不可用时退回固定等待
        self.inp.mouse_mode()
        # 切输入模式本身也会让画面变一下，再稳一次
        try:
            self.vs.wait_still(quiet=0.2, timeout=1.5)
        except Exception:
            time.sleep(0.3)
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


    # ---------- 手柄 ----------
    def press(self, button: str, wait: float = 0.45) -> None:
        self.inp.pad_tap(button, wait=wait)


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
