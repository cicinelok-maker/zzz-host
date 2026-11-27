"""读养成指南的「攻略方案」—— 主属性/副属性/音擎/技能/队伍建议。

## 重大发现（2026-11-26，用户提示换角色时撞见的）

养成指南**不只有材料表**，左边还有两个标签页：

```
方案概览       ← 推荐方案
补充建议       ← 文字建议（这一屏就是）
```

**「补充建议」这一屏直接给出了我一直说「游戏里没有」的东西：**

```
主属性        火属性伤害加成 / 攻击力
副属性推荐    暴击率 / 暴击伤害 / 攻击力百分比      ← 有效副词条！
音擎推荐      硫磺石 / 加农转子                     ← 音擎推荐！
技能推荐      07 / 12 / 12 / 12 / 08 / 08           ← 技能加点优先级！
推荐队伍      5 人配队
补充建议      「11号常规双暴流，不过由于携带专武会比较缺暴击率，
               因此4号驱动盘建议带暴击盘，只有当暴击率面板≥70%时
               才考虑换成暴伤盘…」
```

## 为什么这是整个项目最大的转折

我一直在 `disc_meta.json` 里手维护「有效副词条 / 主词条 / 套装」
（64 个角色，50 个没核对过），**而且一直说这块「只能靠攻略知识，游戏里没有」。**

**错了。游戏里全都有，而且是官方写的。**

所以 `disc_meta` 的这部分数据可以**整体退役** —— 从游戏读，永远是当前版本的。

## 这一屏能读到的结构化字段

```
主属性        第 4/5/6 号位分别推荐什么
副属性推荐    哪些副词条有效（= 有效副词条）
音擎推荐      专属音擎 + 平替
技能推荐      6 个技能图标各自的目标等级（数字）
补充建议      一段自然语言说明
```

## 限制

· 只在「有攻略方案的角色」上有（前瞻/UP/热门角色）
· 技能推荐是「图标 + 数字」，图标没有文字，只能读数字序列
· 主属性那几行是「主属性 N: 词条名」，数字是位号
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, anchors  # noqa: E402


def open_plan_tab(ui: Ui) -> bool:
    """切到「方案概览」/「补充建议」那一侧（左边那两个按钮）。"""
    vs, inp = ui.vs, ui.inp
    vs.frame(force=True)
    for label in ("补充建议", "方案概览"):
        hit = vs.find(label, (120, 100, 460, 400))
        if hit:
            inp.click(hit["cx"], hit["cy"], wait=2.0)
            try:
                vs.wait_still(quiet=0.4, timeout=2.5)
            except Exception:
                pass
            vs.frame(force=True)
            return True
    return False


def read_plan(ui: Ui) -> dict:
    """读当前「补充建议」屏的攻略数据。

    ## 坐标（实测这一屏的 OCR，2026-11-26）

    ```
    y=132 x=778   '火属性伤害加成'      主属性①的值（标签在 y=133 x=579，OCR 读成「曰王属性」）
    y=186 x=580   '⑤ 主属性'            主属性②的行（图标被读成 ⑤）
    y=186 x=728   '攻击力'
    y=286 x=749   '暴击率>'            副属性推荐
    y=284 x=896   '暴击伤害'
    y=286 x=1098  '攻击力百分比'
    y=299 x=1421  '硫磺石'             ← 音擎名跟副属**同一行**！
    y=298 x=1620  '加农转子'           ← 所以必须靠 x 分左右
    y=407 x=1351  '技能推荐'
    y=558 x=1358  '07'  x=1477 '12'
    y=671 x=1473  '08'  x=1588 '08'
    ```

    **关键：右边那块（音擎/技能推荐）x > 1300，左边（主/副属性）x < 1300。**
    原来只按 y 分区域，把音擎名当成副属性了。
    """
    vs = ui.vs
    vs.frame(force=True)
    items = vs.items((0, 0, 1920, 1080))

    def txt(it) -> str:
        return (it.get("text") or "").strip()

    def cx(it) -> int:
        return int(it.get("cx") or 0)

    def cy(it) -> int:
        return int(it.get("cy") or 0)

    out: dict = {"主属性": [], "副属性": [], "音擎": [], "技能等级": [],
                 "建议": ""}

    LEFT_MAX = 1300
    SKIP = {"主属性", "副属性推荐", "音擎推荐", "技能推荐", "推荐队伍",
            "方案概览", "补充建议", "养成指南"}

    # ---------- 副属性推荐：以「副属性推荐」标签那一行为准，只取左边的 ----------
    for it in items:
        if "副属性推荐" in txt(it):
            y = cy(it)
            row = [x for x in items
                   if abs(cy(x) - y) <= 22 and cx(x) > cx(it) + 30 and cx(x) < LEFT_MAX]
            row.sort(key=cx)
            for x in row:
                v = txt(x).rstrip(">＞").strip()
                if v and v not in SKIP and v not in out["副属性"]:
                    out["副属性"].append(v)
            break

    # ---------- 主属性：从顶部到 250 之间、左边、不是标签也不是副属性 ----------
    for it in items:
        y, x = cy(it), cx(it)
        if not (100 <= y <= 250) or not (600 <= x < LEFT_MAX):
            continue
        v = txt(it)
        if not v or any(k in v for k in SKIP):
            continue
        # 去掉前缀图标字符（「⑤ 主属性」里的 ⑤、以及 OCR 读错的「曰王属性」）
        v = re.sub(r"^[^\u4e00-\u9fa5]+", "", v).strip()
        v = v.replace("主属性", "").strip()
        if not v or v in out["主属性"]:
            continue
        out["主属性"].append(v)

    # ---------- 音擎推荐：y 在 250~380、x > 1350 ----------
    for it in items:
        y, x = cy(it), cx(it)
        if 250 <= y <= 380 and x > 1350:
            v = txt(it)
            if v and v not in SKIP and re.fullmatch(r"[\u4e00-\u9fa5·]{2,10}", v):
                if v not in out["音擎"]:
                    out["音擎"].append(v)

    # ---------- 技能推荐：y 在 420~780、x > 1300、两位数字 ----------
    nums = []
    for it in items:
        y, x = cy(it), cx(it)
        if 420 <= y <= 800 and x > 1300:
            v = txt(it)
            if re.fullmatch(r"\d{1,2}", v):
                nums.append((y, x, int(v)))
    nums.sort()
    out["技能等级"] = [n[2] for n in nums]

    # ---------- 补充建议正文 ----------
    long_texts = [it for it in items if len(txt(it)) >= 20]
    long_texts.sort(key=cy)
    out["建议"] = "".join(txt(it) for it in long_texts)[:600]

    return out


def main() -> int:
    # **先解析参数，再碰任何东西**（安全闸）。
    #
    # 原来这个工具**没有 argparse** —— 命令行传 `--help` 会被完全无视，
    # 然后它照常往下走：`Vision()` → `Input()` → `ui.start()` → 开始点游戏。
    # 也就是说「我只是想看看帮助」会变成「它动我的号」。
    #
    # 更糟的是它自己的重试循环：打开养成指南 → 某步失败 →
    # `reset_to_world()` 按 ESC 关掉 → 再来一遍。看起来就是
    # 「一直点开又关上」，而且只有 Alt+F4 游戏才能停。
    #
    # 现在：`argparse` 放在**第一行**，`--help` 在这里就退出，
    # 下面的 `Vision()/Input()/Ui()` 一行都不会执行。
    import argparse as _argparse
    _argparse.ArgumentParser(
        description="读养成指南的养成方案（**会点游戏**，加 --help 只看说明，不会动）"
    ).parse_args()

    import json
    import time

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()

    # 进养成指南
    try:
        import zzz_guide
    except Exception as e:
        print(f"导入 zzz_guide 失败：{e}")
        return 2
    if not zzz_guide.open_guide(ui):
        print("进不去养成指南")
        return 3

    if not open_plan_tab(ui):
        print("找不到「方案概览 / 补充建议」标签")
        return 4

    d = read_plan(ui)
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
