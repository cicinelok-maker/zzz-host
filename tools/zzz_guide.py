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


def open_material_calc(ui: Ui, accept: bool = True) -> dict:
    """打开「养成材料计算」设置框，读它列的等级，然后确定关闭。

    ## 这个面板是什么（实测）

    ```
    养成材料计算  [?]                        [X]
    已根据游戏内培养建议为您完成初始配置，您可以继续按需调整

    代理人等级
      [丽娜]     目标等级与起始等级相同，无需计算

    技能等级
      [普通攻击]  Lv.3 ──●──── Lv.7
      [闪避]      Lv.2 ──●──── Lv.7
      [支援技]    Lv.2 ──●──── Lv.7

            [重置]        [确定]
    ```

    **这是「设目标等级」的面板** —— 每行是「当前 Lv → 目标 Lv」的滑块。
    默认值就是「游戏内培养建议」，所以**直接点「确定」就是按官方推荐算**。

    ## 为什么必须处理它

    点「养成材料计算」会弹出这个框，**它挡着下面的「需要获取的材料 / 养成材料明细」标签**。
    我第一版直接找明细子标签，找不到就是因为这个框还在。

    Returns 读到的 {标题: [(项目, 当前, 目标)]}。
    """
    vs, inp = ui.vs, ui.inp
    out: dict = {}

    def click(label: str, region=(0, 0, 1920, 1080)) -> bool:
        vs.frame(force=True)
        hit = vs.find(label, region)
        if not hit:
            return False
        inp.move(hit["cx"], hit["cy"])
        time.sleep(0.2)
        inp.click(hit["cx"], hit["cy"], wait=2.0)
        try:
            vs.wait_still(quiet=0.4, timeout=2.5)
        except Exception:
            time.sleep(0.4)
        vs.frame(force=True)
        return True

    # 打开
    if not click("养成材料计算", (700, 140, 1300, 300)):
        return out
    vs.frame(force=True)

    txt = vs.text((0, 0, 1920, 1080))
    if "技能等级" not in txt and "代理人等级" not in txt:
        # 没有弹框，说明直接切过去了
        return out

    # 读「项目 Lv.X ... Lv.Y」这种行
    import re
    items = vs.items((300, 150, 1500, 950))
    rows: list[tuple[int, str, list[str]]] = []
    for it in items:
        t = (it.get("text") or "").strip()
        y = int(it.get("cy") or 0)
        if re.fullmatch(r"Lv\.\d+", t):
            rows.append((y, t, []))
        elif t and 1 <= len(t) <= 8 and not t.startswith("Lv."):
            rows.append((y, t, []))
    rows.sort()

    # 按 y 聚成「一行一个项目」
    cur_name = ""
    cur_lvs: list[str] = []
    cur_y = -999
    for (y, t, _) in rows:
        if abs(y - cur_y) > 40:
            if cur_name or cur_lvs:
                out[cur_name or "?"] = list(cur_lvs)
            cur_name = ""
            cur_lvs = []
            cur_y = y
        if t.startswith("Lv."):
            cur_lvs.append(t)
        else:
            cur_name = t
    if cur_name or cur_lvs:
        out[cur_name or "?"] = list(cur_lvs)

    # 确定关闭
    if accept:
        click("确定", (600, 800, 1400, 950))
    return out


