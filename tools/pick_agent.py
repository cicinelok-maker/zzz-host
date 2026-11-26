"""代理人选择：按「等级标签」定位头像，不猜坐标。

## 为什么改

旧版用硬编码的候选坐标网格逐点试，遇到网格右下角（猫又在 1824,1003）
或角色数量变化就选不中。

## 新做法（数据驱动）

代理人列表里每个头像下方都有「等级N」标签，OCR 能直接读到。
所以：

    1. OCR 找出屏幕上所有「等级N」标签的坐标
    2. 头像中心 = 标签上方约 40px
    3. 逐个点击 + 读左下角名字，命中就停
    4. 把「名字 → 坐标」记到缓存，下次先查缓存

这样完全不需要猜网格布局，角色数量变化、滚动都不影响。

## 缓存

state/agent_positions.json：{名字: [x, y]}
命中的位置记下来，下次直接点，失败再从 OCR 重扫。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, anchors  # noqa: E402
from core.machine import Machine  # noqa: E402

R_NAME = (80, 880, 620, 1030)
R_GRID = (900, 60, 1920, 1080)
AGENT_LABEL_DY = -40
CACHE = BASE / "state" / "agent_positions.json"


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(d: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_name(vs: Vision) -> str:
    """读左下角的当前角色名。

    ## 踩过的三个坑（都是实测证据）

**1 只允许纯中文 2~6 字 → 带「·」的名字全丢**
       `简·杜` / `星徽·比利` / `妮可·德玛拉` 的 `·` 不在 `[\u4e00-\u9fa5]`。

**2 OCR 在名字后面带等级符号 → 整条被拒**
       实测原文：`'简☆ | 2'`、`'凯撒 | ☆'`、`'比利 | ☆双'`。
       `☆` 不在允许集里，`fullmatch` 直接失败。

