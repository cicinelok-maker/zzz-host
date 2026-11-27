"""【已归档 2026-11-26】刷本规划（旧）—— 被 zzz_gap.py 取代。

## 为什么归档

这个工具和 `zzz_gap.py` 做同一件事：**算材料缺口 → 调 od_material_farm 刷本**。
区别只在数据来源：

| | zzz_farm_plan（旧） | zzz_gap（新） |
|---|---|---|
| 缺口来源 | 自己算（materials.json + 公式 + inventory.json） | **读游戏官方养成指南** |
| 材料名 | 手维护的表（错过 3 次） | 游戏原文 |
| 库存 | 自己记 | 游戏自带 |
| 定位/属性 | 查 disc_meta（64 个手写） | **从材料名反推** |
| 新增角色 | 要改库 | 不改任何东西 |

## 现状

**还能跑**（`zzz_daily.py` 还在调它），但**新代码不要再用它**。
等 `zzz_daily` 也切到 `zzz_gap` 之后，这个文件可以直接删。

## 保留的原因

`zzz_daily.py`（总控）现在依赖它。删了会连锁破坏。
所以先「归档 = 标清楚，不删」。

## 想用哪个

```powershell
python tools/zzz_gap.py 角色名          # 新的，读官方数据
python tools/zzz_farm_plan.py           # 旧的，别用了
```
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent

# 实测确认的公式（从 OneDragon 源码报错里挖出来的）：
#   实战模拟室 电量 = 怪物卡数量 × 20
#   card_num = int(self.card_num) * 20     ← charge_plan_config.py:69
# 所以 5 张卡 = 100 电。卡越多资源越多，电量也线性增加。
# 结论：在电量够的前提下尽量拉满卡数，减少刷本次数（省时间）。
CARDS_DEFAULT = __import__("core.game_cfg", fromlist=["x"]).CARDS_DEFAULT
CARD_BATTERY = __import__("core.game_cfg", fromlist=["x"]).CHARGE_PER_CARD

# 材料 → 副本（单次电量 / 单次产出）
DUNGEON = {
    "特化芯片": {"cmd": ["--training", "代理人技能", "--cards", str(CARDS_DEFAULT)],
                 "电量": CARD_BATTERY * CARDS_DEFAULT, "产出": 8 * CARDS_DEFAULT,   # 每卡 8 个芯片
                 "名称": f"实战模拟室·代理人技能（{CARDS_DEFAULT}卡）"},
    "认证章":   {"cmd": ["--training", "基础材料", "--cards", str(CARDS_DEFAULT)],
                 "电量": CARD_BATTERY * CARDS_DEFAULT, "产出": 3 * CARDS_DEFAULT,   # 每卡 3 个认证章
                 "名称": f"实战模拟室·基础材料（{CARDS_DEFAULT}卡）"},
    "高维数据": {"cmd": ["--challenge"], "电量": 40, "产出": 5,
                 "名称": "专业挑战室"},
    "刻命残蜕": {"cmd": ["--hunt"], "电量": 0, "产出": 2,
                 "名称": "恶名狩猎（每周3次免费）"},
    "蓄电池":   {"cmd": ["--patrol", "机师与叛甲"], "电量": 60, "产出": 12,
                 "名称": "区域巡防"},
    "驱动盘":   {"cmd": ["--patrol", "机师与叛甲"], "电量": 60, "产出": 2,
                 "名称": "区域巡防·刷盘"},
}

# 套装 → 区域巡防副本
# 权威来源：disc_meta.json 的「套装副本」（2026-11-25 从 moegirl wiki + Game8 核对）。
# 之前这里硬编码过一份，有 4 处错（云岿如我/原始朋克/极地重金属/自由蓝调/雷暴重金属），
# 而且缺 2.x 的新套装。现在统一从 disc_meta 读，不再各写一份。
def _load_patrol_by_set() -> dict:
    try:
        _d = json.loads((HERE / "disc_meta.json").read_text(encoding="utf-8"))
        m = dict(_d.get("套装副本") or {})
        # 别名归一（自由爵士 = 自由蓝调）
        for alias, official in (_d.get("套装别名") or {}).items():
            if official in m:
                m[alias] = m[official]
        if m:
            return m
    except Exception:
        pass
    return {}


PATROL_BY_SET = _load_patrol_by_set()
DEFAULT_PATROL = "机师与叛甲"

# 技能目标（按岗位）
SKILL_TARGETS = {
    "强攻": {"普通攻击": 12, "特殊技": 12, "连携技": 12, "闪避": 8, "支援技": 8},
    "异常": {"特殊技": 12, "连携技": 12, "普通攻击": 10, "闪避": 8, "支援技": 8},
    "击破": {"特殊技": 12, "连携技": 12, "闪避": 8, "普通攻击": 8, "支援技": 6},
    "支援": {"特殊技": 12, "连携技": 10, "支援技": 8, "普通攻击": 6, "闪避": 6},
    "防护": {"特殊技": 12, "连携技": 10, "闪避": 8, "普通攻击": 6, "支援技": 6},
    "命破": {"特殊技": 12, "连携技": 12, "普通攻击": 10, "闪避": 8, "支援技": 8},
    # 2026-11-26 补：disc_meta 职业模板里有 锋御，这里原来漏了。
    # 锋御是 2.x 新特性（防御转伤，双暴+防御），输出型，技能目标和强攻/命破同类。
    "锋御": {"普通攻击": 12, "特殊技": 12, "连携技": 12, "闪避": 8, "支援技": 8},
}
# 技能芯片：每个技能等级差需要多少（粗略，含各阶合计）
CHIP_PER_LEVEL = 12
# 等级认证章：每档晋升
ASCEND_CERT = {20: 4, 30: 20, 40: 20, 50: 30}
# 核心技面板 costs 的三项对应什么材料（2026-11-26 从实际数值对出来的）
#   E: costs=[[1,3],[7,15],[3272482,100000]]
#      刻命残蜕 1/3 · 高维数据 7/15 · 丁尼 3.2M/10万
#   和 CORE_RELIC{E:3} / CORE_DATA{E:15} 完全对得上，所以是权威值。
# 丁尼不进刷本清单（不值当单独刷），所以第三项留空。
COST_KINDS = ["刻命残蜕", "高维数据", ""]
# 核心技高维数据
CORE_DATA = {"D": 9, "E": 15, "F": 30}
CORE_RELIC = {"D": 2, "E": 3, "F": 4}


def load(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _core_of(agent: str):
    """读某个角色的核心技状态。None = 这个角色从没体检过（不能当「全部解锁」）。"""
    per = BASE / "state" / f"core_status_{agent}.json"
    if per.exists():
        return load(per) or None
    # 向后兼容：老版本只有一个全局文件，且没有角色字段。
    # 只在「目录里没有任何按角色的文件」时才敢拿它当全局唯一真相。
    glob = BASE / "state" / "core_status.json"
    if glob.exists() and not list((BASE / "state").glob("core_status_*.json")):
        return load(glob) or None
    return None


def collect() -> dict[str, dict]:
    """汇总所有角色的缺口，按材料类型合并。"""
    meta = load(HERE / "disc_meta.json").get("角色") or {}
    elems = load(BASE / "state" / "agent_elements.json")
    need: dict[str, dict] = {}

    def add(mat: str, amount: int, who: str):
        if amount <= 0:
            return
        d = need.setdefault(mat, {"数量": 0, "角色": []})
        d["数量"] += amount
        d["角色"].append(who)

    _unk = set()

    for name, info in elems.items():
        lv_digits = re.sub(r"\D", "", str((info or {}).get("等级", "")))
        lv = int(lv_digits) if lv_digits else 1
        attr = (info or {}).get("属性", "") or "?"
        st = load(BASE / "state" / f"status_{name}.json")
        # 没体检过的角色不参与统计——否则「slots 是空」会被当成 6 个位号全空，
        # 驱动盘缺口会虚高（实测虚高到 296 个）
        if not st:
            continue
        cfg = meta.get(name) or {}

        # 1) 等级认证章 —— **按职业分**
        # 实际是「代理人晋升」副本，7 个职业各一个演练：
        #   锋御演练 / 命破演练 / 强攻演练 / 击破演练 / 异常演练 / 支援演练 / 防护演练
        # 以前所有角色合并成一笔「认证章」去刷「基础材料」，那是错的。
        cert = sum(v for k, v in ASCEND_CERT.items() if k > lv)
        if cert:
            _role = (cfg.get("定位") or "").split("/")[0] or "强攻"
            add(f"认证章_{_role}", cert, f"{name}({_role} 升{lv}→60)")

        # 2) 技能芯片（按岗位目标）
        # **未知角色要警告，不能静默按强攻算。**
        # 认证章/音擎组件都按职业，猜错了整份清单都错。
        try:
            from core.agent_cfg import is_known as _ik
            if not _ik(name):
                _unk.add(name)
        except Exception:
            pass
        role = cfg.get("岗位", "强攻").split("/")[0]
        tgt = SKILL_TARGETS.get(role, SKILL_TARGETS["强攻"])
        skills = st.get("skills") or {}
        gap = 0
        for sname, val in (skills.items() if isinstance(skills, dict) else []):
            digits = re.sub(r"\D", "", str(val))
            cur = int(digits[:2]) if len(digits) >= 2 else 0
            gap += max(0, tgt.get(sname, 8) - cur)
        if gap:
            add(f"特化{attr}芯片", gap * CHIP_PER_LEVEL, f"{name}(技能差{gap}级)")

        # 3) 核心技
        # **必须读这个角色自己的状态。** 全局 core_status.json 只记了最后体检的那个角色，
        # 拿它判断所有人会让核心技缺口整体消失（2026-11-26 实跑确认过）。
        core = _core_of(name)
        if core is None:
            # 这个角色从没体检过核心技 —— 不知道缺多少，**标出来而不是当 0**
            add("高维数据", sum(CORE_DATA.values()), f"{name}(核心技·未体检，按满额估)")
            add("刻命残蜕", sum(CORE_RELIC.values()), f"{name}(核心技·未体检，按满额估)")
        else:
            # **用 costs 判断，不用 unlocked。**
            # unlocked 只说明「解锁了」，解锁之后还要一层层升；
            # 满级的那几个圈 costs 是空的，没满的 costs 里 have<need。
            # 旧代码用 `len(unlocked) < 6`，A~F 全解锁时永远算不出缺口（实跑确认过）。
            for ckey, cv in core.items():
                if not isinstance(cv, dict):
                    continue
                for ci, pair in enumerate(cv.get("costs") or []):
                    try:
                        _have, _need = int(pair[0]), int(pair[1])
                    except (TypeError, IndexError, ValueError):
                        continue
                    if _have >= _need:
                        continue
                    kind = COST_KINDS[ci] if ci < len(COST_KINDS) else ""
                    if not kind:
                        continue
                    # 注意：这里不能用 need 当变量名 —— 它是外层那个 dict，
                    # 覆盖掉就会 AttributeError: 'int' object has no attribute 'setdefault'
                    add(kind, _need - _have,
                        f"{name}(核心技{ckey} {_have}/{_need})")

        # 4) 音擎：没有实测数据就不瞎加（之前每人硬加 380 是错的，
        #    13 个角色加起来 4940，而实际大多数音擎已经满级）
        eng = load(BASE / "state" / f"wengine_{name}.json")
        if eng and eng.get("batt_need"):
            add("蓄电池", int(eng["batt_need"]), f"{name}(音擎)")

        # 5) 驱动盘：**按套装分副本**
        # 以前不区分套装，全用 DUNGEON["驱动盘"] 那个写死的「机师与叛甲」，
        # 48 次 × 60 电全算在同一个副本上 —— 而实际要刷好几个不同的巡防。
        slots = st.get("slots") or []
        have = {s.get("slot") for s in slots if s.get("set")}
        empty = [s for s in range(1, 7) if s not in have]
        if empty:
            # 这个角色要哪些套装：四件套 + 两件套候选
            _sets = []
            if cfg.get("四件套"):
                _sets.append(cfg["四件套"])
            _sets.extend(cfg.get("两件套候选") or [])
            # 一个空位平均刷 4 次才出能用的
            _per = 4
            if not _sets:
                add("驱动盘_未配置", len(empty) * _per,
                    f"{name}(空{empty}，但 disc_meta 里没配置套装)")
            else:
                # **盘数按「实际要几件」算，不是「空位 × 候选套」**（D13）。
                #
                # 原来 `for _sn in _sets: add(..., len(empty) * _per)` ——
                # 6 个空位、4 个候选套 -> 6×4×4 = **96 盘**
                # （48 趟）。而实际只需要 **6 个盘**：四件套 4 个 + 两件套 2 个，
                # 24 盘 / 12 趟。**虚高 4 倍**，实测两角色 5760 电 vs 手算 1440。
                #
                # 一个盘掉出来只用一次 —— 同一位号不需要「每个候选套各来一个」。
                # 两件套**只会用一个**，所以只按一个候选算（取第一个），
                # 并把「按哪个候选算的」写进理由，免得用户以为另一个也含在内。
                _main = cfg.get("四件套") or ""
                _secs = [x for x in (cfg.get("两件套候选") or []) if x]
                _n_main = min(len(empty), 4) if _main else 0
                _n_sec = min(len(empty) - _n_main, 2) if _secs else 0
                _rest = len(empty) - _n_main - _n_sec

                if _n_main:
                    _dg = PATROL_BY_SET.get(_main)
                    if not _dg:
                        add("驱动盘_无副本", _n_main * _per,
                            f"{name}(套装 {_main} 查不到副本)")
                    else:
                        add(f"驱动盘_{_dg}", _n_main * _per,
                            f"{name}(四件套 {_main} 要 {_n_main} 件)")
                if _n_sec:
                    _sec = _secs[0]
                    _dg = PATROL_BY_SET.get(_sec)
                    if not _dg:
                        add("驱动盘_无副本", _n_sec * _per,
                            f"{name}(套装 {_sec} 查不到副本)")
                    else:
                        add(f"驱动盘_{_dg}", _n_sec * _per,
                            f"{name}(两件套 {_sec} 要 {_n_sec} 件"
                            + (f"；只按这一个候选算，另有 {len(_secs) - 1} 个没算"
                               if len(_secs) > 1 else "") + ")")
                if _rest > 0:
                    add("驱动盘_未配置", _rest * _per,
                        f"{name}(空{_rest} 个位号没有套装归属)")

    if _unk:
        print()
        print("=" * 66)
        print(f"⚠ 有 {len(_unk)} 个角色不在角色库里：{sorted(_unk)}")
        print("=" * 66)
        print("  这些角色按【强攻】模板算，可能不准：")
        print("    · 认证章   → 会算成「强攻演练/先行者」")
        print("    · 音擎组件 → 会算成「强攻组件」")
        print("    · 技能芯片 → 按读到的属性算（这个准）")
        print()
        print("  补数据（不改发布集，pull 不冲突）：")
        print("    python tools/zzz_who.py --add-agent <角色> --role <定位> --element <属性>")
        print("    或直接编辑 state/characters.local.json")
        print("=" * 66)
        print()
    return need



def _materials() -> dict:
    """读 materials.json（材料总表）。读不到返回空。"""
    try:
        import json as _j
        return _j.loads((HERE / "materials.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cost_from_table(mat: str, role: str = "", attr: str = ""):
    """从 materials.json 查材料 → 副本 + 电量/产出（每次刷本口径）。

    只用于**旧 DUNGEON 表没有的新材料**（音擎组件、角色经验、镀剂）。
    已有材料的数字沿用 DUNGEON（那里是实测调过的），不覆盖。
    """
    M = _materials()
    if not M:
        return None

    if mat.endswith("组件"):                    # 音擎组件
        node = M.get("音擎") or {}
        return {"副本": (node.get("副本") or "实战模拟室·音擎改装（{职业}试验）").format(
                   职业=role or "强攻"),
                "电量": node.get("电量", 100), "产出": node.get("产出", 15)}
    if mat == "角色经验":
        node = M.get("角色经验") or {}
        return {"副本": node.get("副本", "实战模拟室·基础材料（代理人经验）"),
                "电量": node.get("电量", 100), "产出": node.get("产出", 15)}
    if mat == "镀剂":
        node = (M.get("驱动盘") or {}).get("镀剂") or {}
        return {"副本": node.get("副本", "实战模拟室·基础材料（镀剂专项）"),
                "电量": node.get("电量", 100), "产出": node.get("产出", 15)}
    return None


def plan_rows(need: dict, meta: dict) -> list[dict]:
    rows = []
    for mat, d in need.items():
        # ---- 新拆出来的材料名 → 副本 ----
        # 认证章_强攻 → 实战模拟室·代理人晋升（强攻演练）
        if mat.startswith("认证章_"):
            _role = mat.split("_", 1)[1]
            rows.append({
                "材料": mat, "数量": d["数量"],
                "副本": f"实战模拟室·代理人晋升（{_role}演练）",
                "次数": -(-d["数量"] // max(1, 3 * CARDS_DEFAULT)),
                "电量": (-(-d["数量"] // max(1, 3 * CARDS_DEFAULT))) * CARD_BATTERY * CARDS_DEFAULT,
                "角色": d["角色"],
                "cmd": ["--training", "代理人晋升", "--cards", str(CARDS_DEFAULT)],
            })
            continue
        # 驱动盘_机师与叛甲 → 区域巡防·机师与叛甲
        if mat.startswith("驱动盘_"):
            _dg = mat.split("_", 1)[1]
            _runs = -(-d["数量"] // 2)          # 每趟约出 2 个能用的盘
            rows.append({
                "材料": mat, "数量": d["数量"],
                "副本": f"区域巡防·{_dg}",
                "次数": _runs, "电量": _runs * 60,
                "角色": d["角色"],
                "cmd": ["--patrol", _dg],
            })
            continue

        # 新材料（旧 DUNGEON 表没有的）走 materials.json；
        # 已有材料沿用 DUNGEON —— 那里的数字是实测调过的，不拿表覆盖它。
        _role = ""
        for _who in (d.get("角色") or [])[:1]:
            _ag = _who.split("(")[0]
            _role = ((meta.get(_ag) or {}).get("定位") or "").split("/")[0]
        _new = _cost_from_table(mat, _role)
        if _new:
            _runs = -(-d["数量"] // max(1, int(_new["产出"])))
            rows.append({"材料": mat, "数量": d["数量"], "副本": _new["副本"],
                         "次数": _runs, "电量": _runs * int(_new["电量"]),
                         "角色": d["角色"], "cmd": []})
            continue

        key = "特化芯片" if mat.startswith("特化") else mat
        cfg = DUNGEON.get(key)
        if not cfg:
            rows.append({"材料": mat, "数量": d["数量"], "副本": "？",
                         "次数": 0, "电量": 0, "角色": d["角色"]})
            continue

        cmd = list(cfg["cmd"])
        name = cfg["名称"]

        # 驱动盘/蓄电池这类要按套装选具体副本，不能写死
        if key in ("蓄电池", "驱动盘"):
            # 有序去重 —— 用 set 的话 picks[0] 取决于哈希顺序，
            # 同样的输入可能给出不同副本（结果不可复现）。
            # dict.fromkeys 保插入序（Python 3.7+ 保证）。
            set_order = {}
            for who in d["角色"]:
                agent = who.split("(")[0]
                s = (meta.get(agent) or {}).get("四件套")
                if s:
                    set_order[s] = True
            sets = list(set_order)
            picks = [PATROL_BY_SET.get(s, DEFAULT_PATROL) for s in sets] or [DEFAULT_PATROL]
            # 用第一个需要的套装（多个套装时要分开刷）
            dungeon = picks[0]
            cmd = ["--patrol", dungeon]
            name = f"区域巡防·{dungeon}"
            if len(set(picks)) > 1:
                name += f"（还有 {len(set(picks)) - 1} 个套装要另外刷）"

        runs = -(-d["数量"] // cfg["产出"])
        # **周本要标跨周**：每周只有 3 次免费，13 次刷不完就得等下几周。
        # 不标的话「0 电 13 次」看起来像一次就能搞定。
        if key == "刻命残蜕":
            from core.weekly import FREE_RUNS as _FR
            _free = _FR.get("恶名狩猎", 3)
            _weeks = -(-runs // max(1, _free))
            _note = f"每周 {_free} 次免费，要 {_weeks} 周" if _weeks > 1 else f"每周 {_free} 次免费"
            name = f"{name}　（{_note}）"
        rows.append({"材料": mat, "数量": d["数量"], "副本": name,
                     "次数": runs, "电量": runs * cfg["电量"],
                     "角色": d["角色"], "cmd": cmd})
    # ---- 排序：**过期优先，不是便宜优先** ----
    # 以前的 key 只有电量，把「周本免费次数（会过期）」和
    # 「专业挑战室（永远在）」当成同一类东西。
    #
    # 优先级：
    #   0 周本（免费次数过期作废）
    #   1 免费材料转化（0 电且不占次数）
    #   2 卡住其他系统的
    #   3 剩下的按电量升序
    def _rank(r: dict) -> tuple:
        _mat = r.get("材料", "")
        _bat = r.get("电量", 0)
        if _mat == "刻命残蜕":
            return (0, 0)                    # 周本，最先
        if _bat == 0:
            return (1, 0)                    # 免费
        return (2, _bat)                     # 其余按电量

    rows.sort(key=_rank)
    return rows


def both_dungeons(agent: str) -> list[str]:
    """返回该角色该刷的两个区域巡防副本：主套的 + 副套的。

    用户 2026-11-24：「你可以两个副本一起刷，哪个盘子好用哪个」
    """
    import json
    meta = json.loads((HERE / "disc_meta.json").read_text(encoding="utf-8"))
    cfg = (meta.get("角色") or {}).get(agent) or {}
    main_set = cfg.get("四件套", "")
    alts = cfg.get("两件套候选") or cfg.get("二件套候选") or []
    out = []
    for sname in [main_set] + alts[:1]:
        d = PATROL_BY_SET.get(sname)
        if d and d not in out:
            out.append(d)
    return out


def main() -> int:
    print("=" * 66)
    print("⚠ zzz_farm_plan.py 已归档，被 zzz_gap.py 取代")
    print("=" * 66)
    print("  新的是：python tools/zzz_gap.py <角色名>")
    print("  它读游戏官方养成指南的缺口，不依赖手写的材料表。")
    print("=" * 66)
    print()
    ap = argparse.ArgumentParser()
    ap.add_argument("--battery", type=int, default=240, help="电量预算")
    ap.add_argument("--convert", action="store_true",
                    help="刷完之后真的跑材料转化（会消耗低阶材料）。"
                         "不加只打印命令，不动手")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()

    need = collect()
    if not need:
        print("没有缺口数据，先跑体检")
        return 2
    meta = load(HERE / "disc_meta.json").get("角色") or {}

    # ---- 第 0 步：先跑材料转化（免费的）----
    # 低阶材料转高阶不花电量，刷之前先榨干这部分
    print("=" * 56)
    print("第 0 步：材料转化（免费，先做）")
    print("=" * 56)
    # **转化是个会消耗材料的动作（BUG-008）。**
    #
    # 原来是 `--run` 就无条件跑 `zzz_convert.py --all --confirm`：
    # · `--all` 展开成 5 个技能材料各转化一遍
    # · `--confirm`（「真的点确认，会消耗材料」）写死在命令行里
    #
    # 也就是说：只要加了 `--run`，不管刷什么本，都会顺手把 5 种技能材料
    # 从低阶转化成高阶。没有预览、没有数量控制、没法拒绝。
    #
    # 现在：默认**只打印**该跑什么，要动手必须显式加 `--convert`。
    _conv_cmd = f"{HERE / 'zzz_convert.py'} --all --confirm"
    if not args.run:
        print("  [计划] 刷完可跑：" + str(HERE / "zzz_convert.py") + " --all --confirm")
    elif not args.convert:
        print("  [跳过] 材料转化（会消耗低阶材料，默认不做）")
        print("         要转化就加 --convert：")
        print(f"           python tools/zzz_convert.py --all --confirm")
    else:
        import os
        import subprocess
        from core.paths import one_dragon_python, one_dragon_env
        PY = one_dragon_python()
        env = dict(os.environ)
        env.update(one_dragon_env())
        print("  ⚠ 正在转化**全部 5 种**技能材料（--all --confirm）")
        print("     这一步会消耗低阶材料，且不可逆。")
        try:
            r = subprocess.run([PY, "-u", str(HERE / "zzz_convert.py"),
                                "--all", "--confirm"],
                               cwd=str(BASE), env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=1800)
            out = (r.stdout or "") + (r.stderr or "")
            done = out.count("已确认转化")
            print(f"  转化 {'成功' if r.returncode == 0 else '失败'}，"
                  f"转化了 {done} 项")
            for line in out.splitlines():
                if "转化" in line and "→" in line:
                    print(f"    {line.strip()}")
        except Exception as e:
            print(f"  转化异常：{e}")

    rows = plan_rows(need, meta)

    print(f"{'材料':<14} {'需要':>5} {'副本':<18} {'次数':>4} {'电量':>5}")
    print("-" * 56)
    total_batt = 0
    for r in rows:
        print(f"{r['材料']:<14} {r['数量']:>5} {r['副本']:<18} "
              f"{r['次数']:>4} {r['电量']:>5}")
        total_batt += r["电量"]
    print("-" * 56)
    print(f"{'合计':<14} {'':>5} {'':>18} {'':>4} {total_batt:>5}")
    print(f"\n按 {args.battery} 电/轮算，需要 {total_batt / max(1, args.battery):.0f} 轮满电")
    print(f"约 {total_batt / max(1, args.battery) * 24:.0f} 小时（6分钟回1电）")

    # 电量预算内能刷多少刷多少（允许只刷一部分，不必凑满一整项）
    print(f"\n电量预算 {args.battery} 内，按性价比（便宜优先）分配：")
    used = 0
    picked = []
    for r in rows:
        if r["电量"] == 0:
            picked.append({**r, "本次次数": r["次数"]})
            print(f"  ✔ {r['材料']}（免费，{r['次数']} 次）")
            continue
        if r.get("cmd") is None:
            continue
        per_run = r["电量"] // max(1, r["次数"])
        if per_run <= 0:
            continue
        left = args.battery - used
        if left < per_run:
            continue
        # 这次最多刷几次
        can = min(r["次数"], left // per_run)
        if can <= 0:
            continue
        used += can * per_run
        picked.append({**r, "本次次数": can})
        print(f"  ✔ {r['材料']} 刷 {can}/{r['次数']} 次（{can * per_run} 电）")
    if not picked:
        print("  （预算不够刷任何一项，先等电量或降低目标）")
    print(f"  用掉 {used}/{args.battery} 电")

    if args.run:
        print("\n按清单批量刷…")
        import os
        import subprocess
        from core.paths import one_dragon_python, one_dragon_env
        PY = one_dragon_python()
        env = dict(os.environ)
        env.update(one_dragon_env())
        # **没有 OneDragon 的 python 就别硬跑**（RT-03 同一类）。
        if not PY:
            print("  ✘ 没找到 OneDragon 的 python —— 先跑 `python tools/check_config.py`")
            return 2

        _bad = 0
        for r in picked:
            if not r.get("cmd"):
                continue
            # **用预算算出来的「本次次数」，不是 `min(次数, 3)`**（RT-06）。
            #
            # 原来这里写死 `min(r["次数"], 3)` —— 上面刚算好的 `本次次数`
            # **被丢掉了**。于是 `--battery 100` 打印「刷 1/6 次（100 电）」，
            # 实际发的是 `--times 3`（300 电）—— **最多按预算的 3 倍花掉**，
            # 而计划页和执行完全对不上。
            _n = int(r.get("本次次数") or 0)
            if _n <= 0:
                print(f"  跳过 {r['材料']}：本次 0 次")
                continue
            cmd = [PY, "-u", str(HERE / "od_material_farm.py")] + r["cmd"] + \
                  ["--times", str(_n), "--run"]
            print(f"  刷 {r['材料']} {_n} 次：{' '.join(r['cmd'])}")
            try:
                _r = subprocess.run(cmd, cwd=str(BASE), env=env, timeout=3600)
                if _r.returncode != 0:
                    _bad += 1
                    print(f"    ⚠ 退出码 {_r.returncode}")
            except Exception as e:
                _bad += 1
                print(f"    失败：{e}")
        if _bad:
            print(f"\n  {_bad} 项刷本失败")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())