def switch_to_detail(ui: Ui) -> bool:
    """切到「养成材料明细」。

    ## 层级（实测 —— 我一开始搞错了）

    养成指南有**三个主标签**（左侧竖排）：
    ```
    方案概览        ← 属性&等级 / 驱动盘推荐 / 属性推荐 / 队伍 / 技能推荐
    养成材料计算     ← **「需要获取的材料」和「养成材料明细」是它下面的两个子标签**
    补充建议        ← 一段文字建议
    ```

    **而且这两个子标签是竖排的**（实测「需要获取的材料」在 (564,272)，
    「养成材料明细」在 (552,674)），**不是横排**。
    我一开始按横排猜区域 (600,200)-(1500,400)，所以找不到 ——
    **现在改成全屏查找，不猜方位。**

    **所以找「养成材料明细」之前，必须先点「养成材料计算」。**
    我第一版直接全屏找「养成材料明细」，
    在「方案概览」视图下当然找不到（返回 False）。

    ## 流程

    1. 有「养成材料明细」→ 直接点
    2. 没有但有「养成材料计算」→ 先点它，再点明细
    3. 都不行 → 失败
    """
    vs, inp = ui.vs, ui.inp

    def click(label: str, region=(0, 0, 1920, 1080)) -> bool:
        vs.frame(force=True)
        hit = vs.find(label, region)
        if not hit:
            return False
        inp.move(hit["cx"], hit["cy"])
        time.sleep(0.2)
        inp.click(hit["cx"], hit["cy"], wait=2.2)
        try:
            vs.wait_still(quiet=0.4, timeout=2.5)
        except Exception:
            time.sleep(0.4)
        vs.frame(force=True)
        return True

    vs.frame(force=True)

    # ① 明细子标签已经在
    if vs.find("养成材料明细", (0, 0, 1920, 1080)):
        click("养成材料明细", (0, 0, 1920, 1080))
    else:
        # ② 先点主标签「养成材料计算」—— **它会弹一个设置框，必须点「确定」关掉**
        if not click("养成材料计算", (700, 140, 1300, 300)):
            print("  找不到「养成材料计算」主标签")
            return False
        # 弹框挡着子标签，先确定
        vs.frame(force=True)
        if vs.find("确定", (600, 800, 1400, 950)):
            print("  「养成材料计算」弹了设置框，点「确定」")
            click("确定", (600, 800, 1400, 950))
        # 再点明细
        if not click("养成材料明细", (0, 0, 1920, 1080)):
            print("  找不到「养成材料明细」子标签")
            return False

    vs.frame(force=True)
    ok = "所需" in vs.text((600, 380, 1800, 1080))
    if not ok:
        print("  点了明细但没看到「所需」表头")
    return ok


def current_agent(ui: Ui) -> str:
    """读养成指南当前选中的角色名（左侧面板下部）。"""
    vs = ui.vs
    vs.frame(force=True)

    # **区域必须收窄到「角色牌」那块** —— 原来用 (180,830,700,1010)，
    # 把方案视图右上角的「推荐队伍」也读进来了（实测误判成角色名）。
    #
    # 实测角色名在 (320±60, 868±30)：
    #   材料视图  挽昼 @(344,908)
    #   方案视图  知更鸟 @(320,868) 一带
    SKIP = ("RANK", "WIKI", "前瞻", "UP", "推荐队伍", "养成指南",
            "养成材料计算", "代理人攻略", "方案概览", "补充建议")
    for region in ((250, 850, 660, 930), (250, 890, 660, 960)):
        for it in vs.items(region):
            t = (it.get("text") or "").strip()
            if not t or any(k in t for k in SKIP):
                continue
            # 角色名：中文字 + 可能带 ·
            if re.fullmatch(r"[\u4e00-\u9fa5·]{1,12}", t):
                return t
    return ""