**3 单字名 + 回退正则要求 `{2,8}` → 单字名救不回来**
       「简」就一个字，`re.findall(r"[\u4e00-\u9fa5]{2,8}")` 捞不到。
       **这就是「简·杜」扫不到的真正原因** （诊断脚本打出 `'简☆ | 2'` 才发现的）。

    ## 现在的做法

    1. **先剥掉等级符号和数字**：`☆★◇◆○●` + 数字 + 空白
    2. 允许 **1~12 个中文字**（单字名存在：简 / 雅 / 西）
    3. 用 UI 词黑名单挡噪音（`非` `山` `人` `友` `目` 这种纯图标碎片）
    4. 整行拼接兜底（OCR 可能把名字拆成多段）
    """
    vs.frame(force=True)
    t = vs.text(R_NAME)

    BAD = ("等级", "UID", "装备", "技能", "基础", "面板", "WIKI", "代理人")
    # 纯图标/界面碎片，不是名字
    NOISE = {"非", "山", "人", "友", "目", "具", "力", "口", "十", "土"}

    def _clean(x: str) -> str:
        x = re.sub(r"[☆★◇◆○●◯◎✦✧＊*]", "", x)
        x = re.sub(r"\d+", "", x)
        x = x.replace(" ", "").strip()
        return x

    cands: list[str] = []
    for part in t.split("|"):
        p = part.strip()
        if not p or any(b in p for b in BAD):
            continue
        c = _clean(p)
        if c:
            cands.append(c)

    NAME_RE = re.compile(r"^[\u4e00-\u9fa5·・.‧•∙]{1,12}$")

    # ① 单段匹配（允许单字名）
    for p in cands:
        if NAME_RE.fullmatch(p) and p not in NOISE and re.search(r"[\u4e00-\u9fa5]", p):
            return p

    # ② 整行拼接（OCR 把名字拆成多段时）
    joined = _clean("".join(cands))
    if joined and NAME_RE.fullmatch(joined) and joined not in NOISE:
        return joined

    # ③ 取最长中文段（允许单字）
    best = ""
    for p in cands:
        for seg in re.findall(r"[\u4e00-\u9fa5]{1,8}", p):
            if len(seg) > len(best) and seg not in NOISE:
                best = seg
    return best


def _describe_stable(vs, tries: int = 2, gap: float = 0.18) -> str:
    """连判几次，任一次认出就用它。

    抢前台/切换画面后的第一帧经常是过渡画面。
    单次判定失败不代表「不在大世界」，可能只是「还没画好」。
    """
    last = "未知界面"
    for i in range(max(1, tries)):
        try:
            vs.frame(force=True)
        except Exception:
            pass
        last = anchors.describe(vs)
        if last != "未知界面":
            return last
        if i + 1 < tries:
            time.sleep(gap)
    return last


def current_name(vs: Vision) -> str:
    if not anchors.is_(vs, "代理人列表"):
        return ""
    return _read_name(vs)


def reset_to_world(ui: Ui, max_esc: int = 6) -> bool:
    """退回大世界。

    **不要在第一帧判不出来时就按键。** ESC 在大世界会打开菜单，
    越按画面越不像大世界 —— 实测会反复重试白花 28 秒。
    所以：先多判几次；确实要按键时，优先用手柄 B（无副作用），ESC 兜底。
    """
    vs, inp = ui.vs, ui.inp

    # 第一轮：只判不按。画面可能还在过渡 —— 先等稳再判。
    try:
        vs.wait_still(quiet=0.3, timeout=2.5)
    except Exception:
        time.sleep(0.4)
    if _describe_stable(vs, tries=3, gap=0.4) == "世界":
        return True

    for i in range(max_esc):
        # 用手柄 B（Xbox 的返回键，走 vgamepad 虚拟手柄）。
        # **不调 pad_mode()** —— 那个函数发的是「方向键上」，
        # 作用是把游戏切到手柄态，但副作用是会移动菜单的选中项。
        #
        # 代价：Ui.start() 把游戏切成了键鼠态，所以第一次 B 可能被游戏
        # 当成「切换到手柄态」的信号吃掉，要按 2~3 次才真生效。
        # 实测（朋友那边）从主菜单退出去要按 3 次。
        #
        # **这个取舍是有意的**：慢一点 vs 可能移动菜单选中项。
        # B 在任何界面都无副作用，方向键上有。所以选慢。
        try:
            inp.pad_tap("b", wait=1.0)
        except Exception:
            inp.key("esc", wait=1.5)      # 手柄不可用才用 ESC

        # **等画面真的稳了再判**，不要固定睡 0.15 秒就重判 ——
        # 实测界面切换有约 3 秒的过渡画面，期间判出来是「未知界面」。
        # 之前等太短，会在过渡期连按 B，退过头或把按键喂给过渡动画。
        try:
            vs.wait_still(quiet=0.3, timeout=3.0)
        except Exception:
            time.sleep(0.4)
        if _describe_stable(vs, tries=3, gap=0.5) == "世界":
            return True

    return _describe_stable(vs, tries=3, gap=0.2) == "世界"


def _scan_portraits(vs: Vision) -> list[tuple[int, int]]:
    """OCR 读所有「等级N」标签，返回头像中心坐标列表（按 y 再 x 排序）"""
    vs.frame(force=True)
    pts = []
    for it in vs.items(R_GRID):
        if not it["text"].startswith("等级"):
            continue
        x = int(it["cx"])
        y = int(it["cy"]) + AGENT_LABEL_DY

        # **必须夹在屏幕内** —— 实测「等级1」的标签在 y=31，
        # 减掉 AGENT_LABEL_DY(-40) 之后是 y=-9，点到屏幕外去了。
        # 屏幕上沿那一行的角色因此永远点不到
        # （新抽到的低级角色往往就排在那儿 → 「简·杜」就是这么漏的）。
        y = max(4, min(1076, y))
        x = max(4, min(1916, x))
        pts.append((x, y))

    # 去重（夹取后可能产生重复点）
    seen = set()
    uniq = []
    for p in pts:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    uniq.sort(key=lambda p: (p[1], p[0]))
    return uniq


def _select_once(ui: Ui, m: Machine, name: str, verbose: bool) -> bool:
    vs, inp = ui.vs, ui.inp
    if not m.go_to("代理人列表"):
        if verbose:
            print("  到不了代理人列表")
        return False
    vs.frame(force=True)   # go_to 后必须刷新帧再读画面
    if not anchors.is_(vs, "代理人列表"):
        if verbose:
            print("  不在代理人列表页")
        return False

    # 归一化比较：OCR 读出来的可能是繁体/多个空格，裸 == 会误判
    from core.agent_name import lenient_match
    if lenient_match(current_name(vs), name):
        if verbose:
            print(f"  已经是「{name}」")
        return True

    # 1) 先查缓存
    cache = load_cache()
    order: list[tuple[int, int]] = []
    if name in cache:
        order.append(tuple(cache[name]))
    # 2) 再用 OCR 扫出来的实际位置
    for p in _scan_portraits(vs):
        if p not in order:
            order.append(p)

    if verbose:
        print(f"  候选位置 {len(order)} 个")

    for pt in order:
        inp.click(pt[0], pt[1], wait=1.3)
        vs.frame(force=True)
        got = _read_name(vs)
        if not got:
            continue
        if lenient_match(got, name):
            cache[name] = [pt[0], pt[1]]
            save_cache(cache)
            if verbose:
                print(f"  找到「{name}」@ {pt}")
            return True

    # 3) 当前屏没有，滚动再找（实测网格会滚动，第一屏只有 9 个）
    if verbose:
        print("  第一屏没找到，开始滚动")
    for key in (-3, -3, 3, 3):
        inp.wheel(key, wait=1.5)
        vs.frame(force=True)
        if not anchors.is_(vs, "代理人列表"):
            continue
        for pt in _scan_portraits(vs):
            inp.click(pt[0], pt[1], wait=1.3)
            vs.frame(force=True)
            got = _read_name(vs)
            if lenient_match(got, name):
                cache[name] = [pt[0], pt[1]]
                save_cache(cache)
                if verbose:
                    print(f"  滚动后找到「{name}」@ {pt}")
                return True

    if verbose:
        print(f"  没找到「{name}」（滚动了 4 次）")
    return False


def select_agent(ui: Ui, m: Machine, name: str, verbose: bool = True) -> bool:
    """选中指定角色。内部带「退大世界重来」兜底。"""
    if _select_once(ui, m, name, verbose):
        return True
    if verbose:
        print("  第一次没选中，退回大世界重试")
    if not reset_to_world(ui):
        return False
    return _select_once(ui, m, name, verbose)


def set_hide_owned(ui: Ui, m: "Machine", hide: bool) -> bool:
    """把代理人筛选里的「隐藏未拥有」开关设成 hide。

    `hide=True`  → 只看已拥有
    `hide=False` → 显示全部（未拥有的灰掉/带锁）

    ## 开关长什么样（截图量的）

    ```
    代理人筛选
      等级                        [⇅]
      隐藏未拥有        [ ON  ○ ]      ← 绿色药丸 + 圆形滑块
                        ↑
                        点这一带才能切
    底部还有一个「重置」按钮
    ```

    ## 踩过的坑

    只点 `(1800, row_y)` 没反应 —— **那是滑块右边一点，落在按钮外面**。
    现在按「药丸中心附近试几个点」+ 每次读完确认状态。
    """
    vs, inp = ui.vs, ui.inp
    if not m.go_to("代理人筛选"):
        return False
    vs.frame(force=True)

    lbl = vs.find("隐藏未拥有", (1250, 180, 1900, 300))
    if not lbl:
        print("  找不到「隐藏未拥有」")
        return False
    row_y = int(lbl["cy"])

    def read_state() -> str:
        vs.frame(force=True)
        for it in vs.items((1600, row_y - 35, 1920, row_y + 35)):
            t = (it.get("text") or "").strip().upper()
            if t in ("ON", "OFF"):
                return t
        return ""

    want = "ON" if hide else "OFF"
    state = read_state()
    if state == want:
        print(f"  「隐藏未拥有」已经是 {want}")
    else:
        print(f"  「隐藏未拥有」现在 {state or '?'}，要点成 {want}")
        # **在药丸那一带试几个位置** —— 只试一个点会点空（踩过）
        for dx in (1755, 1795, 1730, 1820):
            inp.click(dx, row_y, wait=1.4)
            state = read_state()
            if state == want:
                print(f"    点 ({dx},{row_y}) 成功，现在是 {state}")
                break
            # 点错了方向就再点一次
            if state and state != want:
                continue
        if state != want:
            print(f"    ✘ 试了 4 个位置还是 {state or '?'}")

    # 关掉筛选面板回列表
    inp.key("esc", wait=1.6)
    vs.frame(force=True)
    return state == want


def list_agents(ui: Ui, m: Machine) -> dict[str, str]:
    """扫一遍代理人列表（含滚动），返回 {名字: 等级}"""
    vs, inp = ui.vs, ui.inp
    reset_to_world(ui)
    if not m.go_to("代理人列表"):
        return {}
    out: dict[str, str] = {}

    # **最小改动**：只把「固定 4 轮」换成「没有新角色就停」。
    #
    # 原来 `range(4)` 是硬上限 —— 14 个角色要滚 6~8 轮才到底，4 轮必然漏。
    # 但步长必须保持 `wheel(-3)`：试过改成 -5，行会被跳过（14 → 13 个，丢了波可娜）。
    #
    # 所以：**步长不动（实测 -3 不跳行），只放开轮数上限。**
    # **先滚回顶部** —— 列表是有滚动位置的，如果上次停在中间，
    # 上面的角色永远看不到（截图确认：顶部两行会被切掉）。
    # 这一步是「简·杜」漏掉的直接原因之一。
    for _ in range(12):
        inp.wheel(6, wait=0.5)
    vs.frame(force=True)

    MAX_ROUNDS = 15
    _last_sig = ""
    for round_i in range(MAX_ROUNDS):
        if round_i > 0:
            inp.wheel(-3, wait=1.5)
            vs.frame(force=True)
            if not anchors.is_(vs, "代理人列表"):
                break

        # **画面没变 = 滚到底了**（用网格区域的 OCR 文本当指纹）
        _sig = vs.text(R_GRID)
        if round_i > 0 and _sig == _last_sig:
            break
        _last_sig = _sig

        # **滚到底的判断：画面根本没变**，不是「没有新角色」。
        #
        # 踩过的坑：用「这一轮没新角色就停」会提前退出 ——
        # `wheel(-3)` 滚动时上下两屏重叠很多，第二轮看到的还是同一批人，
        # 于是误判到底（14 个角色扫成 13 个，丢了波可娜）。
        #
        # 正确信号：**滚动前后网格区域的 OCR 文本完全一样** = 真的滚不动了。
        for pt in _scan_portraits(vs):
            inp.click(pt[0], pt[1], wait=1.2)
            vs.frame(force=True)
            nm = _read_name(vs)
            if not nm or nm in out:
                continue
            lv = ""
            for it in vs.items(R_GRID):
                if it["text"].startswith("等级") and abs(it["cx"] - pt[0]) < 60:
                    lv = it["text"]
                    break

            # **只留已拥有的** —— 判据是「`等级N` 左边有没有 S/A 彩色徽章」
            # （用户确认：带锁 = 未解锁，显示 S/A = 已解锁）。
            #
            # 这是「正向检测」：找到彩色徽章就算拥有。
            # 前面试过「看饱和度」「看通道差」都不行 —— 深色系角色和灰的挤在一档，
            # 阈值定不下来。徽章就有没有，界限很清楚（实测 36~43% vs 0%）。
            #
            # **只有明确「没有徽章」才排除**；读不到（None）当拥有处理，
            # 宁可多留一个，也不要把有的角色漏掉。
            try:
                from core import portrait as _pf
                _owned = _pf.is_owned(vs, pt)
                if _owned is False:
                    continue
            except Exception:
                pass

            out[nm] = lv

    # **单字残段过滤** —— OCR 有时只读到名字的最后一个字，
    # 变成一个独立的「角色」（实测：「西」是「露西」的残段，用户确认账号里没有「希格莉德」）。
    #
    # 规则：单字名如果是**另一个已扫到的名字的子串**，就当残段丢掉。
    #        「西」⊂「露西」 → 丢
    #        「简」不在别的名字里 → 保留
    if len(out) > 1:
        names = list(out.keys())
        for nm in names:
            if len(nm) != 1:
                continue
            if any(nm != other and nm in other for other in names):
                out.pop(nm, None)

    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()
    m = Machine(ui, verbose=False)

    if args.list or not args.name:
        roster = list_agents(ui, m)
        print(f"共 {len(roster)} 个角色：")
        for nm, lv in roster.items():
            print(f"  {nm:<8} {lv}")
    else:
        ok = select_agent(ui, m, args.name)
        print(f"选中「{args.name}」: {'✔' if ok else '✖'}  当前={current_name(vs)}")
