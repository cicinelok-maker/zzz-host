"""界面锚点：用「必须有这些文字」判定当前处于哪个界面。

为什么需要
==========
之前多次出现「以为在仓库，其实在商城」这类假成功。
根因是只看了某个特征就去动作，没有校验整体状态。

本模块给每个界面定义一组**必须同时存在**的文字锚点，
缺任何一个都不认这个状态。
"""
from __future__ import annotations

from dataclasses import dataclass

from .vision import Region

# ---------- 常用区域 ----------
R_TITLE = (0, 0, 900, 220)            # 左上角标题（含仓库计数）
R_GRID = (100, 250, 1400, 900)        # 网格区域
R_DETAIL = (1400, 180, 1910, 960)     # 右侧详情面板
R_PANEL = (1100, 100, 1910, 1000)     # 筛选面板
R_BOTTOM = (700, 990, 1920, 1080)     # 底部按钮提示
R_MENUBAR = (0, 950, 1920, 1080)      # 主菜单底部图标栏（标签在 y≈1035）
R_FULL_LEFT = (0, 0, 1400, 1080)
# 大世界左下角：Tab 快捷轮盘 + 相机 常驻（不受任务状态影响）
R_BOTTOM_LEFT = (0, 940, 620, 1080)
# 快捷手册页签栏（大世界按 F2 打开）。y≈180，五个页签横排
R_COMPENDIUM_TAB = (700, 140, 1680, 230)


@dataclass
class Anchor:
    """一个界面的判定条件"""
    name: str
    region: Region                   # 检查区域
    must: tuple[str, ...] = ()       # 必须同时存在的关键词
    forbidden: tuple[str, ...] = ()  # 出现任何一个就否定
    note: str = ""

    def match(self, vision) -> bool:
        txt = vision.text(self.region)
        if any(f in txt for f in self.forbidden):
            return False
        return all(m in txt for m in self.must)


# ---------- 已知界面 ----------
ANCHORS: list[Anchor] = [
    # ===== 排序原则：子界面 / 更具体的状态排在前面 =====
    # 否则父界面的锚点会抢先命中，状态就永远停在父界面。
    Anchor("驱动盘定制", (0, 0, 1920, 120), must=("驱动盘定制",),
           note="从装备页点盘位进入"),

    Anchor("强化面板", (0, 200, 1920, 1000), must=("阶段添加", "升级")),

    Anchor("技能详情", (0, 0, 1920, 120), must=("简略描述",),
           note="单个技能的详情页（有简略描述/描述/属性）"),

    Anchor("技能强化面板", (400, 130, 1200, 220), must=("技能强化",),
           note="技能升级确认面板（显示等级N→M和材料）"),

    Anchor("调律界面", (0, 900, 1920, 1080), must=("调律×",),
           forbidden=("调律获得",),
           note="音像店调律主界面（底部有调律×01/×10）"),

    Anchor("调律结果", (0, 0, 1920, 500), must=("调律获得",),
           note="调律产出结果页"),

    # 代理人列表与装备页顶部都显示「代理人攻略」，
    # 区别在于装备页有音擎槽（DRIVER 字样）。所以：
    #   代理人列表 = 有代理人攻略 且 无 DRIVER
    #   装备页     = 环形区有「等级N」标签（DRIVER 可有）
    # 代理人详情/技能详情页顶部也有「代理人攻略」，
    # 所以要用它们独有的底部按钮（培养建议/操作教学/技能强化）来排除
    # 排除词必须在锚点区域内才有效！
    # 「简略描述」在 (300,50)，落在 (0,0,1920,400) 内；
    # 而「培养建议」在 y≈1000，区域外，写了也没用。
    Anchor("代理人列表", (0, 0, 1920, 400), must=("代理人攻略",),
           forbidden=("DRIVER", "驱动盘定制", "简略描述"),
           note="代理人选择网格"),

    # 注意：不能只靠「等级」标签——没装驱动盘的角色（比如猫又）环形区没有标签。
    # DRIVER 是音擎槽的固定标签，任何角色都有。
    Anchor("装备页", (900, 300, 1850, 950), must=("DRIVER",),
           forbidden=("驱动盘定制", "仓库["),
           note="装备 tab：环形区有 DRIVER 标签（音擎槽）"),

    Anchor("套装网格", R_PANEL, must=("选择",),
           forbidden=("稀有度", "驱动盘定制"),
           note="筛选里的套装弹窗（盖住了筛选面板）"),

    Anchor("筛选面板", R_PANEL, must=("稀有度",),
           forbidden=("驱动盘定制", "所选套装")),

    Anchor("驱动仓库", R_TITLE, must=("驱动仓库[",), forbidden=("稀有度",),
           note="驱动盘仓库列表（无筛选面板时）"),

    Anchor("音擎仓库", R_TITLE, must=("音擎仓库[",), forbidden=("稀有度",)),

    Anchor("主菜单", R_MENUBAR, must=("邮件", "成就", "绳网", "仓库"),
           note="底部图标栏（标签在 y≈1035，区域必须覆盖到）"),

    Anchor("战斗结果", (0, 0, 1920, 600), must=("挑战结果",)),

    # 大世界：必须用**常驻**文字。
    # 原来用「前往任务目标」（左上角任务指引）—— 那行字只有追踪任务时才出现，
    # 任务做完就消失，大世界会判成「未知界面」，整条导航链退化成超时等待。
    # 现在用左下角常驻的「快捷轮盘」+「相机」：
    #   快捷轮盘 (174,1035)
    #   相机     (129,979)
    # 两个都要求命中，单字容易被别的界面偶合。
    # 快捷手册：大世界按 F2 打开。
    # **只用页签栏，不用页内内容** —— 页里的字（特训目标等）会随页签切换消失，
    # 拿它当判据就是「前往任务目标」那个坑的第二次。
    Anchor("快捷手册", R_COMPENDIUM_TAB, must=("日常", "训练", "作战", "战术"),
           note="大世界按 F2；判据是五个页签里的四个（不含「目标」，那个词到处都有）"),

    Anchor("世界", R_BOTTOM_LEFT, must=("快捷轮盘", "相机"),
           note="大世界，左下角常驻快捷键提示（不用任务指引，它会消失）"),
]


def detect_by_fingerprint(vision) -> str | None:
    """用界面指纹判定（比文字锚点可靠：靠区分度打分，不是命中一个词就认）。"""
    try:
        from . import fingerprint as fp
        data = fp.load()
        if not data:
            return None
        name, score, ok = fp.detect(vision, data)
        return name if ok else None
    except Exception:
        return None


def detect(vision, candidates: list[Anchor] | None = None) -> Anchor | None:
    """返回第一个匹配上的界面锚点。顺序即优先级。"""
    for a in (candidates or ANCHORS):
        try:
            if a.match(vision):
                return a
        except Exception:
            continue
    return None


def is_(vision, name: str) -> bool:
    """先按指纹判，指纹不可信再按文字锚点。"""
    fp_name = detect_by_fingerprint(vision)
    if fp_name:
        return fp_name == name
    for a in ANCHORS:
        if a.name == name:
            return a.match(vision)
    return False


def wait(vision, name: str, timeout: float = 10.0) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if is_(vision, name):
            return True
        time.sleep(0.15)
    return False


def describe(vision) -> str:
    """优先用指纹判定，指纹不可信时退回文字锚点。"""
    fp_name = detect_by_fingerprint(vision)
    if fp_name:
        return fp_name
    a = detect(vision)
    return a.name if a else "未知界面"