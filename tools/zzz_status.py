"""角色练度体检：读六个位号实际装备的驱动盘，算有效词条总数与毕业进度。

毕业标准（NGA 实测口径）：
    小毕业 28 条 / 实战够用 32 条 / 大毕业 37 条（六盘合计）

    python tools/zzz_status.py 佩洛伊斯
    python tools/zzz_status.py 佩洛伊斯 --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, Journal, anchors, vocab  # noqa: E402
from core.machine import Machine  # noqa: E402
from core.slots import slot_xy  # noqa: E402

R_DETAIL = (500, 120, 900, 980)

GRAD = [("小毕业", 28.0), ("实战够用", 32.0), ("大毕业", 37.0)]


def _warn_unknown(agent: str) -> None:
    """角色不在库里时的警告。说清「哪里不准」和「怎么补」。"""
    print()
    print("=" * 66)
    print(f"⚠ 「{agent}」不在角色库里（disc_meta.json）")
    print("="  * 66)
    print("  · 仍然会读取：装备、等级、副词条、质量分 —— 这些不依赖配装知识")
    print("  · 会不准的：「主词条对不对」按【强攻】模板判定")
    print("  · 补数据：在 tools/disc_meta.json 的「角色」下加一段，")
    print(f"      至少给「定位」和「属性」，例如：")
    print(f'        "{agent}": {{"定位": "强攻", "属性": "以太"}}')
    print("=" * 66)
    print()

def rolls(s: str) -> int:
    """升级次数。没有 +N 就是 0（口径B 下「存在」另算 1）"""
    m = re.search(r"\+(\d+)", s or "")
    return int(m.group(1)) if m else 0


def stat_of(s: str) -> str:
    m = re.match(r"\s*([^\s+]+)", s or "")
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-unknown", action="store_true",
                    help="角色不在库里也继续（按强攻模板判定，可能不准）")
    ap.add_argument("agent", nargs="?", default="佩洛伊斯")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    # 角色名校验：能纠正就纠正，纠正不了就退出（不静默走默认）
    try:
        from core.agent_cfg import resolve_agent
        _canon = resolve_agent(args.agent,
                               allow_unknown=args.force_unknown)
        if _canon != args.agent:
            print(f"（角色名「{args.agent}」→「{_canon}」）")
            args.agent = _canon
        from core.agent_cfg import is_known
        if not is_known(args.agent):
            _warn_unknown(args.agent)
    except Exception as _e:
        print(f"✘ {_e}")
        return 3


    meta_all = json.loads((HERE / "disc_meta.json").read_text(encoding="utf-8"))
    cfg = (meta_all.get("角色") or {}).get(args.agent)
    if not cfg:
        print(f"{args.agent} 不在 disc_meta.json")
        return 2
    good = set(cfg["有效副词条"])
    half = set(cfg.get("次选副词条") or [])

    vs, inp = Vision(), Input()
    # **`--json` 就该输出 JSON**（RT-REPORT N-2）。
    #
    # 真机实测：`zzz_status --json` 的 stdout 里 27 行全是中文，
    # **一个 JSON 字符都没有** —— `--json` 实际上只是「写盘开关」。
    #
    # 这里把人类可读文本改道到 stderr，stdout 只留 JSON。
    # Unix 惯例：stdout 给机器，stderr 给人。
    # （实测确认：全项目没有一处解析它的 stdout —— 都读 state/status_*.json）
    _real_stdout = sys.stdout
    if args.json:
        sys.stdout = sys.stderr

    ui = Ui(vs, inp)
    log = Journal(f"体检_{args.agent}")
    ui.start()
    m = Machine(ui, verbose=False)
    print(f"{args.agent}｜有效={sorted(good)} 次选={sorted(half)}")

    # 关键：先确认当前选中的是目标角色，否则读到的是别人的配装
    from pick_agent import select_agent, current_name
    if not select_agent(ui, m, args.agent):
        print(f"  选不中「{args.agent}」（当前「{current_name(vs)}」），中止以免读错人")
        return 4
    print(f"  已选中「{args.agent}」")

    # ---- 角色等级 + 技能等级 ----
    def read_level() -> tuple[str, dict]:
        """返回 (角色等级文本, {技能名: 等级})"""
        if not m.go_to("装备页"):
            return "", {}
        vs.frame(force=True)
        h = vs.find("基础", (900, 940, 1500, 1080))
        if h:
            inp.click(h["cx"], h["cy"], wait=2.0)
            vs.frame(force=True)
        lv = ""
        for it in vs.items((1000, 430, 1250, 500)):
            if it["text"].startswith("等级"):
                lv = it["text"]
                break
        # 技能等级
        hits = vs.find_all("技能", (0, 0, 1920, 1080))
        skills = {}
        if hits:
            h2 = max(hits, key=lambda i: i["cy"])
            inp.click(h2["cx"], h2["cy"], wait=2.0)
            vs.frame(force=True)
            t = vs.text((900, 690, 1800, 800))
            nums = re.findall(r"(\d{2})12", t)
            for name, val in zip(("普通攻击", "闪避", "支援技", "特殊技", "连携技"), nums):
                skills[name] = f"{val}/12"
        return lv, skills

    char_lv, skill_lv = read_level()
    if char_lv:
        print(f"\n角色等级：{char_lv}" + ("（已满级）" if "60" in char_lv else ""))
    if skill_lv:
        print("技能等级：" + "  ".join(f"{k} {v}" for k, v in skill_lv.items()))

    result = []
    unread: list[int] = []
    for slot in range(1, 7):
        # 每个位号都回到装备页再重新点，避免状态漂移
        if anchors.is_(ui.vs, "驱动盘定制"):
            ui.inp.click(120, 52, wait=1.6)
        if not m.go_to("装备页"):
            print(f"  {slot} 号位：到不了装备页")
            continue
        # 关键修：go_to 之后必须刷新帧，否则 slot_xy 读的是导航前的旧画面，
        # 算出来的坐标是错的——这才是「位号点击偶发失败」的真正原因。
        vs.frame(force=True)
        from core.slots import slot_map as _sm
        if slot not in _sm(vs):
            print(f"  {slot} 号位：空位（没装盘）")
            result.append({"slot": slot, "set": "", "level": 0, "main": "",
                           "eff": 0.0, "detail": [], "blue": 0})
            continue
        xy = slot_xy(vs, slot)
        if xy is None:
            print(f"  {slot} 号位：认不出位置（可能空位）")
            continue
        # 统一走 core.click.click_verify（同位置重试 + 换偏移）
        from core.click import click_verify
        opened = click_verify(
            ui, xy,
            check=lambda: anchors.is_(vs, "驱动盘定制"),
            tries=4, wait=2.0, label=f"{slot}号位",
        )
        if not opened:
            # 读不到 ≠ 空位。要明确记下来，不能当成 0
            print(f"  {slot} 号位：进不去定制页（读失败，不是空位）")
            result.append({"slot": slot, "set": "?", "level": 0,
                           "main": "", "eff": 0.0, "detail": ["读失败"]})
            unread.append(slot)
            continue
        # 定制页的详情区位置不稳定（和仓库不同），改读全屏按关键词切
        # 复用 zzz_disc_train 里已验证的读取器（全屏解析 + 属性名过滤）
        from zzz_disc_train import read_disc, evaluate as ev_disc
        d0 = read_disc(vs)
        e0 = ev_disc(d0, good, half)
        eff = e0["eff"]
        try:
            from core import disc_color as _dc
            blue = _dc.report(vs)["蓝色条数"]
        except Exception:
            blue = 0
        # 游戏用颜色标出有效副词条，这里数蓝条——和用户肉眼数的一致
        try:
            from core import disc_color as _dc
            _rep = _dc.report(vs)
            blue = _rep["蓝色条数"]
        except Exception:
            blue = 0
        detail = [f"{x['name']}+{x['rolls']}" for x in e0["subs"]]
        if not d0["set"]:
            print(f"  {slot} 号位：读不到")
            continue
        main = ""
        for x in e0["subs"]:
            pass
        txt2 = vs.text((0, 0, 1920, 1080))
        if "主属性" in txt2:
            seg = txt2.split("主属性", 1)[1].split("副属性", 1)[0]
            for part in seg.split("|"):
                q = part.strip()
                if any(q.startswith(k) for k in vocab.STATS):
                    main = q
                    break
        # 主词条校验：这个主词条适不适合这个角色
        from core.disc_main import verdict as _mv
        from core.game_cfg import element_of as _eo
        mw = (cfg.get("主词条") or {})
        mverdict, mnote = _mv(main, slot, mw, _eo(args.agent))
        result.append({"slot": slot, "set": d0["set"], "level": d0["level"],
                       "main": main, "eff": round(eff, 1), "detail": detail,
                       "blue": blue, "main_verdict": mverdict,
                       "main_note": mnote})
        _mark = {"good": "✔", "weak": "~", "bad": "✘", "unknown": "?"}.get(
            mverdict, "?")
        print(f"  {slot} 号位  {d0['set']:<8} Lv{d0['level']:<2} "
              f"{_mark}主:{main or '?':<12} 有效 {eff:>4} 条  "
              f"{'/'.join(detail) or '无'}")
        if mverdict == "bad":
            print(f"      ⚠ {mnote}")

        log.log(f"{slot}号位", d0["set"] or "空", ok=bool(d0["set"]),
                detail=f"Lv{d0['level']} 有效{eff}")

    # **主词条是硬门槛**：主词条对这个角色没用的盘，副词条再好也是 0 价。
    # 用户在 2026-11-25 明确：主词条不对，副词条再好也「是一坨狗屎」。
    # 不归零的话总分虚高 —— 实跑踩过：4号位主防御力，eff 4.0 被算进 24.0，
    # 换掉它之后总分「下降」，让人以为换装亏了。
    total = round(sum(0.0 if r.get("main_verdict") == "bad" else r["eff"]
                      for r in result), 1)
    blue_count = sum(r.get("blue", 0) for r in result)
    _occ = len([r for r in result if r.get("set") and r["set"] not in ("", "?")])
    print()
    print(f"合计：{_occ} 个位号有盘（空 {6 - _occ}）")
    print(f"  有效副词条  {blue_count} 条（游戏标蓝的个数）")
    print(f"  质量分      {total}（存在1 + 升级N）")
    _bad = [r.get("slot") for r in result if r.get("main_verdict") == "bad"]
    _unk = [r.get("slot") for r in result if r.get("main_verdict") == "unknown"]
    if _bad:
        print(f"  ⚠ 主词条无效 {len(_bad)} 个位号：{_bad}"
              f"（这几条主词条对这个角色没用，优先级高于副词条）")
    if _unk:
        print(f"  ? 主词条读不到：{_unk}")
    if unread:
        print(f"  ⚠ 有 {len(unread)} 个位号**读取失败**：{unread}")
        print(f"    这些位号的词条没算进总数，{total} 条是偏低的，需要重跑")
        print(f"  ⚠ 别把「读取失败」当成「空位」——那是两回事")
    for name, line in GRAD:
        gap = round(line - total, 1)
        mark = "✔ 已达成" if gap <= 0 else f"还差 {gap} 条"
        print(f"  {name:<8}（{line} 条）  {mark}")
    sets = {}
    for r in result:
        sets[r["set"]] = sets.get(r["set"], 0) + 1
    print("套装构成：" + "、".join(f"{k}×{v}" for k, v in sets.items() if k))

    if args.json:
        out = BASE / "state" / f"status_{args.agent}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        # 技能等级也要存，zzz_skill_target / zzz_next 要用
        sk = {}
        for k, v in (skill_lv.items() if isinstance(skill_lv, dict) else []):
            sk[k] = v
        # 打时间戳 —— 三天前读的状态算出来的缺口是错的，但文件看着正常。
        # 见 core/state.py 的 check_fresh()。
        from core.state import stamp as _stamp
        # **下游读的字段必须在这里写全**（RT-REPORT 确认第 1 条 / N-3）。
        #
        # 真机实测：文件里只有 agent/total/slots/skills/char_level，
        # 而 `zzz_who` 读 `blue_total`、`zzz_plan`/`zzz_grind` 读 `unread`，
        # 于是 `zzz_who` 的「主词条×N」告警**永久失效**，
        # `zzz_grind` 的进展永远是 `0.0 → 0.0`。
        #
        # 而且这不是「旧文件残留」——文件内容三次运行一字不变，
        # 说明这两个键**从来没被写过**。
        _payload = {"agent": args.agent, "total": total,
                    "blue_total": blue_count,   # 游戏里标蓝的副词条个数
                    "unread": list(unread),     # 读取失败的位号
                    "slots": result, "skills": sk,
                    "char_level": char_lv}
        _data = _stamp(_payload)
        out.write_text(json.dumps(_data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"\n已写入 {out}")
        # **stdout 只留 JSON**（人类文本已经在 stderr 上了）
        sys.stdout = _real_stdout
        print(json.dumps(_data, ensure_ascii=False))
    print()
    print(log.summary())
    # 兜底恢复 —— 没走写盘分支时 stdout 还指着 stderr
    if args.json and sys.stdout is not _real_stdout:
        sys.stdout = _real_stdout
    return 0


if __name__ == "__main__":
    sys.exit(main())