def select_agent(ui: Ui, name: str, max_clicks: int = 30) -> bool:
    """在养成指南里切到指定角色。

    **实现方式：点右箭头循环，每点一次读一次左下的角色名，匹配就停。**

    为什么不用 ⊞ 那个网格图标：它打开的可能是个更大更慢的选择页，
    而「点箭头 + 读名字」在 30 次内一定覆盖完（角色最多一百来个，
    但顶部条是「这个版本有攻略的」，通常十几个）。
    """
    vs, inp = ui.vs, ui.inp
    vs.frame(force=True)

    # **先点左箭头回起点** —— 选择条点过末尾会进空槽（左面板全黑），
    # 而且面板会**记住**这个空状态，关掉重开都恢复不了（实测）。
    # 起点一定是有效角色，所以每次都从起点往右点。
    for _ in range(25):
        inp.click(P_SEL_PREV[0], P_SEL_PREV[1], wait=0.35)
    vs.frame(force=True)

    cur = current_agent(ui)
    print(f"  当前角色：{cur or '?'}　目标：{name}")
    if cur and (cur == name or name in cur or cur in name):
        print("  已经是目标角色")
        return True

    for i in range(max_clicks):
        inp.click(P_SEL_NEXT[0], P_SEL_NEXT[1], wait=1.2)
        vs.frame(force=True)
        cur = current_agent(ui)
        if cur and (cur == name or name in cur or cur in name):
            print(f"  第 {i + 1} 次点击切到「{cur}」")
            # 切换后要等它重算（智能计算有延迟）
            for _ in range(6):
                try:
                    vs.wait_still(quiet=0.4, timeout=1.5)
                except Exception:
                    time.sleep(0.4)
                if "养成材料" in vs.text((600, 380, 1800, 1080)):
                    break
                time.sleep(0.5)
            return True
    print(f"  ✘ 点了 {max_clicks} 次没找到「{name}」，最后停在「{cur or '?'}」")
    return False


