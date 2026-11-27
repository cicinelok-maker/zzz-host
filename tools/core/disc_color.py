"""用游戏自己标的颜色判断有效副词条。

## 用户 2026-11-24 指出

「在驱动盘装备页面你能看副词条是不是橙色，是的话就是有效副词条」

## 实测：实际是蓝色，不是橙色

在定制页采样的真实 RGB：

    攻击力+2    （有效）  38,160,233   ← 蓝
    暴击伤害+1  （有效）  37,158,230   ← 蓝
    穿透值      （次选）  233,233,233  ← 白
    防御力+1    （无效）  204,224,236  ← 白

所以判定规则：
    蓝：R < 100 且 G 在 120~200 且 B > 190       → 肯定是有效词条
    白：R,G,B 三个值接近（max-min < 40）          → 普通/无效
    橙：R > 180 且 G 在 100~180 且 B < 120        → 有可能在别的界面是橙

## 为什么这个比算词条名更可靠

我原来的做法：读词条名 → 查「有效副词条」配置表 → 判断。
问题：
1. 配置表是人写的，可能和游戏认定的不一样
2. OCR 会把「攻击力百分比」读成「攻击力」
3. 不同角色配置不同，要维护一堆表

用颜色判断：
- 游戏按「当前角色的推荐」着色，天然正确
- 不受 OCR 文字错误影响
- 不需要维护角色配置表

## 注意

只在**定制页/装备页的详情区**有颜色。
仓库列表、拆解页不显示颜色（那里只显示等级）。

## 局限

颜色只告诉你「这条是否有效」，**不告诉你是不是次选**。
次选（如穿透值）显示为白色，和「完全无效」一样。
所以：
    有效词条数 = 蓝色条的个数（这是最硬的指标）
    口径B 的分数仍然需要词条名 + roll 数
两者配合用：颜色定「是否有用」，OCR 定「具体是什么、升了几次」。
"""
from __future__ import annotations

import numpy as np

# 采样参数：文字中心附近的一个扁矩形
SUBS_HW = 70     # 半宽
SUBS_HH = 14     # 半高


def sample_text_color(vs, cx: int, cy: int,
                      hw: int = SUBS_HW, hh: int = SUBS_HH):
    """取一个文字块里「笔画」的平均颜色。

    做法：把区域所有像素按亮度排序，只取最亮的那 45%（笔画），
    排除深色背景。返回 (r, g, b) 或 None。
    """
    img = vs.crop((cx - hw, cy - hh, cx + hw, cy + hh))
    if img is None:
        return None
    a = np.asarray(img).astype(np.int32)
    if a.ndim != 3:
        return None
    flat = a.reshape(-1, 3)
    lum = flat.sum(axis=1)
    if lum.size == 0:
        return None
    # 用「最亮像素的 55%」当阈值——文字笔画是最亮的，
    # 用百分位会混进大量中间调，平均出来就变灰了（实测踩过）。
    thr = lum.max() * 0.55
    bright = flat[lum >= thr]
    if bright.size == 0:
        return None
    return tuple(bright.mean(axis=0))


def classify_color(rgb) -> str:
    """把颜色归类：blue（有效）/ orange / white（普通）/ unknown。

    实测样本：
        有效  38,160,233 / 37,158,230
        无效  233,233,233 / 204,224,236
    """
    if rgb is None:
        return "unknown"
    r, g, b = rgb
    # 蓝：蓝明显高于红，且绿在中间
    if r < 110 and 110 <= g <= 215 and b > 185:
        return "blue"
    # 橙：红高于绿高于蓝
    if r > 175 and 95 <= g <= 185 and b < 130:
        return "orange"
    # 白/灰：三通道接近
    if max(r, g, b) - min(r, g, b) < 45:
        return "white"
    return "unknown"


def read_sub_colors(vs, items):
    """从定制页/装备页读出每条副词条的颜色。

    返回 [{text, color, cx, cy}]，只含副属性区域的行。

    ## 去掉了死形参 `region`（BUG-061）

    原来签名是 `read_sub_colors(vs, items, region=(400, 100, 1100, 1000))`，
    但函数体**从头到尾没用过它** —— 它是靠 `items` 里「副属性」这两个字
    判断从哪里开始、到「套装效果」结束的。

    留着这个参数会让人以为「传不同的 region 能改读取范围」，
    实际传什么结果都一样。
    """
    out = []
    started = False
    for it in items:
        t = it.get("text", "")
        if "副属性" in t:
            started = True
            continue
        if "套装效果" in t:
            break
        if not started:
            continue
        rgb = sample_text_color(vs, it["cx"], it["cy"])
        out.append({"text": t, "color": classify_color(rgb),
                    "rgb": rgb, "cx": it["cx"], "cy": it["cy"]})
    return out


def report(vs, region=(400, 100, 1100, 1000)) -> dict:
    """综合报告：蓝色条数 + 明细。"""
    items = vs.items(region)
    rows = read_sub_colors(vs, items)
    eff_names = [r["text"] for r in rows if r["color"] == "blue"]
    return {
        "蓝色条数": len(eff_names),
        "有效条目": eff_names,
        "明细": rows,
    }