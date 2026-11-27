"""工具清理：确定 canonical 清单，其余挪进 tools/_legacy/。

判定「canonical」的三条标准（全部满足才算）：
1. 被总控调用（zzz_auto / zzz_daily / zzz_grind / zzz_next / selfcheck）
2. 或被人手动用（有明确的 CLI 用途）
3. 或被 canonical 工具 import

用法：
    python tools/cleanup_tools.py            # 只看清单
    python tools/cleanup_tools.py --apply    # 真移动
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

BASE = Path(__file__).resolve().parent.parent
TOOLS = BASE / "tools"
CORE = TOOLS / "core"
LEGACY = TOOLS / "_legacy"

# ---- canonical 清单（手工确认过，每个都有明确职责）----
CANON = {
    # 核心库
    "core/disc_cfg.py": "驱动盘区域/阈值/坐标",
    "core/game_cfg.py": "跨系统常量（电量/刷本成本）",
    "core/disc_stats.py": "词条数值表 + roll 反推",
    "core/vocab.py": "属性词表",
    "core/slots.py": "盘位几何",
    "core/vision.py": "截图 + OCR",
    "core/input.py": "键鼠输入",
    "core/ui.py": "UI 封装",
    "core/anchors.py": "页面指纹识别",
    "core/machine.py": "状态机导航",
    "core/fingerprint.py": "指纹采集",
    "core/journal.py": "任务日志",
    "core/progress.py": "进度记录",
    "core/recovery.py": "异常恢复",
    "core/flows.py": "通用流程",
    "core/locate.py": "元素定位",

    # 驱动盘
    "zzz_disc_v2.py": "批量读盘",
    "zzz_disc_train.py": "单盘读+判",
    "zzz_disc_cycle.py": "升级→判定→标记→拆解 闭环",
    "zzz_equip.py": "装备/升级",
    "zzz_plan.py": "4+2 决策",
    "zzz_status.py": "全状态",
    "zzz_tune.py": "定向调律",
    "run_dismantle.py": "批量拆解",
    "disc_gaps.py": "调律推导 + 升级止损",
    "filter_terms.py": "筛选词条映射",
    "disc_meta.json": "角色盘配置",

    # 其他四系统
    "zzz_resource.py": "电量/资源",
    "zzz_convert.py": "材料转化",
    "zzz_level.py": "角色等级/晋升",
    "zzz_skill.py": "技能升级",
    "zzz_skill_target.py": "技能目标表",
    "zzz_core.py": "核心技",
    "zzz_wengine.py": "音擎",

    # 刷本
    "od_material_farm.py": "刷本入口",
    "zzz_farm_plan.py": "刷本计划",

    # 总控
    "zzz_grind.py": "多轮收敛",
    "zzz_daily.py": "日常",

    # 工具/辅助
    "live.py": "真机操作（识屏/点击/确认）",
    "feishu.py": "飞书通知（文本）",
    "feishu_img.py": "飞书通知（图片）",
    "pick_agent.py": "选角色",
    "selfcheck.py": "兼容性自检",
    "audit_all.py": "全量体检",
    "audit_eff.py": "口径体检",
    "audit_coords.py": "坐标体检",
    "explain_crit.py": "命中率说明",
    "show_discs_v2.py": "读盘结果展示",
    "gap_analysis.py": "缺口分析",
    "zzz_cost.py": "养成成本表",
    "cleanup_tools.py": "本文件：工具清理",
}
# ============================================================ 生效清单
def _canon_effective() -> dict:
    """**`CANON` 的手工清单 + `tools.json` 里所有在用的工具**（E27）。

    ## 原来

    `CANON` 是**手工维护**的。工具越加越多，清单没跟上 ——
    预演说「移走 36 个」，而那些**全是在用的工具**。

    更糟的是它看起来很正常：每一行都有名字、都像那么回事。
    真加 `--run` 就是 36 个工具被搬进 `_legacy/`。

    ## 现在

    以 **`tools.json`**（`gen_manifest.py` 从实际文件生成的）为准 ——
    **只要 `tools.json` 里列了的，就一律保留**。`CANON` 只作为补充说明。

    这样清单永远不会过期，因为它不是手写的。
    """
    out = dict(CANON)
    tj = TOOLS.parent / "tools.json"
    if not tj.exists():
        return out
    try:
        import json as _json
        d = _json.loads(tj.read_text(encoding="utf-8"))
    except Exception:
        return out
    # **`tools` 是一个「字典列表」**，每项形如
    # `{"name": "check_config", "cmd": "python tools/check_config.py", ...}`。
    # 不是「名字 -> 配置」的映射 —— 我第一版按映射写，迭代出来的是整个 dict。
    items = d.get("tools") if isinstance(d, dict) else None
    if not isinstance(items, (list, dict)):
        return out
    names = []
    if isinstance(items, dict):
        names = list(items.keys())
    else:
        for it in items:
            if isinstance(it, dict):
                nm = it.get("name") or ""
                cmd = it.get("cmd") or ""
                # 优先用 cmd 里的文件名（最准），否则用 name
                if cmd:
                    tail = cmd.rsplit("/", 1)[-1].strip()
                    if tail.endswith(".py"):
                        nm = tail[:-3]
                if nm:
                    names.append(str(nm))
    for name in names:
        key = name if name.endswith(".py") else name + ".py"
        out.setdefault(key, "（来自 tools.json — 在用）")
    return out



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    existing = set()
    for f in TOOLS.glob("*.py"):
        existing.add(f.name)
    for f in CORE.glob("*.py"):
        existing.add(f"core/{f.name}")
    for f in TOOLS.glob("*.json"):
        existing.add(f.name)

    keep, move, guarded = [], [], []
    for name in sorted(existing):
        if name in _canon_effective():
            keep.append(name)
            continue
        # **硬保护**（BUG-109）：这些永远不移动，哪怕不在 CANON 里。
        #
        # 原来的分拣是 `keep if name in CANON else move` ——
        # **不在 CANON 里的一律移走**，包括 `core/` 里的活模块。
        # 依赖检查只查「保留的文件是否 import 了要移走的」，
        # 如果一整组活模块都被移走，它一个都查不出来 ——
        # 搬完整个项目直接跑不起来（审计实测会搬走 43 个，含 14 个活 core 模块）。
        if name.startswith("core/"):
            guarded.append((name, "core/ 里的模块是地基，不动"))
            keep.append(name)
            continue
        if name.endswith(".json"):
            guarded.append((name, "数据文件，不是工具，不动"))
            keep.append(name)
            continue
        move.append(name)

    print(f"总计 {len(existing)} 个文件")
    print(f"  保留 {len(keep)} 个")
    print(f"  移走 {len(move)} 个")

    # **数量反常就拒绝执行**（E27）。
    #
    # `CANON` 是手工清单，会过期。修之前它想移走 **36 个在用工具**，
    # 而输出看起来很正常：每一行都有名字、都像那么回事。
    #
    # 现在生效清单合并了 `tools.json`（从实际文件生成），降到 18。
    # 但「18」仍然不少 —— 所以再加一道：**一次要移超过 20 个就停下**，
    # 让人先看看清单对不对。
    _LIMIT = 20
    if args.apply and len(move) > _LIMIT:
        print()
        print(f"  ✘ 一次要移走 {len(move)} 个 —— 超过 {_LIMIT}，拒绝执行")
        print(f"     这多半说明 CANON 清单过期了，或者 tools.json 没重新生成。")
        print(f"     先跑：python tools/gen_manifest.py")
        print(f"     再确认下面这些真的不该在 tools/ 里：")
        for _m in move[:20]:
            print(f"       {_m}")
        return 1
    if guarded:
        print(f"  硬保护 {len(guarded)} 个（不在 CANON 里但绝不能动）")
        for n, why in guarded[:20]:
            print(f"    · {n:<28} {why}")
        if len(guarded) > 20:
            print(f"    …还有 {len(guarded) - 20} 个")
    print()

    print("=== 保留 ===")
    for n in keep:
        print(f"  {n:<30} {CANON.get(n, '')}")

    # 检查保留的是否引用了要移走的
    print("\n=== 依赖检查（保留的文件是否 import 了要移走的）===")
    move_stems = {Path(n).stem for n in move}
    danger = []
    # **检查必须扫「全部文件」，不只是 keep**（BUG-109）。
    # 否则「一整组活模块都被移走」这种情况一个都查不出来。
    for n in sorted(existing):
        # 审计工具只是把名字当字符串列出来，不是真依赖，跳过
        if n.startswith("audit_") or n in ("cleanup_tools.py",):
            continue
        if n in move_stems:
            continue        # 自己要走的不用查
        p = (CORE / Path(n).name) if n.startswith("core/") else (TOOLS / n)
        if p.suffix != ".py":
            continue
        s = p.read_text(encoding="utf-8", errors="replace")
        # 只看真正的 import 语句
        imports = set()
        for m in re.finditer(r"^\s*(?:from\s+(\S+)\s+import|import\s+(\S+))", s, re.M):
            mod = (m.group(1) or m.group(2) or "").split(".")[0]
            if mod:
                imports.add(mod)
        for stem in move_stems & imports:
            danger.append((n, stem))
    if danger:
        for a, b in danger:
            print(f"  ⚠ {a} 引用了 {b}")
        print("\n→ 有依赖，先解决再移动")
        if args.apply:
            return 5
    else:
        print("  ✔ 没有依赖，可以安全移走")

    if not args.apply:
        print("\n（预演模式。加 --apply 真移动）")
        return 0

    LEGACY.mkdir(exist_ok=True)
    moved = 0
    for n in move:
        src = (CORE / Path(n).name) if n.startswith("core/") else (TOOLS / n)
        if not src.exists():
            continue
        dst = LEGACY / src.name
        if dst.exists():
            dst = LEGACY / f"{src.stem}_dup{src.suffix}"
        shutil.move(str(src), str(dst))
        moved += 1
    print(f"\n已移动 {moved} 个文件到 {LEGACY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())