def read_detail(ui: Ui) -> dict:
    """读当前「养成材料明细」页。

    ## 布局（实测两屏，列位置不一样）

    ```
    代理人技能升级              1,187,500      ← 节标题（左）+ 丁尼（右）
    养成材料    所需    已有    仍需获取        ← 表头
    基础电击芯片  12     0      12
    进阶电击芯片  75     0      75
    ```

    挽昼那屏：材料名 x≈895　所需 x≈1243　已有 x≈1404　仍需 x≈1565
    丽娜这屏：材料名 x≈634　所需 x≈1043　已有 x≈1203　仍需 x≈1365

    **差一两百像素 —— 所以列位置必须从表头动态取，不能写死。**

    ## 做法

    1. 找表头行（含「所需」「已有」「仍需获取」），记下三列的 x
    2. 每个数字按「离哪个列锚点最近」归类
    3. 节标题 = 左侧不是数字、不是表头、不在材料名列的文本
    """
    import re

    vs = ui.vs
    vs.frame(force=True)
    items = vs.items((0, 0, 1920, 1080))

    def txt(it) -> str:
        return (it.get("text") or "").strip()

    def cx(it) -> int:
        return int(it.get("cx") or 0)

    def cy(it) -> int:
        return int(it.get("cy") or 0)

    out: dict = {"分节": [], "角色": ""}

    # ---------- ① 找表头，拿三列的 x 锚点 ----------
    heads = [it for it in items if "所需" in txt(it) or "仍需" in txt(it)
             or txt(it) in ("已有", "养成材料")]
    if not heads:
        return out
    # 表头应该在同一行
    hy = min(cy(x) for x in heads)
    heads = [x for x in heads if abs(cy(x) - hy) <= 25]

    col = {}
    for it in heads:
        t = txt(it)
        if "所需" in t:
            col["所需"] = cx(it)
        elif "仍需" in t:
            col["仍需"] = cx(it)
        elif t == "已有":
            col["已有"] = cx(it)
        elif t == "养成材料":
            col["材料"] = cx(it)
    if len(col) < 3:
        return out

    anchors = [(k, v) for k, v in col.items() if k != "材料"]

    def which_col(x: int) -> str:
        """这个数字属于哪一列（取最近的锚点）。"""
        best, bd = "", 10 ** 9
        for k, ax in anchors:
            d = abs(x - ax)
            if d < bd:
                best, bd = k, d
        return best if bd < 220 else ""

    name_x = col.get("材料", min(v for _, v in anchors))

    # ---------- ② 角色名（左侧，材料表上方）----------
    SKIP_ROLE = ("RANK", "WIKI", "养成", "材料", "明细", "计算", "方案",
                 "补充", "代理人技能", "代理人升级")
    for it in vs.items((150, 780, 700, 1010)):
        t = txt(it)
        if not t or any(k in t for k in SKIP_ROLE):
            continue
        if re.fullmatch(r"[\u4e00-\u9fa5·]{1,12}", t):
            out["角色"] = t
            break

    # ---------- ③ 按 y 聚类成行 ----------
    rows: dict[int, list] = {}
    for it in items:
        t = txt(it)
        if not t:
            continue
        y = cy(it)
        key = next((k for k in rows if abs(k - y) <= 22), y)
        rows.setdefault(key, []).append(it)

    section = None
    for y in sorted(rows):
        line = sorted(rows[y], key=cx)
        texts = [txt(x) for x in line]

        # 表头行跳过
        if "所需" in texts and "仍需获取" in texts:
            continue

        # **丁尼（5 位以上的数字）不算列数据** ——
        # 它是一个大额货币，出现在节标题行右侧。
        # 我原来把它当「仍需获取」列的数字，导致节标题行被判成材料行、
        # 然后因为 `section is None` 被整行丢弃（实测「代理人技能升级」那一行就这么没了）。
        nums = []
        money = ""
        for x in line:
            v = txt(x)
            if not re.fullmatch(r"[\d,]+", v):
                continue
            if len(v.replace(",", "")) >= 5:
                money = v
                continue
            c = which_col(cx(x))
            if c:
                nums.append((c, v))

        # 材料名：在材料名列左边那一带、不是数字
        names = [x for x in line
                 if cx(x) <= name_x + 260 and not re.fullmatch(r"[\d,]+", txt(x))
                 and "所需" not in txt(x) and "仍需" not in txt(x)]

        # ---------- 节标题行 ----------
        if names and not nums:
            head = txt(names[0])
            if any(k in head for k in ("代理人", "技能", "音擎", "驱动盘",
                                       "核心", "晋升", "等级")):
                section = {"节": head, "丁尼": money, "材料": []}
                out["分节"].append(section)
            continue

        # ---------- 材料行 ----------
        if nums and names:
            _nm = txt(names[0])
            # **OCR 别名** —— 实测「「仓鼠笼」访问器」被读成 `CC`。
            # 这种「读成完全不相干的短串」只能靠显式表。
            try:
                import json as _j
                from pathlib import Path as _P
                _M = _j.loads((_P(__file__).parent / "materials.json")
                              .read_text(encoding="utf-8"))
                _nm = (_M.get("OCR别名") or {}).get(_nm, _nm)
            except Exception:
                pass
            ent = {"材料": _nm}
            for c, v in nums:
                ent[c] = int(v.replace(",", ""))
            if section is not None:
                section["材料"].append(ent)
            else:
                # **节标题滚出屏幕了** —— 材料还在，但不知道属于哪一节。
                # 先扔进「_未归属」，由 read_detail_all 挂到「上一次见到的节」下面。
                #
                # 踩过：原来这里是 `if section is not None` 才收，
                # 结果滚到「核心技」时标题已经滚上去了，
                # **核心技的材料全被归到了上一节「代理人技能升级」里。**
                out.setdefault("_未归属", []).append(ent)

    return out



def read_detail_all(ui: Ui, max_scroll: int = 20) -> dict:
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
    # **不要在这里按 ESC！**
    #
    # 我原来写了「如果看到『所需』但没有『养成材料』就按 ESC 关弹窗」——
    # 但**「养成材料明细」页本身就是有『所需』没『养成材料』**，
    # 结果连按两次 ESC 把整个养成指南面板关掉了。
    #
    # 材料详情的 tooltip 是「点材料行才弹」的，正常流程不会出现；
    # 真出现了也不该在滚动循环之前处理。
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

        # **无主材料挂到「上一次见到的节」下面**
        # 滚动的方向是「标题先出现，材料后出现」，
        # 所以「材料出现时标题已滚走」= 它属于刚才那一节。
        _orphan = d.get("_未归属") or []
        if _orphan:
            tgt = None
            if merged["分节"]:
                tgt = merged["分节"][-1]
            if tgt is not None:
                have = {m.get("材料") for m in tgt.get("材料") or []}
                for m in _orphan:
                    if m.get("材料") not in have:
                        tgt["材料"].append(m)
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
