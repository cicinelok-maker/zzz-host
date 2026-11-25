"""MCP 服务器：把这套 CLI 工具暴露给任何 MCP 客户端（DSH / Claude / Cursor…）。

## 为什么（用户问「能做成 DSH 插件吗」）

DSH 的 MCP bundle 支持 `transport: stdio` —— 只要有个说 MCP 协议的程序，
就能挂上去，里面的工具会直接变成 agent 可调用的 tool。

本项目全是 Python CLI，包一层 MCP 就通用了：
**任何支持 MCP 的客户端都能用**，不只 DSH。

## 协议（MCP over stdio）

```
← {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
→ {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":...,
                                     "serverInfo":{...},
                                     "capabilities":{"tools":{}}}}
← {"jsonrpc":"2.0","method":"notifications/initialized"}
← {"jsonrpc":"2.0","id":2,"method":"tools/list"}
→ {"jsonrpc":"2.0","id":2,"result":{"tools":[{name,description,inputSchema}]}}
← {"jsonrpc":"2.0","id":3,"method":"tools/call",
   "params":{"name":"zzz_resource_check","arguments":{"agent":"佩洛伊斯"}}}
→ {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"..."}],
                                     "isError":false}}
```

消息用 `Content-Length` 头？**不用** —— MCP stdio 用「一行一个 JSON」。

## 工具设计

**不把 36 个 CLI 全暴露** —— 太多会淹没 agent。只暴露 8 个高层工具：

```
zzz_environment    环境自检（配置/OCR/角色）
zzz_launch         确保游戏开着
zzz_read_status    读角色状态（结构化）
zzz_read_resource  读电量/母盘（结构化）
zzz_plan           换装建议（结构化）
zzz_daily_plan     今日计划（不动游戏）
zzz_daily_run      跑一轮完整养成（有副作用，需 confirm）
zzz_list_agents    列出支持的角色
```

## 安全

**破坏性工具（会花电量/材料）必须传 `confirm: true`**，
否则只返回「将要做什么」不执行。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core.paths import one_dragon_python, one_dragon_env  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "zzz-host"
SERVER_VERSION = "1.0.0"


# ============================================================ 工具定义

def _tool(name, desc, props=None, required=None) -> dict:
    return {
        "name": name,
        "description": desc,
        "inputSchema": {
            "type": "object",
            "properties": props or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool(
        "zzz_environment",
        "检查运行环境：路径配置、OneDragon OCR 模块、角色配置。"
        "任何操作前先调这个，失败就不要继续。",
    ),
    _tool(
        "zzz_launch",
        "确保绝区零在运行。没开就启动客户端、等窗口、自动点「进入游戏」到世界。"
        "约 72 秒。已在运行时直接返回。",
        {"timeout_s": {"type": "integer", "minimum": 30, "maximum": 600,
                       "default": 180,
                       "description": "等窗口出现最多多少秒"}},
    ),
    _tool(
        "zzz_read_status",
        "读角色当前养成状态（结构化 JSON）：6 个位号的套装/等级/主词条/"
        "副词条/有效值 + 主词条判定 + 质量分 + 技能等级。",
        {"agent": {"type": "string",
                   "description": "角色名，如 佩洛伊斯", "default": "佩洛伊斯"}},
        ["agent"],
    ),
    _tool(
        "zzz_read_resource",
        "读当前资源（结构化 JSON）：电量 / 上限 / 母盘数。",
    ),
    _tool(
        "zzz_plan",
        "算 4+2 最优换装方案（结构化 JSON）。主词条不适合角色的盘会被排除。"
        "只出方案，不换装。",
        {"agent": {"type": "string", "default": "佩洛伊斯"}},
        ["agent"],
    ),
    _tool(
        "zzz_daily_plan",
        "今天的养成计划（纯文本）：盘点 / 缺口 / 电量规划 / 动作建议。"
        "不动游戏数据，安全。",
        {"agent": {"type": "string", "default": "佩洛伊斯"}},
        ["agent"],
    ),
    _tool(
        "zzz_daily_run",
        "跑一轮完整养成：刷本 + 提升 + 换装 + 回收，会消耗电量和材料。"
        "**必须传 confirm=true 才真跑**，否则只返回计划。",
        {
            "agent": {"type": "string", "default": "佩洛伊斯"},
            "confirm": {"type": "boolean", "default": False,
                        "description": "true 才真执行，false 只出计划"},
            "skip": {"type": "string", "default": "",
                     "description": "跳过的步骤，逗号分隔：wengine,level,skill,core,disc,farm"},
        },
        ["agent"],
    ),
    _tool(
        "zzz_scan_roster",
        "扫用户账号上有哪些角色（需游戏开着，约 30~60 秒）。"
        "第一次用时先调这个，把结果当菜单给用户选。"
        "和 zzz_list_agents 不同：那个列的是配置库（64 个），这个是账号实际有的。",
    ),
    _tool(
        "zzz_list_agents",
        "列出 disc_meta.json 里配好的角色，以及每个的四件套/主词条要求。",
    ),
]


# ============================================================ 执行

def _run(cmd: list[str], timeout: int = 3600) -> tuple[int, str]:
    """跑一个 CLI，返回 (退出码, 输出)。"""
    env = dict(__import__("os").environ)
    env.update(one_dragon_env())
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run(cmd, cwd=str(BASE), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"超时（{timeout} 秒）"


def _py() -> str:
    p = one_dragon_python()
    return p or sys.executable


def _read_state(name: str) -> dict | list | None:
    p = BASE / "state" / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def call_tool(name: str, args: dict) -> tuple[str, bool]:
    """执行一个工具，返回 (文本结果, 是否出错)。"""
    # 角色名必须能解析，不能静默当默认角色 ——
    # MCP 客户端传空/错名时，按佩洛伊斯跑会得到完全错误的结果。
    raw = (args.get("agent") or "").strip()
    if raw:
        try:
            from core.agent_cfg import resolve_agent
            agent = resolve_agent(raw)
            if agent != raw:
                out_note = f"（角色名「{raw}」→「{agent}」）\n"
            else:
                out_note = ""
        except Exception as e:
            return f"✘ {e}", True
    else:
        from core.game_cfg import DEFAULT_AGENT
        agent = DEFAULT_AGENT
        out_note = ""
    _ = out_note      # 后面各分支用 agent 即可，注释带在结果里由各工具自己打

    if name == "zzz_environment":
        rc, out = _run([_py(), "-u", str(HERE / "check_config.py")], 300)
        return out.strip(), rc != 0

    if name == "zzz_launch":
        t = int(args.get("timeout_s") or 180)
        rc, out = _run([_py(), "-u", str(HERE / "zzz_launch.py"),
                        "--timeout", str(t)], t + 120)
        return out.strip(), rc != 0

    if name == "zzz_read_status":
        rc, out = _run([_py(), "-u", str(HERE / "zzz_status.py"),
                        agent, "--json"], 2400)
        if rc != 0:
            return out.strip(), True
        st = _read_state(f"status_{agent}.json")
        if st:
            return json.dumps(st, ensure_ascii=False, indent=1), False
        return out.strip(), False

    if name == "zzz_read_resource":
        rc, out = _run([_py(), "-u", str(HERE / "zzz_resource.py"),
                        "check", "--json"], 1200)
        # 取最后一行 JSON
        for line in reversed(out.strip().splitlines()):
            line = line.strip()
            if line.startswith('{"ok"'):
                return line, rc != 0
        return out.strip(), rc != 0

    if name == "zzz_plan":
        rc, out = _run([_py(), "-u", str(HERE / "zzz_plan.py"), agent], 2400)
        return out.strip(), rc != 0

    if name == "zzz_daily_plan":
        rc, out = _run([_py(), "-u", str(HERE / "zzz_disc_daily.py"), agent], 2400)
        return out.strip(), rc != 0

    if name == "zzz_daily_run":
        # 读 status 生成计划
        rc0, out0 = _run([_py(), "-u", str(HERE / "zzz_disc_daily.py"), agent], 2400)
        if not args.get("confirm"):
            return ("【未执行】这是计划，要真跑请传 confirm=true\n\n"
                    + out0.strip()), False
        cmd = [_py(), "-u", str(HERE / "zzz_daily.py"), agent, "--run"]
        skip = (args.get("skip") or "").strip()
        if skip:
            cmd += ["--skip", skip]
        rc, out = _run(cmd, 7200)
        return out.strip(), rc != 0

    if name == "zzz_scan_roster":
        rc, out = _run([_py(), "-u", str(HERE / "zzz_who.py"), "--scan"], 1800)
        return out.strip(), rc != 0

    if name == "zzz_list_agents":
        p = HERE / "disc_meta.json"
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return f"读不了 disc_meta.json：{e}", True
        rows = []
        for n, c in (meta.get("角色") or {}).items():
            rows.append({
                "name": n,
                "role": c.get("定位") or c.get("岗位") or "",
                "main_set": c.get("四件套") or "",
                "alt_sets": c.get("两件套候选") or c.get("二件套候选") or [],
                "main_stats": c.get("主词条") or {},
                "good_subs": c.get("有效副词条") or [],
            })
        return json.dumps(rows, ensure_ascii=False, indent=1), False

    return f"没有这个工具：{name}", True


# ============================================================ 协议

def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _err(id_, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": id_,
           "error": {"code": code, "message": message}})


def handle(msg: dict) -> None:
    method = msg.get("method")
    id_ = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {}},
        }})
        return

    if method in ("notifications/initialized", "initialized"):
        return

    if method == "tools/list":
        _send({"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOLS}})
        return

    if method == "tools/call":
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        try:
            text, is_err = call_tool(name, args)
        except Exception as e:
            text, is_err = f"工具异常：{type(e).__name__}: {e}", True
        _send({"jsonrpc": "2.0", "id": id_, "result": {
            "content": [{"type": "text", "text": text}],
            "isError": is_err,
        }})
        return

    if method == "ping":
        _send({"jsonrpc": "2.0", "id": id_, "result": {}})
        return

    if id_ is not None:
        _err(id_, -32601, f"unknown method: {method}")


def main() -> int:
    # 关掉可能的警告，免得污染 stdout
    import warnings
    warnings.filterwarnings("ignore")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
