"""材料弹窗 → 直接传送到获取副本。

## 用户指出的机制（2026-11-26 01:29）

> 你那个点进去那个材料的图片，不是会弹出那个能获取的界面吗，
> 其实那个界面就是那获取的那两个地方，其实是个按钮来的。
> 你能点进去之后，它就会给你传送到那个获取的界面，或者能获取它的地方

## 实测验证（2026-11-26 01:31）

在核心技強化面板点 E 圈 → 点材料图标 @(135,890)，弹窗 OCR：

```
'刻命残蜕'                                    @(697,344)
'当前拥有×1'                                  @(687,385)
'提升代理人高等级核心技所需的重要物品。'        @(817,423)
'一种稀有形态留存下来的以太凝结物，取自「基塔布鲁」。...'  ← 来源 boss 写在描述里
'[获取]恶名狩猎'                              @(742,595)   ★
'[获取]哨站后勤'                              @(742,666)   ★
```

点 `[获取]恶名狩猎` @(742,595) → 画面弹出 **「是否立即传送？ 取消 | 确认」**

## 为什么这是大发现

**以前**：每个副本的进入路径要硬编码坐标。
`zzz_disc_daily` 里 `m.go_to("驱动盘拆解页")`、`zzz_core.goto_skill_tab()` …
每个都要单独维护，界面一变就全错。

**现在**：想刷任何材料 →
```
进任意能显示这个材料的界面 → 点材料图标 → 点「[获取] xxx」→ 点「确认」→ 到了
```

**不用知道副本在哪、几号入口、要点几次返回。**

## 三个附带的收获

1. **材料真名** —— 弹窗标题就是（不用再猜「最高模块」还是「音擎能源模块」）
2. **当前库存** —— 「当前拥有 ×N」
3. **来源 boss** —— 描述里写着（「取自『基塔布鲁』」），等于 boss→材料对照表
   可以现场读，不用维护静态表

## 用法

```python
from core import material_nav as mnav

pop = mnav.read_popup(vs)         # 读当前弹窗
# {'name': '刻命残蜕', 'have': 1, 'desc': '...', 'sources': [{...}], 'buttons': [{...}]}

mnav.goto_source(ui, pop, index=0)  # 点第一个来源 → 确认传送
```
"""
from __future__ import annotations

import re

# 弹窗区域（全屏更稳 —— 弹窗居中是覆盖层，位置不固定）
R_POPUP = (0, 0, 1920, 1080)

# 「是否立即传送？」的确认按钮
CONFIRM_WORDS = ("确认", "確定", "确定")


def read_popup(vs) -> dict | None:
    """读当前材料弹窗。

    Returns None = 这不是材料弹窗（没有「[获取]」也没有「当前拥有」）。
    """
    txt = vs.text(R_POPUP)
    if "当前拥有" not in txt and "[获取]" not in txt:
        return None

    out = {"name": "", "have": None, "desc": "", "sources": [], "buttons": []}

    items = vs.items(R_POPUP)

    # 材料名：弹窗里最靠上的一条短文本（排除「当前拥有」和「[获取]」）
    for it in sorted(items, key=lambda x: x.get("cy") or 0):
        t = (it.get("text") or "").strip()
        if not t or "当前拥有" in t or "[获取]" in t or "获取" in t:
            continue
        if len(t) <= 20 and not t.endswith("。"):
            out["name"] = t
            break

    m = re.search(r"当前拥有\s*[×x]\s*(\d+)", txt)
    if m:
        out["have"] = int(m.group(1))

    # 描述：从「提升」或「一种」开头的连续几行
    desc_lines = []
    for it in items:
        t = (it.get("text") or "").strip()
        if t.startswith(("提升", "一种", "用于", "可")):
            desc_lines.append(t)
        elif desc_lines and len(desc_lines) < 4 and t and not t.startswith("["):
            desc_lines.append(t)
    out["desc"] = "".join(desc_lines)

    # 「取自「XXX」」→ 来源 boss
    mb = re.search(r"取自[「『]?([^」』，。]{2,20})[」』]?", out["desc"])
    if mb:
        out["boss"] = mb.group(1).strip()

    # [获取] xxx 按钮（这些有坐标，能点）
    for it in items:
        t = (it.get("text") or "").strip()
        if "[获取]" in t or t.startswith("获取"):
            name = t.replace("[获取]", "").strip()
            out["sources"].append({"name": name, "cx": it.get("cx"),
                                   "cy": it.get("cy")})
            out["buttons"].append({"text": t, "cx": it.get("cx"), "cy": it.get("cy")})

    return out


