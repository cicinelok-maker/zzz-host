"""控制台编码修复：**import 一下就生效，不需要任何环境变量。**

## 为什么需要（BUG-111 / BUG-170）

中文 Windows 的默认控制台编码是 **cp936（GBK）**，它编不了这几个字符：

```
✔ ✘ ⚠ ✗ ⏱ ▶ ◀ ℹ ✅ ❌ 🔧
```

而 `✔ ✘ ⚠` 恰好是全项目「对不对 / 成没成」的主要标记。
在没设 `PYTHONIOENCODING=utf-8` 的机器上，
**任何工具一打印就 `UnicodeEncodeError` 崩掉，exit 1** ——
而且常常崩在写完文件之后，留下一半做完的状态。

（开发机上没暴露是因为 shell 里设了 `PYTHONIOENCODING=utf-8`；
审计那边是在**默认控制台**下测的，所以 14/17 个自检脚本全崩。）

## 怎么用

```python
import enc          # noqa: F401  —— 只要 import，副作用就是修好编码
```

`core/__init__.py` 里也调了同一个函数，所以 `from core import ...` 的工具
自动就有；这个模块是给**不 import core** 的脚本用的（自检脚本居多）。

## 为什么用 errors="replace"

改编码解决不了「终端字体根本没有这个字形」的情况。
`errors="replace"` 让编不了的字符变成 `?` ——
**显示难看一点，但不会让整个工具崩掉。**
"""
import sys


def fix() -> str:
    """把 stdout/stderr 改成 utf-8 + errors=replace。返回最终的编码名。"""
    last = ""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconf = getattr(stream, "reconfigure", None)
        if reconf is None:
            continue
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if enc.startswith("utf"):
                last = enc
                continue                      # 已经是 utf-8，不动
            reconf(encoding="utf-8", errors="replace")
            last = "utf-8"
        except Exception:
            # 改不了编码就至少别因为编码崩
            try:
                reconf(errors="replace")
            except Exception:
                pass
    return last


fix()
