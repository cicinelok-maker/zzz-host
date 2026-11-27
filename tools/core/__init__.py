
# ---------------------------------------------------------------- 控制台编码
# **中文 Windows 默认控制台是 cp936（GBK），编不了 `✔ ✘ ⚠ ✗` 这些符号。**
#
# 全项目用了 4 个这样的字符，而它们恰好是「对不对/成没成」的主要标记 ——
# 在没设 `PYTHONIOENCODING=utf-8` 的机器上，**任何工具一打印就
# UnicodeEncodeError 崩掉，exit 1**，而且往往崩在写文件之后
# （BUG-111 / BUG-170）。
#
# 这里在 import core 的第一时间把 stdout/stderr 改成 utf-8 + errors="replace"：
# · 正常情况下和以前完全一样（终端能显示就显示）
# · 编不了的字符变成 '?' 而不是抛异常
# · 用户不需要任何环境变量
#
# `errors="replace"` 是关键 —— 即使某些老终端只认 GBK，
# 顶多显示成问号，**不会让整个工具崩掉**。
def _fix_console_encoding() -> None:
    import sys as _sys
    for name in ("stdout", "stderr"):
        stream = getattr(_sys, name, None)
        reconf = getattr(stream, "reconfigure", None)
        if reconf is None:
            continue
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if enc.startswith("utf"):
                continue                    # 已经是 utf-8，不动
            reconf(encoding="utf-8", errors="replace")
        except Exception:
            # 改不了就退一步：至少别因为编码崩
            try:
                reconf(errors="replace")
            except Exception:
                pass


_fix_console_encoding()
"""绝区零托管系统的底层操作层。

## 模块

    vision.py     Vision：区域 OCR、模板匹配、颜色判定、缓存、并行、多帧投票
    input.py      Input ：鼠标/键盘/虚拟手柄，自动处理输入模式，带节流抖动
    ui.py         Ui    ：语义化动作（click_text / scroll_to / back_until …）
    vocab.py      词表纠错 + 值域校验（属性名/套装名/角色名是封闭集合）
    anchors.py    界面锚点：必须有这些文字才算处于某界面
    journal.py    结构化日志 + 截图留证
    progress.py   断点续跑
    recovery.py   看门狗 + 全局复位 + 资源门控
    flows.py      决策表：界面流程集中管理
    machine.py    状态机：显式状态 + 合法转移 + 路径规划
    template_lib  模板库（tools/template_lib.py 管理）

## 性能事实（1920x1080，实测）

    ┌─────────────────┬──────────┐
    │ 全屏 OCR        │  992 ms  │  ← 禁止
    │ 详情面板 OCR    │  250 ms  │
    │ 小区域 OCR      │   50 ms  │
    │ 模板匹配        │  1~5 ms  │
    │ 颜色采样        │  <1 ms   │
    └─────────────────┴──────────┘

## 两条硬规则

1. **任何 OCR 都必须给区域**；固定按钮用模板或颜色，不要用 OCR。
2. **任何写操作后必须校验**；读操作可以用缓存和单次读取。

## 用法

    from core import Vision, Input, Ui, anchors, Journal, Progress

    vs, inp = Vision(), Input()
    ui, log = Ui(vs, inp), Journal("我的任务")
    ui.start()

    print(anchors.describe(vs))          # 当前在哪个界面
    if anchors.is_(vs, "驱动仓库"):
        txt = vs.text((1400, 180, 1910, 960))
"""
from .vision import Vision, Region
from .input import Input
from .ui import Ui
from .journal import Journal
from .progress import Progress
from . import anchors, vocab, flows, recovery
from .machine import Machine, TRANSITIONS


# ===== 运行时目录 =====
# 工具会往这两个目录写文件。新用户 clone 下来没有它们，
# 不建会导致 FileNotFoundError（实测：filter_terms 首次跑就崩）。
# 放在 __init__ 里是因为每个工具都会 `from core import ...`。
def _ensure_runtime_dirs() -> None:
    try:
        from pathlib import Path as _P
        _root = _P(__file__).resolve().parent.parent.parent
        # **`od_test/shots` 也要建**（RT-09）。
        # 原来只建 `state` 和 `od_test`，而 `run_dismantle` 往
        # `od_test/shots/` 存截图 —— 干净机器上目录不存在，
        # `Image.save` 直接 FileNotFoundError，且发生在 --run 闸门之前。
        for _d in ("state", "od_test", "od_test/shots"):
            (_root / _d).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


_ensure_runtime_dirs()

Screen = Vision   # 兼容旧名字

__all__ = [
    "Vision", "Input", "Ui", "Region", "Screen",
    "Journal", "Progress", "anchors", "vocab", "flows", "recovery",
    "Machine", "TRANSITIONS",
]