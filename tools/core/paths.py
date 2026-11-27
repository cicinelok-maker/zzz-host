"""路径配置：把本机绝对路径变成可配置 + 自动探测。

## 为什么（2026-11-25 可移植性审计）

代码里到处是：
```python
PY = r"E:\\OneDragon\\ZenlessZoneZero-OneDragon-v2.6.1-Full\\.venv\\Scripts\\python.exe"
ENV = {"PYTHONPATH": r"E:\\OneDragon\\...\\src;...\\plugins"}
```
别人的 OneDragon 装在别处、游戏装在别的盘，全跑不了。

## 设计

三层查找（优先级从高到低）：
```
① 环境变量
     ONE_DRAGON_HOME    OneDragon 安装目录
     GAME_EXE           游戏 exe 路径
     ZZZ_PYTHON         OneDragon 的 python.exe
② config.json（项目根目录，已 gitignore）
③ 自动探测（常见安装位置）
```

## 用法

```python
from core.paths import one_dragon_python, one_dragon_env, game_exe

PY = one_dragon_python()      # 找到就用，找不到返回空串
ENV = one_dragon_env()        # PYTHONPATH 等环境变量
EXE = game_exe()              # 游戏客户端
```

**找不到时不抛异常** —— 调用方用 `check()` 给出清晰提示。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
# 注意：config.json 已经被「成本/权重」用了，不能混。
# 路径单独放 paths.json，也支持写在 config.json 的 "paths" 段里。
PATHS_CONFIG = BASE / "paths.json"
CONFIG = BASE / "config.json"

# ---- 常见安装位置（自动探测用）
ONE_DRAGON_GUESSES = [
    "E:\\OneDragon\\ZenlessZoneZero-OneDragon-v2.6.1-Full",
    "D:\\OneDragon\\ZenlessZoneZero-OneDragon-v2.6.1-Full",
    "C:\\OneDragon\\ZenlessZoneZero-OneDragon-v2.6.1-Full",
    "E:\\OneDragon\\ZenlessZoneZero-OneDragon",
    "D:\\OneDragon\\ZenlessZoneZero-OneDragon",
    "C:\\OneDragon\\ZenlessZoneZero-OneDragon",
]

GAME_GUESSES = [
    "A:\\miHoYo Launcher\\games\\ZenlessZoneZero Game\\ZenlessZoneZero.exe",
    "C:\\Program Files\\HoYoPlay\\games\\ZenlessZoneZero Game\\ZenlessZoneZero.exe",
    "D:\\miHoYo Launcher\\games\\ZenlessZoneZero Game\\ZenlessZoneZero.exe",
    "E:\\miHoYo Launcher\\games\\ZenlessZoneZero Game\\ZenlessZoneZero.exe",
    "C:\\miHoYo Launcher\\games\\ZenlessZoneZero Game\\ZenlessZoneZero.exe",
]


_WARNED_BAD_PATHS = False       # 坏 paths.json 只提示一次（_conf 会被调多次）


def _conf() -> dict:
    """读路径配置：paths.json 优先，其次 config.json 的 paths 段。

    ## **必须校验类型**（BUG-041）

    原来 `return json.loads(...)` 直接返回解析结果 ——
    但 JSON 合法不代表内容合法：`paths.json` 里写 `[1,2]` 或 `"E:\\xx"`
    也是合法 JSON，于是返回一个 list/str，
    接着 `one_dragon_home()` 里的 `c.get("one_dragon_home")` 抛

        AttributeError: 'list' object has no attribute 'get'

    **用户看到的是「代码崩了」，而不是「你的 paths.json 写错了」。**

    现在：不是 dict 就当没配置，并明确说一句。
    """
    global _WARNED_BAD_PATHS
    if PATHS_CONFIG.exists():
        try:
            d = json.loads(PATHS_CONFIG.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
            if not _WARNED_BAD_PATHS:
                _WARNED_BAD_PATHS = True
                print(f"⚠ {PATHS_CONFIG.name} 的内容不是对象（是 "
                      f"{type(d).__name__}）—— 已忽略，按默认路径继续")
                print(f'   正确写法：{{"one_dragon_home": "E:\\...", '
                      f'"zzz_python": "E:\\...\\.venv\\Scripts\\python.exe"}}')
        except Exception as e:
            if not _WARNED_BAD_PATHS:
                _WARNED_BAD_PATHS = True
                print(f"⚠ {PATHS_CONFIG.name} 读不了：{e}（按默认路径继续）")
    if CONFIG.exists():
        try:
            d = json.loads(CONFIG.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("paths"), dict):
                return d["paths"]
        except Exception:
            pass
    return {}


def _first_dir(paths: list[str]) -> str:
    for p in paths:
        if p and Path(p).is_dir():
            return p
    return ""


def _first_file(paths: list[str]) -> str:
    for p in paths:
        if p and Path(p).is_file():
            return p
    return ""


def one_dragon_home() -> str:
    """OneDragon 安装目录。"""
    c = _conf()
    env = os.environ.get("ONE_DRAGON_HOME") or c.get("one_dragon_home") or ""
    got = _first_dir([env])
    if got:
        return got
    return _first_dir(ONE_DRAGON_GUESSES)


def one_dragon_python() -> str:
    """OneDragon 自带的 python.exe。"""
    c = _conf()
    env = os.environ.get("ZZZ_PYTHON") or c.get("zzz_python") or ""
    if env and Path(env).is_file():
        return env
    home = one_dragon_home()
    if home:
        cand = Path(home) / ".venv" / "Scripts" / "python.exe"
        if cand.is_file():
            return str(cand)
    return ""


def one_dragon_env() -> dict:
    """跑 OneDragon 工具时的环境变量。"""
    home = one_dragon_home()
    c = _conf()
    if not home:
        return {"PYTHONIOENCODING": "utf-8"}
    env = {
        "PYTHONPATH": home + "\\src;" + home + "\\plugins",
        "PYTHONIOENCODING": "utf-8",
    }
    od_home = c.get("od_home") or ""
    if od_home:
        env["OD_HOME"] = od_home
    return env


def game_exe() -> str:
    """游戏客户端 exe。"""
    c = _conf()
    env = os.environ.get("GAME_EXE") or c.get("game_exe") or ""
    got = _first_file([env])
    if got:
        return got
    return _first_file(GAME_GUESSES)


def summary() -> dict:
    """启动时打印的配置摘要，方便排查。"""
    return {
        "one_dragon_home": one_dragon_home() or "（没找到）",
        "zzz_python": one_dragon_python() or "（没找到）",
        "game_exe": game_exe() or "（没找到）",
        "paths_file": str(PATHS_CONFIG) if PATHS_CONFIG.exists() else
                       "（没有，用自动探测）",
    }


def check() -> list[str]:
    """返回缺什么。空列表 = 配置齐全。"""
    missing = []
    if not one_dragon_home():
        missing.append("OneDragon 安装目录（设 ONE_DRAGON_HOME 或写进 config.json）")
    elif not one_dragon_python():
        missing.append("OneDragon 的 python.exe（.venv\\Scripts\\python.exe 不存在？）")
    if not game_exe():
        missing.append("游戏客户端 exe（设 GAME_EXE 或写进 config.json）")
    return missing


def ensure() -> None:
    """配置不全时打印提示（不抛异常，让调用方自己决定）。"""
    miss = check()
    if miss:
        print("配置不完整：")
        for m in miss:
            print(f"  ✘ {m}")
        print("  参考 config.example.json，或设环境变量")
    return


def require_python() -> str:
    """拿 OneDragon 自带的 python；没有就**给出可操作的指引**并退出。

    ## 为什么需要这个（RT-03）

    `one_dragon_python()` 找不到时返回空串，而 7 个工具直接
    `subprocess.run([PY, ...])` —— 空串当可执行文件会抛

        OSError: [WinError 87] The parameter is incorrect

    **崩在任何配置提示之前**，用户看到的是一段 traceback。
    """
    py = one_dragon_python()
    if py:
        return py
    import sys as _sys
    print("=" * 62, file=_sys.stderr)
    print("✘ 没找到 OneDragon 自带的 python", file=_sys.stderr)
    print("  本项目读游戏画面要用它的 OCR 模块，没有它什么都做不了。", file=_sys.stderr)
    print("", file=_sys.stderr)
    print("  怎么配：", file=_sys.stderr)
    print("    1 下载 OneDragon **完整包**（不是源码包）", file=_sys.stderr)
    print("    2 把路径写进 state/config.json 的 paths 段，或环境变量 ONE_DRAGON_HOME", file=_sys.stderr)
    print("    3 验证：python tools/check_config.py", file=_sys.stderr)
    print("=" * 62, file=_sys.stderr)
    raise SystemExit(2)