def goto_source(ui, pop: dict, index: int = 0, wait: float = 3.5) -> str | None:
    """点第 index 个「[获取]」按钮 → 确认传送。

    Returns 传送后 `anchors.describe()` 的结果；失败返回 None。

    **会改变游戏状态**（把你送到副本界面），调用前确认这是想要的。
    """
    from core import anchors
    vs, inp = ui.vs, ui.inp
    srcs = pop.get("sources") or []
    if not srcs or index >= len(srcs):
        return None

    src = srcs[index]
    print(f"    点「[获取]{src['name']}」@({src['cx']},{src['cy']})")
    inp.click(src["cx"], src["cy"], wait=2.2)
    vs.frame(force=True)

    # 弹出「是否立即传送？ 取消 | 确认」
    #
    # **不要用「文本里有『传送』」当条件** —— 实测踩过：对话框明明在
    # （文本 "是否立即传送？ | 取消 | 确认"），但那个分支没进去，
    # 结果只点了「获取」没点「确认」，传送失败。
    #
    # 改成**无条件找「确认」**：找到就点，找不到就说明没弹（可能免确认）。
    #
    # 另外要确认「确认」在「取消」右边 —— 弹窗里可能有两个同名按钮，
    # 点错就取消了。
    c = None
    for w in CONFIRM_WORDS:
        hits = vs.items((600, 500, 1500, 800))
        cands = [it for it in hits if (it.get("text") or "").strip() == w]
        if cands:
            c = cands[0]
            break
    if c is None:
        c = vs.find("确认", (700, 550, 1500, 750)) or vs.find("确认", R_POPUP)

    if c:
        # 检查右边没有「取消」（确认应该在右、取消在左）
        same_row = [it for it in vs.items((600, 500, 1500, 800))
                    if abs((it.get("cy") or 0) - (c.get("cy") or 0)) < 20]
        names = [(it.get("text") or "").strip() for it in same_row]
        if "确认" in names or "確定" in names or "确定" in names:
            print(f"      对话框：{names}")
            print(f"      点「确认」@({c['cx']},{c['cy']})")
            inp.click(c["cx"], c["cy"], wait=wait)
            try:
                vs.wait_still(quiet=0.3, timeout=3.5)
            except Exception:
                pass
            vs.frame(force=True)
        else:
            print(f"      找到「{c.get('text')}」但同行没有确认按钮，不动")
    else:
        print("      没有确认框（可能免确认直接传送）")

    name = anchors.describe(vs)
    print(f"      传送后：{name}")
    return name


