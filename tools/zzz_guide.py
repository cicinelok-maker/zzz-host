"""读游戏内「养成指南 → 养成材料明细」—— 官方材料缺口表。

## 这不是估算，是游戏自己算好的

实测界面（2026-11-26，ESC → 更多 → 养成指南 → 养成材料明细）：

```
养成指南
养成材料计算    智能计算    智能计算设置
需要获取的材料 | 养成材料明细        ← 两个 tab
仓库数据计算存在10分钟左右延迟，请悉知   ← 它读真实库存

─────────────────────────────────────────
代理人升级&晋升              800,000（丁尼）
养成材料        所需    已有    仍需获取
初阶锋御认证章    4      10       0
高阶锋御认证章    32     0        32
执锋者认证章      30     0        30
资深调查员记录    300    181      119
─────────────────────────────────────────
代理人技能升级              1,780,000（丁尼）
养成材料        所需    已有    仍需获取
…
─────────────────────────────────────────
```

## 为什么这比我们自己的材料表好

**我们自己算的（`zzz_farm_plan`）：**
```
读 status → 查 materials.json → 算缺口 → 查副本
```
· 材料表要手维护，而且一直错（最高模块/电流/章层数）
· 库存要自己记（inventory.json 还得靠 material 顺手记）
· 缺口是「估算」（CHIP_PER_LEVEL=12 这种粗估）

**游戏算的：**
· 材料名——官方，不会错
· 所需 / 已有 / 仍需获取——**精确值，而且已经有真实库存**
· 分模块（升级&晋升 / 技能升级 / 核心技 / 音擎 / 驱动盘）
· 还会按「最高稀有度合成」自动折算

**所以正确做法是：读游戏算好的结果，不再自己算。**

## 顺带一个重要数据

**「执锋者认证章」** —— 锋御职业的专属认证章名，之前一直没查到。
（日文对照：ブレイカー/コマンダー/ガードナー…… 锋御是较新的职业）

## 用法

```powershell
python tools/zzz_guide.py                    # 进养成指南，打印当前角色的材料明细
python tools/zzz_guide.py --json             # 输出结构化 JSON
```
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, anchors  # noqa: E402
import live  # noqa: E402

# 主菜单「更多」的位置（实测）
P_MORE_Y = 1040


def _to_world(ui: Ui, tries: int = 6) -> bool:
    """退回大世界。

    **注意：ESC 和手柄 B 在这里不能互换。**
    实测（2026-11-26）：
      · 养成指南全屏面板 —— `pad_tap("b")` **无效**，只有 ESC 能关
      · 主菜单 —— ESC 能关回大世界
      · 一般界面 —— 手柄 B 也能退

    所以顺序是：**先 ESC（对全屏面板唯一有效），ESC 不行再 B**。
    反过来（先 B）会在养成指南里死循环。
    """
    vs, inp = ui.vs, ui.inp
    for i in range(tries):
        vs.frame(force=True)
        if anchors.describe(vs) == "世界":
            return True
        if i < 3:
            inp.key("esc", wait=1.5)          # 全屏面板只有 ESC 能关
        else:
            try:
                inp.pad_tap("b", wait=1.1)    # 一般界面用 B（无副作用）
            except Exception:
                inp.key("esc", wait=1.4)
        time.sleep(0.6)
    vs.frame(force=True)
    return anchors.describe(vs) == "世界"


def open_guide(ui: Ui) -> bool:
    """进「养成指南」。**走 Machine.go_to**（状态机 + BFS 路径规划）。

    转移表在 `core/machine.py` 的 TRANSITIONS：
        大世界 → 主菜单（ESC）
        主菜单 → 更多功能（点「更多」）
        更多功能 → 养成指南（点「养成指南」）

    这样就不用在这里手写导航 —— 路径由状态机算。
    """
    from core.machine import Machine

    vs, inp = ui.vs, ui.inp

    # 先回大世界（养成指南是全屏面板，B 无效，只能 ESC）
    if not _to_world(ui):
        # 退不回就再试 ESC 几次
        for _ in range(3):
            inp.key("esc", wait=1.5)
            vs.frame(force=True)
            if anchors.describe(vs) == "世界":
                break

    m = Machine(ui, verbose=True)
    cur = anchors.describe(vs)
    if cur == "养成指南":
        return True
    ok = m.go_to("养成指南")
    if not ok:
        # go_to 内部最后一次 state() 的 OCR 还在 TTL 缓存里，
        # 直接 describe 可能拿到旧结果 → 先强制刷帧
        vs.frame(force=True)
        print(f"  ✘ 到不了养成指南（当前 {anchors.describe(vs)}）")
        return False
    return True


def switch_to_detail(ui: Ui) -> bool:
    """切到「养成材料明细」标签页。"""
    vs, inp = ui.vs, ui.inp
    vs.frame(force=True)
    hit = vs.find("养成材料明细", (0, 0, 1920, 1080))
    if not hit:
        return False
    inp.click(hit["cx"], hit["cy"], wait=2.5)
    try:
        vs.wait_still(quiet=0.4, timeout=3.0)
    except Exception:
        time.sleep(0.5)
    vs.frame(force=True)
    return "所需" in vs.text((0, 0, 1920, 1080))


def read_detail(ui: Ui) -> dict:
    """读当前「养成材料明细」页。

    布局（实测）：
        材料名 @ x≈895    所需 @ x≈1243    已有 @ x≈1404   仍需获取 @ x≈1565
    按 y 分组即可成行。
    """
    vs = ui.vs
    vs.frame(force=True)
    items = vs.items((0, 380, 1920, 1080))

    # 按 y 聚类成分行
    rows: dict[int, list] = {}
    for it in items:
        t = (it.get("text") or "").strip()
        if not t:
            continue
        y = int(it.get("cy") or 0)
        key = next((k for k in rows if abs(k - y) <= 22), y)
        rows.setdefault(key, []).append(
            {"t": t, "x": int(it.get("cx") or 0), "y": y})

    out = {"分节": [], "角色": ""}
    section = None

    # 角色名先单独找一遍：左下角 x<500、y 在 850~1000、不是功能词
    # （和 RANK 同一行，所以不能靠「这一行只有一条」判断）
    SKIP = {"RANK", "WIKI", "规则", "养成", "材料", "所需", "已有", "仍需"}
    for it in vs.items((200, 850, 700, 1010)):
        t = (it.get("text") or "").strip()
        if not t or any(k in t for k in SKIP):
            continue
        if 1 <= len(t) <= 14:
            out["角色"] = t
            break
    for y in sorted(rows):
        line = sorted(rows[y], key=lambda z: z["x"])
        texts = [z["t"] for z in line]

        # （角色名已在前面单独读过了）

        # 分节标题（左对齐的单条长文本 + 右侧丁尼）
        if len(line) >= 1 and line[0]["x"] < 900 and line[0]["x"] > 700:
            head = line[0]["t"]
            if any(k in head for k in ("代理人", "技能", "音擎", "驱动盘", "核心")):
                section = {"节": head, "丁尼": "", "材料": []}
                out["分节"].append(section)
                # 右侧数字可能是丁尼
                if len(line) > 1 and re.match(r"^[\d,]+$", texts[-1]):
                    section["丁尼"] = texts[-1]
                continue

        # 表头行
        if "所需" in texts and "仍需获取" in texts:
            continue

        # 材料行：**按 x 坐标区间取数**，不靠「排序后前三个」
        #
        # 实测列位置：材料名 x≈895　所需 x≈1243　已有 x≈1404　仍需 x≈1565
        # 之前按「排序后取前 3 个数字」，遇到 OCR 把某个数拆成两段就会错位
        # （资深调查员记录 300/181/119 被读成 29/300/181）。
        def _pick(lo, hi):
            c = [z for z in line if lo <= z["x"] < hi and re.match(r"^[\d,]+$", z["t"])]
            return c[0]["t"] if c else None

        names = [z for z in line if z["x"] < 1200 and not re.match(r"^[\d,]+$", z["t"])]
        if names and section is not None:
            name = names[0]["t"]
            need = _pick(1200, 1350)
            have = _pick(1350, 1500)
            left = _pick(1500, 1920)
            if need is None and have is None:
                continue                      # 这行不是材料行
            ent = {"材料": name}
            for k, v in (("所需", need), ("已有", have), ("仍需", left)):
                if v is not None:
                    ent[k] = int(v.replace(",", ""))
            section["材料"].append(ent)

    return out


def read_detail_all(ui: Ui, max_scroll: int = 8) -> dict:
    """**滚着读完整个「养成材料明细」**（一节一节读到底）。

    实测：明细页一屏只放得下 1~2 节（代理人升级&晋升 / 技能升级 / …），
    不滚动只能读到第一节 —— 属性也就推不出来（芯片在第二节）。

    滚动信号和扫角色列表一样：**画面文本没变 = 滚到底了。**
    """
    vs, inp = ui.vs, ui.inp
    merged = {"分节": [], "角色": ""}
    seen_sections: set[str] = set()
    last_sig = ""

    # **滚轮跟着鼠标位置走** —— 实测不先把鼠标移到面板里，`wheel` 完全无效
    # （试过 wheel(-4)、PageDown、方向键，文本长度一直是 217 不变）。
    #
    # 面板的可滚动区域大约在 x 620~1700、y 380~1050（看截图量的）。
    # 顺便先按一下 ESC 关掉可能的材料详情弹窗（点材料行会弹出来）。
    for _ in range(2):
        if "所需" in vs.text((600, 380, 1800, 1080)) and "养成材料" not in vs.text(
                (600, 380, 1800, 1080)):
            inp.key("esc", wait=1.0)
            vs.frame(force=True)
        else:
            break
    inp.move(1200, 600)
    time.sleep(0.3)

    for i in range(max_scroll + 1):
        if i > 0:
            inp.move(1200, 600)          # 每次都确保鼠标在面板内
            inp.wheel(-4, wait=1.5)
            vs.frame(force=True)

        vs.frame(force=True)
        sig = vs.text((600, 380, 1800, 1080))
        if i > 0 and sig == last_sig:
            break                       # 滚不动了
        last_sig = sig

        d = read_detail(ui)
        if d.get("角色") and not merged["角色"]:
            merged["角色"] = d["角色"]

        # **丢掉「名字等于角色名」的行** —— 「音擎强化&进阶」那一节的材料表里
        # 有一条是音擎本体（用来精炼/改造），名字恰好就是角色名
        # （实测：挽昼的音擎叫「挽昼」，被当成材料 32 个）。
        _self = merged.get("角色") or ""
        if _self:
            for _sec in d.get("分节") or []:
                _sec["材料"] = [m for m in (_sec.get("材料") or [])
                                if (m.get("材料") or "").strip() != _self]

        added = False
        for sec in d.get("分节") or []:
            key = sec.get("节") or ""
            if key in seen_sections:
                # 同一节再次出现（滚动重叠）→ 合并材料
                for tgt in merged["分节"]:
                    if tgt.get("节") == key:
                        have = {m.get("材料") for m in tgt.get("材料") or []}
                        for m in sec.get("材料") or []:
                            if m.get("材料") not in have:
                                tgt["材料"].append(m)
                                added = True
                        break
            else:
                merged["分节"].append(dict(sec))
                seen_sections.add(key)
                added = True

        if not added and i > 0:
            break

    return merged


def main() -> int:
    ap = argparse.ArgumentParser(
        description="读游戏内「养成指南 → 养成材料明细」（官方材料缺口）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--out", default="", help="写到文件")
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()

    print("进「养成指南」…")
    if not open_guide(ui):
        return 3

    print("切到「养成材料明细」…")
    if not switch_to_detail(ui):
        print("  ✘ 切不过去，可能是别的 tab")
        return 4

    d = read_detail(ui)

    if args.json or args.out:
        s = json.dumps(d, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(s, encoding="utf-8")
            print(f"已写入 {args.out}")
        if args.json:
            print(s)
        return 0

    print()
    print(f"角色：{d.get('角色') or '?'}")
    for sec in d["分节"]:
        print()
        print(f"【{sec['节']}】" + (f"  丁尼 {sec['丁尼']}" if sec["丁尼"] else ""))
        if not sec["材料"]:
            print("  （本屏没读到材料行，可能要滚动）")
            continue
        print(f"  {'材料':<18}{'所需':>6}{'已有':>6}{'仍需':>6}")
        for m in sec["材料"]:
            print(f"  {m['材料']:<18}{m.get('所需','?'):>6}"
                  f"{m.get('已有','?'):>6}{m.get('仍需','?'):>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
