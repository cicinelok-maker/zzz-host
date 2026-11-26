"""原子写：先写临时文件再 `os.replace`，避免半截 JSON。

## 为什么需要（BUG-064 / RT-REPORT 柱 3）

全仓 `grep -rn "os.replace" tools/` 原来是**空的** ——
所有 `state/*.json` 都是 `path.write_text(...)` 直接覆盖。

后果不是「写失败」，而是**写到一半断电/被杀就留下半截 JSON**：

```json
{"agent": "佩洛伊斯", "total": 24.0, "slots": [{"slot": 1, "se
```

而读取方（`json.loads` + `except: return {}`）会把它当成「空状态」，
于是数据**凭空消失**，而且没有任何报错。

`BUG-067`（`disc_progress` 坏 JSON 静默当空）和
`BUG-066`（指纹写盘非原子）是同一个病的两个症状。

## 做法

```python
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(text, encoding="utf-8")
os.replace(tmp, path)          # ← 原子：要么是旧的，要么是新的，不会是半个
```

`os.replace` 在同一文件系统内是原子操作（Windows 上是 `MoveFileEx` + REPLACE）。

**顺带的好处**：任何时刻磁盘上的文件都是完整的——
即使进程在写入过程中被杀，读者看到的还是上一份好数据。
"""
from __future__ import annotations

import json
import os
import pathlib

__all__ = ["write_text", "write_json", "read_json"]


def write_text(path, text: str, encoding: str = "utf-8") -> None:
    """原子写文本。先写 `<path>.tmp` 再 `os.replace`。"""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, p)
    finally:
        # 失败时别把 .tmp 留在目录里 (下次读会困惑)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def write_json(path, data, *, indent: int = 2, ensure_ascii: bool = False) -> None:
    """原子写 JSON。"""
    write_text(path, json.dumps(data, ensure_ascii=ensure_ascii, indent=indent))


def read_json(path, default=None):
    """读 JSON；**坏文件不静默当空**，而是抛出并说明是哪份文件。

    原来的写法到处都是：
    ```python
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}          # ← 半截 JSON 被当成「没有数据」
    ```
    这让「文件坏了」和「文件不存在」变成同一件事。

    需要「坏了也能继续」的调用方仍然可以自己接住异常，
    但至少**看得见是哪份文件坏了**。
    """
    p = pathlib.Path(path)
    if not p.exists():
        return default
    txt = p.read_text(encoding="utf-8")
    try:
        return json.loads(txt)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{p.name} 不是合法 JSON（第 {e.lineno} 行第 {e.colno} 列）："
            f"{e.msg}。文件大小 {len(txt)} 字节。"
            f"这份文件可能被写到一半就中断了 —— 删掉它重跑一次即可。"
        ) from e