def goto_by_icon(ui, icon_xy: tuple[int, int], index: int = 0,
                 wait: float = 3.5) -> str | None:
    """**从材料图标开始**：点图标 → 读弹窗 → 点第 index 个「[获取]」→ 确认传送。

    ## 为什么需要这个而不是 goto_source

    `read_material()` 读完会按 ESC 关弹窗。之后再去点保存下来的按钮坐标，
    **弹窗已经没了**，点到的是下面那层界面的随机位置。

    实测踩过：日志写着「点 [获取]恶名狩猎 @(742,595)」，
    然后「没有确认框」—— 因为那时弹窗早关了。

    → 要传送就必须**自己重新开弹窗**，不能用缓存的坐标。
    """
    from core import anchors
    vs, inp = ui.vs, ui.inp

    print(f"    重新打开材料弹窗 @{icon_xy}")
    inp.click(icon_xy[0], icon_xy[1], wait=2.2)
    vs.frame(force=True)

    pop = read_popup(vs)
    if not pop or not pop.get("sources"):
        print("      弹窗打不开或没有来源按钮")
        inp.key("esc", wait=1.0)
        return None

    srcs = pop["sources"]
    if index >= len(srcs):
        print(f"      只有 {len(srcs)} 个来源，要第 {index} 个")
        inp.key("esc", wait=1.0)
        return None

    src = srcs[index]
    print(f"      材料「{pop['name']}」拥有 {pop.get('have')}，"
          f"来源 {[x['name'] for x in srcs]}")
    print(f"      点「[获取]{src['name']}」@({src['cx']},{src['cy']})")
    inp.click(src["cx"], src["cy"], wait=2.5)
    vs.frame(force=True)

    # 找「确认」（同一行里同时有「取消」和「确认」才说明是传送对话框）
    c = None
    for w in ("确认", "確定", "确定"):
        cands = [it for it in vs.items((600, 480, 1500, 820))
                 if (it.get("text") or "").strip() == w]
        if cands:
            c = cands[0]
            break

    if c is None:
        print("      没有传送确认框 —— 可能这个来源不需要确认")
    else:
        row = [it for it in vs.items((600, 480, 1500, 820))
               if abs((it.get("cy") or 0) - (c.get("cy") or 0)) < 25]
        names = [(it.get("text") or "").strip() for it in row]
        print(f"      对话框按钮：{names}")
        print(f"      点「确认」@({c['cx']},{c['cy']})")
        inp.click(c["cx"], c["cy"], wait=wait)
        try:
            vs.wait_still(quiet=0.3, timeout=4.0)
        except Exception:
            pass
        vs.frame(force=True)

    name = anchors.describe(vs)
    print(f"      传送后：{name}")
    return name


def read_hunt_detail(vs) -> dict | None:
    """读恶名狩猎 boss 详情页（从材料「[获取]恶名狩猎」传送过来的界面）。

    ## 实测能读到什么（2026-11-26 01:40）

    ```
    街区 / 挑战等级 Lv.65 / 基塔布(鲁) / 弱点 风属性 / 抗性 无
    当前情报：本次的「狩猎」目标是…蝎形以骸
    挑战奖励 400 150 2-3 3000 6-7 2-3
    **剩余奖励次数：3/3**       ← 免费次数，直接读！
    周期剩余 04天03时
    下一步 @(1721,1027)          ← 开始挑战
    ```

    **这意味着周本免费次数不用自己记账** —— 界面就是权威。
    `core/weekly.py` 那套计数器只是兜底（离线时用）。
    """
    import re
    txt = vs.text((0, 900, 1920, 1080))
    if "剩余奖励次数" not in txt:
        return None

    out = {"free_left": None, "free_max": None, "weeks_left": ""}

    m = re.search(r"剩余奖励次数[：:\s]*(\d+)\s*/\s*(\d+)", txt)
    if m:
        out["free_left"] = int(m.group(1))
        out["free_max"] = int(m.group(2))

    m2 = re.search(r"(\d+)\s*天\s*(\d+)\s*时", txt)
    if m2:
        out["weeks_left"] = f"{m2.group(1)}天{m2.group(2)}时"

    # boss 名（标题区）
    for it in vs.items((600, 150, 1400, 350)):
        t = (it.get("text") or "").strip()
        if t and len(t) <= 12 and not any(
                k in t for k in ("等级", "弱点", "抗性", "街区", "挑战", "属性")):
            out["boss"] = t
            break

    return out


def read_materials_in(view, ui, points: list[tuple[int, int]],
                      close_key: str = "esc") -> dict:
    """依次点一串材料图标，把每个弹窗读出来。

    points: [(x, y), ...] 材料图标的坐标（数字上方 36px 那种）
    返回 {name: {have, desc, boss, sources}}
    """
    vs, inp = view, ui.inp
    out = {}
    for (x, y) in points:
        inp.click(x, y, wait=2.0)
        vs.frame(force=True)
        pop = read_popup(vs)
        if not pop or not pop.get("name"):
            inp.key(close_key, wait=1.0)
            continue
        out[pop["name"]] = {
            "have": pop.get("have"),
            "desc": pop.get("desc", ""),
            "boss": pop.get("boss", ""),
            "sources": [s["name"] for s in pop.get("sources") or []],
        }
        print(f"    {pop['name']}：拥有 {pop.get('have')}　"
              f"来源 {[s['name'] for s in pop.get('sources') or []]}"
              + (f"　取自「{pop['boss']}」" if pop.get("boss") else ""))
        inp.key(close_key, wait=1.0)
    return out
