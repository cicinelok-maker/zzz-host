"""统一的 --json 输出格式。

## 为什么（用户要求补齐，2026-11-25）

现在只有 6/36 个工具有 `--json`，其他都是给人看的 print。
外部 agent / MCP 客户端拿不到结构化结果。

## 统一格式

每个工具的 `--json` 输出同一个外壳：

```json
{
  "ok": true,
  "tool": "zzz_resource",
  "agent": "佩洛伊斯",
  "duration_s": 45.2,
  "data": { ...工具特定的数据... },
  "artifacts": ["state/status_佩洛伊斯.json"],
  "warnings": []
}
```

失败时：
```json
{"ok": false, "tool": "...", "error": "缺 OneDragon", "exit_code": 2}
```

## 用法

```python
from core.jsonout import emit

# 工具内部收集好数据
result = {"battery": 83, "mother_discs": 7}
emit("zzz_resource", data=result, agent="佩洛伊斯",
     artifacts=["state/resource.json"])
```

## 注意

`emit` 只在 `--json` 时才打印，否则什么都不做 —— 不影响原来的文本输出。
"""
from __future__ import annotations

import json
import sys
import time

_START = time.time()


def emit(tool: str, data: dict | None = None, agent: str = "",
         artifacts: list[str] | None = None,
         warnings: list[str] | None = None,
         enabled: bool = True, **extra) -> None:
    """打印统一格式的 JSON。

    enabled=False 时什么都不做（用于非 --json 模式）。
    """
    if not enabled:
        return
    out = {
        "ok": True,
        "tool": tool,
        "duration_s": round(time.time() - _START, 1),
    }
    if agent:
        out["agent"] = agent
    if data is not None:
        out["data"] = data
    if artifacts:
        out["artifacts"] = artifacts
    if warnings:
        out["warnings"] = warnings
    out.update(extra)
    print(json.dumps(out, ensure_ascii=False))