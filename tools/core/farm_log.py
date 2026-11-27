"""刷本日志 `state/farm_log.json` 的**唯一读写入口**（RT-08）。

## 为什么需要这个模块

同一份文件，两个工具用**两种 schema** 读写：

```
zzz_daily.py:144   d = json.loads(...)      # 按 dict 读
zzz_daily.py:145   if d.get("date") == 今天
zzz_daily.py:158   写 {"date","count","last",...}          <- dict

zzz_gap.py:415     logs = json.loads(...)                  # 按 list 读
zzz_gap.py:452     logs[-200:]                             <- list
```

于是：

· 先跑 `zzz_gap --run`（写 list），再跑 `zzz_daily --run` ——
  `_farm_count_today()` 对 list 调 `.get` → `AttributeError` 被
  `except: pass` 吞掉 → 返回 0 → **以为今天没刷过，又刷一遍**（多花 60~200 电）。

· 反过来先跑 `zzz_daily`（写 dict），再跑 `zzz_gap --run` ——
  `logs.append` 对 dict → `AttributeError`，
  而且**崩在刷完之后**（电已经花了）。

## 现在的约定

```json
{"_schema": 2,
 "records": [{"ts": "2026-11-27T19:00:00", "date": "2026-11-27",
              "dungeon": "机师与叛甲", "times": 1, "ok": true,
              "source": "zzz_daily"}]}
```

**读侧兼容三种历史形态**：新格式、裸 list、旧的 dict（`{"date","count"}`）。
认不出来就**明确报错**，不再静默当 0 —— 「读不了」和「没刷过」是两件事。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

CAT = Path(__file__).resolve().parent.parent.parent
LOG = CAT / "state" / "farm_log.json"

SCHEMA = 2


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def read() -> list[dict]:
    """读成**统一的记录列表**。认不出就抛异常，不吞。

    ## 为什么不吞

    原来两边都是 `except: pass` / `except: logs = []`。
    而「文件读不了」和「今天还没刷」在调用方看来一样 ——
    于是额度闸门静默失效，同一天重复刷本。
    """
    if not LOG.exists():
        return []
    txt = LOG.read_text(encoding="utf-8", errors="replace")
    if not txt.strip():
        return []
    d = json.loads(txt)          # 坏 JSON 直接抛给上层，让它报出来

    # ① 新格式
    if isinstance(d, dict) and isinstance(d.get("records"), list):
        return [r for r in d["records"] if isinstance(r, dict)]

    # ② 裸 list（zzz_gap 以前写的）
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]

    # ③ 旧 dict（zzz_daily 以前写的）：只有当天计数，补成一条记录
    if isinstance(d, dict) and "date" in d:
        n = int(d.get("count") or 0)
        return [{"ts": d.get("last") or d["date"] + "T00:00:00",
                 "date": d["date"],
                 "dungeon": d.get("last_dungeon") or "",
                 "times": 1,
                 "ok": True,
                 "source": "legacy-dict"}] * max(0, n)

    raise ValueError(f"{LOG.name} 的格式认不出（是 {type(d).__name__}）")


def count_today() -> int:
    """今天刷了几次。**读不了要抛，不要返回 0。**"""
    return sum(1 for r in read() if r.get("date") == _today())


def count_today_safe() -> tuple[int, str]:
    """今天刷了几次 + 读失败的原因（空串 = 没问题）。

    给「不想因此崩掉主流程、但也**不能假装没事**」的调用方用。
    """
    try:
        return count_today(), ""
    except Exception as e:
        return -1, f"{LOG.name} 读不了：{e}"


def append(dungeon: str = "", times: int = 0, ok: bool = True,
           source: str = "") -> None:
    """追加一条。用原子写。"""
    from . import atomic as _aw
    try:
        recs = read()
    except Exception:
        # 读不了就**备份再重来**，别把它覆盖掉（那等于删了历史）
        try:
            bak = LOG.with_name(LOG.name + ".corrupt")
            LOG.replace(bak)
            print(f"  ⚠ {LOG.name} 读不了，已备份成 {bak.name}，重新开始记")
        except Exception:
            pass
        recs = []
    now = time.localtime()
    recs.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", now),
        "date": time.strftime("%Y-%m-%d", now),
        "dungeon": dungeon,
        "times": times,
        "ok": bool(ok),
        "source": source,
    })
    _aw.write_json(LOG, {"_schema": SCHEMA, "records": recs[-200:]})
