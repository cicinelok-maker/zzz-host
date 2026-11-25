"""本地角色覆盖层。

## 为什么需要

`tools/disc_meta.json` 是发布集里的文件（64 个手写角色）。
用户想加自己的角色，如果直接改那个文件：
  · git pull 会冲突
  · 或者被 checkout 冲掉

**「用户数据」和「程序数据」必须分开放。**

## 数据

`state/characters.local.json`
```json
{"角色": {"角色名": {"定位": "...", "属性": "...", "有效副词条": [...]}}}
```

## 谁在用

· `agent_cfg.cfg_of()`   —— 角色配置（有效副词条/主词条/套装）
· `game_cfg.element_of()` —— 属性
· `zzz_farm_plan`         —— 职业（决定认证章/音擎组件）

## 合并规则

覆盖层的字段**逐个覆盖**发布集的同名字段，不是整条替换。
这样用户只需填「和默认不一样的那几个」。
"""
from __future__ import annotations

import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
LOCAL = BASE / "state" / "characters.local.json"

_TEMPLATE = {
    "_说明": "你自己的角色补充。这里的条目会覆盖 tools/disc_meta.json 的同名角色。"
             "只需要填「和默认不一样」的字段。",
    "_怎么用": "把下面「角色」里加一条，至少填 定位 和 属性。",
    "_示例": {
        "定位": "强攻|异常|击破|支援|防护|命破|锋御",
        "属性": "物理|火|冰|电|以太|风|流明|烈霜|玄墨|凛刃",
        "四件套": "套装名",
        "两件套候选": ["套装A"],
        "有效副词条": ["暴击率", "暴击伤害"],
        "次选副词条": ["攻击力百分比"],
        "主词条": {"4": ["暴击率"], "5": ["属性伤害"], "6": ["攻击力百分比"]},
    },
    "角色": {},
}


def load() -> dict:
    """读覆盖层。不存在返回空结构。"""
    if not LOCAL.exists():
        return {"角色": {}}
    try:
        d = json.loads(LOCAL.read_text(encoding="utf-8"))
    except Exception:
        return {"角色": {}}
    if not isinstance(d.get("角色"), dict):
        d["角色"] = {}
    return d


def get(name: str) -> dict:
    """取某个角色的本地覆盖（没有返回空 dict）。"""
    return dict((load().get("角色") or {}).get(name) or {})


def has(name: str) -> bool:
    return bool(get(name))


def ensure_file() -> pathlib.Path:
    """确保覆盖层文件存在（带模板），返回路径。"""
    if not LOCAL.exists():
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        LOCAL.write_text(json.dumps(_TEMPLATE, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return LOCAL


def add(name: str, cfg: dict) -> str:
    """加/改一个角色。返回提示文本。"""
    d = load()
    chars = d.setdefault("角色", {})
    old = chars.get(name) or {}
    merged = dict(old)
    merged.update(cfg)
    chars[name] = merged
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"已写入 {LOCAL}（{name}：{', '.join(cfg.keys())}）"


def names() -> list[str]:
    return sorted((load().get("角色") or {}).keys())
