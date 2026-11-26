"""状态机：显式定义界面状态与合法转移，按目标自动规划路径。

和 anchors.py 的分工
====================
    anchors.py   只负责「我现在在哪个状态」（识别）
    machine.py   负责「从这个状态怎么走到目标状态」（转移）

为什么需要
==========
之前每个工具都自己写「先按 start 再点仓库再按 RB」，重复且容易漂移。
现在把转移集中定义一次，任何工具只要说「我要到驱动仓库」，机器自己走。

用法
====
    from core.machine import Machine
    m = Machine(ui)
    if m.go_to("驱动仓库"):
        ...
    print(m.describe())      # 当前状态 + 可用转移

设计要点
========
* 每个转移带前置条件（from 状态）和验证（到目标后确认）
* 走错了会被 detect 发现，机器重新规划
* 最多重试 N 轮，失败抛异常交给人/上层处理
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import anchors
from .vision import Region

# ---------- 区域 ----------
R_ALL = (0, 0, 1920, 1080)
R_TITLE = (0, 0, 900, 220)
R_PANEL = (1100, 100, 1910, 1000)
R_DETAIL = (1400, 180, 1910, 960)
R_BOTTOM = (700, 990, 1920, 1080)
R_TABS = (1420, 130, 1780, 210)


@dataclass
class Action:
    """一个原子动作"""
    kind: str                       # click_xy / click_text / press / wheel / template
    arg: str = ""
    xy: tuple[int, int] | None = None
    n: int = 1
    wait: float = 0.5
    region: Region | None = None


@dataclass
class Transition:
    """一次状态转移"""
    src: str
    dst: str
    actions: list[Action] = field(default_factory=list)
    verify: tuple[str, ...] = ()     # 到达后必须出现的文字
    verify_region: Region | None = None
    note: str = ""


# ============ 转移表 ============
# 名字要和 anchors.ANCHORS 里的 name 一致
TRANSITIONS: list[Transition] = [
    # 大世界 → 主菜单
    Transition("世界", "主菜单",
               [Action("key", "esc", wait=2.2)],
               verify=("邮件", "代理人"), verify_region=R_ALL,
               note="START 打开菜单"),

    # ============ 代理人筛选 ============
    # 漏斗在代理人列表右上角，实测 (1662,53)。用 click_xy 而不是 click_text ——
    # 漏斗是图标没有文字。
    Transition("代理人列表", "代理人筛选",
               [Action("click_xy", xy=(1662, 53), wait=2.0)],
               verify=("代理人筛选", "隐藏未拥有"), verify_region=R_ALL,
               note="右上角漏斗图标 @(1662,53)，无文字"),

    Transition("代理人筛选", "代理人列表",
               [Action("key", "esc", wait=1.8)],
               verify=("代理人",), verify_region=R_ALL,
               note="ESC 关闭筛选面板"),

    # ============ 更多功能 / 养成指南 ============
    # 「更多」必须限定在底部图标栏找 —— 全屏找可能命中别处的同名文字
    Transition("主菜单", "更多功能",
               [Action("click_text", "更多", region=(0, 950, 1920, 1080), wait=2.0)],
               verify=("更多功能", "养成指南"), verify_region=R_ALL,
               note="菜单底部图标栏点「更多」@(317,1040)"),

    Transition("更多功能", "养成指南",
               [Action("click_text", "养成指南", region=(0, 0, 1920, 1080), wait=2.5)],
               # **等它加载完** —— 加载中只有一条 'Q'，verify 会失败
               verify=("养成材料计算",), verify_region=R_ALL,
               note="点养成指南 @(1133,474)，加载约 3 秒"),

    # 材料视图 → 方案视图（点左边的「方案概览」或「补充建议」标签）
    Transition("养成指南", "养成指南方案",
               [Action("click_text", "方案概览", region=(120, 100, 470, 420), wait=2.0)],
               verify=("副属性推荐",), verify_region=R_ALL,
               note="左边两个标签：方案概览 / 补充建议。"
                    "点不到「方案概览」时也试「补充建议」（都在同一块）"),

    Transition("养成指南方案", "养成指南",
               [Action("click_text", "养成材料明细", region=(600, 200, 1400, 360), wait=2.0)],
               verify=("养成材料计算",), verify_region=R_ALL,
               note="点回「养成材料明细」标签"),

    # 回程：**只能 ESC** —— 这个全屏面板 B 键无效（实测）
    Transition("养成指南", "更多功能",
               [Action("key", "esc", wait=2.0)],
               verify=("更多功能",), verify_region=R_ALL,
               note="全屏面板只有 ESC 能关，B 无效"),

    Transition("更多功能", "主菜单",
               [Action("key", "esc", wait=1.8)],
               verify=("邮件", "代理人"), verify_region=R_ALL,
               note="ESC 回主菜单"),

    # 主菜单 → 仓库（默认落在音擎页，驱动盘要靠下面的切页转移）
    Transition("主菜单", "音擎仓库",
               # 必须限定在底部图标栏区域内找「仓库」，
               # 全屏找可能命中别处的同名文字（实测点不进去）
               [Action("click_text", "仓库", region=(0, 950, 1920, 1080), wait=2.0)],
               verify=("仓库[",), verify_region=R_TITLE,
               note="菜单底部图标栏点「仓库」"),

    # 仓库内切页（顶部标签）
    Transition("音擎仓库", "驱动仓库",
               [Action("click_template", "标签_驱动盘", xy=(1557, 174), wait=1.4)],
               verify=("驱动仓库[",), verify_region=R_TITLE,
               note="点顶部驱动盘标签"),
    Transition("仓库任意", "驱动仓库",
               [Action("click_xy", xy=(1557, 174), wait=1.4)],
               verify=("驱动仓库[",), verify_region=R_TITLE,
               note="兜底：直接点驱动盘标签"),
    Transition("驱动仓库", "音擎仓库",
               [Action("click_xy", xy=(1450, 174), wait=1.2)],
               verify=("音擎仓库[",), verify_region=R_TITLE),

    # ---------- 音擎的三个新界面（2026-11-24 补） ----------
    Transition("音擎详情", "音擎推荐面板",
               [Action("click_xy", xy=(456, 1028), wait=2.6)],
               verify=("代理人专属",), verify_region=(1000, 20, 1920, 1080),
               note="详情页底部「推荐」"),

    Transition("音擎推荐面板", "音擎详情",
               [Action("key", "esc", wait=1.8)],
               verify=("音擎效果",), verify_region=(400, 120, 1100, 760)),

    Transition("音擎详情", "音擎筛选面板",
               [Action("click_xy", xy=(315, 52), wait=2.4)],
               verify=("音擎筛选",), verify_region=(1000, 20, 1920, 1080),
               note="左上角「筛选」"),

    Transition("音擎筛选面板", "音擎详情",
               [Action("key", "esc", wait=1.8)],
               verify=("音擎效果",), verify_region=(400, 120, 1100, 760)),

    Transition("音擎详情", "音擎回收",
               [Action("click_xy", xy=(1755, 50), wait=2.6)],
               verify=("音擎回收",), verify_region=(0, 0, 900, 140),
               note="右上角「回收」"),

    Transition("音擎回收", "音擎详情",
               [Action("key", "esc", wait=1.8)],
               verify=("音擎效果",), verify_region=(400, 120, 1100, 760)),

    # ---------- 驱动盘拆解页 ----------
    Transition("驱动仓库", "驱动盘拆解页",
               [Action("click_xy", xy=(365, 930), wait=2.6)],
               verify=("驱动盘拆解",), verify_region=(0, 0, 1200, 120),
               note="仓库底部「拆解」按钮"),

    Transition("驱动盘拆解页", "驱动仓库",
               [Action("key", "esc", wait=1.8)],
               verify=("驱动仓库",), verify_region=(0, 120, 700, 220),
               note="ESC 退回仓库"),

    # 拆解页漏斗 (84,1031) → 筛选面板（这个面板有「已弃置」选项）
    Transition("驱动盘拆解页", "驱动盘筛选面板",
               [Action("click_xy", xy=(84, 1031), wait=2.4)],
               verify=("稀有度",), verify_region=(1350, 250, 1920, 700),
               note="拆解页左下角漏斗"),

    # 拆解页 → 智能弃置设置面板
    Transition("驱动盘拆解页", "智能弃置面板",
               [Action("click_xy", xy=(561, 1028), wait=2.6)],
               verify=("智能弃置设置",), verify_region=(0, 0, 1920, 1080),
               note="拆解页底部「智能弃置」"),

    Transition("智能弃置面板", "驱动盘拆解页",
               [Action("key", "esc", wait=1.8)],
               verify=("驱动盘拆解",), verify_region=(0, 0, 1200, 120)),

    Transition("驱动盘筛选面板", "驱动盘拆解页",
               [Action("key", "esc", wait=1.8)],
               verify=("驱动盘拆解",), verify_region=(0, 0, 1200, 120)),

    # 仓库 → 筛选面板
    Transition("驱动仓库", "筛选面板",
               [Action("click_template", "漏斗", xy=(135, 922), wait=1.4)],
               verify=("稀有度",), verify_region=R_PANEL,
               note="点左下角漏斗"),

    # 筛选面板 → 套装网格
    Transition("筛选面板", "套装网格",
               [Action("click_text", "点击选择", region=R_PANEL, wait=1.4)],
               verify=("所选套装",), verify_region=R_PANEL,
               note="「套装」是标题，要点「点击选择」"),

    # 套装网格 → 筛选面板（确认筛选）
    Transition("套装网格", "筛选面板",
               [Action("click_text", "确认筛选", region=R_PANEL, wait=2.0)],
               verify=("驱动仓库[",), verify_region=R_TITLE),

    # 筛选面板 → 仓库（关面板）
    # 实测：按 B 关不掉筛选面板，必须点面板外的空白处
    Transition("筛选面板", "驱动仓库",
               [Action("click_xy", xy=(300, 500), wait=1.4)],
               verify=("驱动仓库[",), verify_region=R_TITLE,
               note="点面板外空白处关闭"),

    # ---------- 代理人 → 装备 → 定制 ----------
    Transition("主菜单", "代理人列表",
               [Action("click_xy", xy=(1249, 980), wait=2.2)],
               verify=("代理人攻略",), verify_region=(0, 0, 1920, 300),
               note="点底部「代理人」图标（点标签无效，要点图标）"),

    Transition("代理人列表", "装备页",
               [Action("click_text", "装备", region=(1000, 950, 1800, 1030), wait=2.0)],
               verify=("基础", "装备"), verify_region=(1000, 950, 1800, 1030),
               note="点底部「装备」标签"),

    Transition("装备页", "驱动盘定制",
               [Action("click_slot", wait=2.0)],
               verify=("驱动盘定制",), verify_region=(0, 0, 1920, 120),
               note="点任一盘位（默认 1 号位）"),

    # 强化面板 → 驱动盘定制（ESC 退出）
    Transition("强化面板", "驱动盘定制",
               [Action("key", "esc", wait=1.8)],
               verify=("驱动盘定制",), verify_region=(0, 0, 1920, 120),
               note="ESC 退出强化面板"),

    # ---------- 技能页 ----------
    # 关键：底部三个标签（基础/技能/装备）只在角色详情页才有，
    # 代理人列表（网格）上没有。所以从装备页直接点「技能」最可靠。
    # ---------- 音擎 ----------
    # 装备页中心 (1345,620) 是音擎圆盘，点开进详情
    Transition("装备页", "音擎详情",
               [Action("click_xy", xy=(1345, 620), wait=2.4)],
               verify=("音擎效果",), verify_region=(400, 450, 1100, 700),
               note="点装备页中心的音擎圆盘"),

    Transition("音擎详情", "装备页",
               [Action("key", "esc", wait=1.8)],
               verify=("DRIVER",), verify_region=(900, 300, 1850, 950),
               note="ESC 退回装备页"),

    # 详情页底部「强化」(1717,1030) → 强化面板；卡上限时按钮在 (1452,842) 变「改装」
    Transition("音擎详情", "音擎强化面板",
               [Action("click_xy", xy=(1717, 1030), wait=3.2),
                Action("click_xy", xy=(1717, 1030), wait=3.2)],
               verify=("自动添加",), verify_region=(1000, 780, 1600, 900),
               note="点强化（可能要点两次）"),

    Transition("音擎强化面板", "音擎详情",
               [Action("key", "esc", wait=1.8)],
               verify=("音擎效果",), verify_region=(400, 450, 1100, 700)),

    # ---------- 代理人培训 ----------
    # 装备页「基础」标签 → 等级徽章右边的绿色 >>> (1355,472)
    Transition("装备页", "代理人培训",
               [Action("click_xy", xy=(1154, 996), wait=2.0),
                Action("click_xy", xy=(1355, 472), wait=2.6)],
               verify=("代理人培训",), verify_region=(300, 200, 1400, 400),
               note="点基础标签，再点等级右边的绿色箭头"),

    Transition("代理人培训", "装备页",
               [Action("key", "esc", wait=1.8)],
               verify=("DRIVER",), verify_region=(900, 300, 1850, 950)),

    # ---------- 基础页 ----------
    # 基础页录了指纹之后成了独立状态，必须给它出口，否则进了出不来
    Transition("基础页", "装备页",
               [Action("click_xy", xy=(1654, 996), wait=2.0)],
               verify=("DRIVER",), verify_region=(900, 300, 1850, 950),
               note="底部点「装备」标签"),

    Transition("基础页", "技能页",
               [Action("click_xy", xy=(1402, 995), wait=2.0)],
               # **原来 verify=("12",)** —— 技能等级那一排数字里到处都有 12
               # （实测 y≈757 是 `1212 / 10 / 12`），而且基础页的暴击率也含 "12.2%"，
               # 所以这个校验**恒真**，等于没有（RT-REPORT 柱 2 点名的就是这类）。
               #
               # 换实测判别词：「影画」在技能页有、基础页没有（实测 False）。
               verify=("影画",), verify_region=(40, 890, 460, 1010),
               note="底部点「技能」标签（验「影画」：技能页有、基础页无）"),

    Transition("技能页", "基础页",
               [Action("click_xy", xy=(1154, 996), wait=2.0)],
               verify=("生命值",), verify_region=(1000, 500, 1400, 800),
               note="底部点「基础」标签"),

    Transition("装备页", "基础页",
               [Action("click_xy", xy=(1154, 996), wait=2.0)],
               verify=("生命值",), verify_region=(1000, 500, 1400, 800)),

    Transition("装备页", "技能页",
               [Action("click_xy", xy=(1402, 995), wait=2.0)],
               verify=("12",), verify_region=(900, 700, 1800, 800),
               note="角色详情页底部点「技能」标签"),

    Transition("技能页", "装备页",
               [Action("click_xy", xy=(1654, 996), wait=2.0)],
               verify=("DRIVER",), verify_region=(900, 300, 1850, 950),
               note="角色详情页底部点「装备」标签"),

    # 注意：代理人列表（网格）上没有底部标签，技能标签只在角色详情页才有。
    # 所以去技能页必须经过装备页。

    Transition("技能页", "技能详情",
               [Action("click_xy", xy=(984, 700), wait=1.8)],
               verify=("简略描述",), verify_region=(0, 0, 1920, 120),
               note="点第一个技能格子"),

    # 技能详情是子页面，返回要点左上角箭头（ESC 会退过头）
    Transition("技能详情", "技能页",
               [Action("click_xy", xy=(120, 52), wait=1.8)],
               verify=("12",), verify_region=(900, 700, 1800, 800),
               note="点左上角返回箭头回技能格子页"),

    # 同上，从网格到技能详情要经过 装备页 → 技能页 → 技能详情

    # 注：技能详情 → 技能强化面板 这条边实测点「技能强化」没反应，
    # 不加。zzz_skill.py 自己走的是另一条路径（点格子→找按钮），是通的。

    # 技能详情的返回箭头只回上一层（技能页），不能直接跳代理人列表。
    # 要去代理人列表走：技能详情→技能页→装备页→代理人列表

    Transition("技能强化面板", "技能详情",
               [Action("key", "esc", wait=1.4)],
               verify=("简略描述",), verify_region=(0, 0, 1920, 120)),

    # ---------- 音像店调律（两条入口）----------
    # 入口一：波浪号开手机 → 点「音像店」→ 直接进调律
    Transition("世界", "调律界面",
               [Action("key", "tilde", wait=2.2),
                Action("click_text", "音像店", region=R_ALL, wait=3.0)],
               verify=("调律×",), verify_region=(0, 900, 1920, 1080),
               note="波浪号开手机 → 点音像店"),

    # 入口二：驱动盘定制页右上角「驱动盘定制」
    Transition("驱动盘定制", "调律界面",
               [Action("click_text", "驱动盘定制", region=(1300, 20, 1920, 90), wait=3.0)],
               verify=("调律×",), verify_region=(0, 900, 1920, 1080),
               note="定制页右上角「驱动盘定制」直通音像店"),

    # 调律结果页 → 调律界面
    Transition("调律结果", "调律界面",
               [Action("key", "esc", wait=1.4)],
               verify=("调律×",), verify_region=(0, 900, 1920, 1080)),

    # 调律界面的 ESC 出口不固定，用循环动作退到世界
    Transition("调律界面", "世界",
               [Action("esc_to_world", n=8, wait=1.5)],
               verify=("快捷轮盘", "相机"), verify_region=(0, 0, 1400, 1080),
               note="循环 ESC 直到大世界"),

    # 主菜单 → 世界（ESC 关菜单）
    Transition("主菜单", "世界",
               [Action("key", "esc", wait=1.8)],
               verify=("快捷轮盘", "相机"), verify_region=(0, 0, 1400, 1080),
               note="ESC 关闭主菜单"),

    # 回退路径：实测左上角返回箭头 (120,52) 才可靠，B 键在这些页面无效
    Transition("驱动盘定制", "装备页",
               [Action("click_xy", xy=(120, 52), wait=1.8)],
               verify=("装备",), verify_region=(1500, 950, 1800, 1040),
               note="点左上角返回箭头"),
    Transition("装备页", "代理人列表",
               [Action("click_xy", xy=(120, 52), wait=1.8)],
               verify=("代理人攻略",), verify_region=(0, 0, 1920, 400),
               note="点左上角返回箭头"),
    Transition("代理人列表", "主菜单",
               [Action("click_xy", xy=(120, 52), wait=2.0)],
               verify=("邮件", "代理人"), verify_region=(0, 950, 1920, 1080),
               note="点左上角返回箭头"),

    # 任意 → 大世界（兜底复位）
    Transition("*", "世界",
               # ESC 是开关：按两次会又打开菜单，所以只按一次，
               # 没到目标就让 go_to 的下一轮重试
               [Action("key", "esc", wait=1.6)],
               verify=("快捷轮盘", "相机"), verify_region=(0, 0, 1400, 1080),
               note="连按 B/ESC 脱离"),
]
class Machine:
    def __init__(self, ui, max_rounds: int = 4, verbose: bool = True):
        self.ui = ui
        self.vs = ui.vs
        self.inp = ui.inp
        self.max_rounds = max_rounds
        self.verbose = verbose
        self.log: list[str] = []
        # **verify 条件与 state 判定不一致的次数**（RT-REPORT 柱 2）。
        # `verify` 原来被直接丢掉，写错了也没人知道
        # （实测 `verify=("12",)` 恒真、`("前往任务目标",)` 恒假）。
        # 记下来，`verbose` 时会打出来。
        self._verify_mismatch = 0
        self._verify_log: list[tuple] = []

    # ---------- 状态 ----------
    def state(self) -> str:
        """当前界面。

        必须走 anchors.describe()——它是「指纹优先、文字锚点兜底」。
        直接调 anchors.detect() 会绕开指纹，导致父子页面误判，
        进而让所有转移的「状态验证」失败（这次导航卡死的元凶）。
        """
        name = anchors.describe(self.vs)
        return "未知" if name == "未知界面" else name

    def describe(self) -> str:
        cur = self.state()
        outs = [t.dst for t in TRANSITIONS if t.src == cur or t.src == "*"]
        return f"当前状态：{cur}｜可前往：{sorted(set(outs))}"

    # ---------- 动作执行 ----------
    def _do(self, a: Action) -> bool:
        k = a.kind
        if k == "click_xy":
            if not a.xy:
                return False
            self.inp.click(a.xy[0], a.xy[1], wait=a.wait)
        elif k == "click_text":
            if a.region is None:
                # **不能静默 False** —— 实测这个坑查了很久：
                # 日志只打「动作失败：click_text 养成指南 None」，
                # 看着像「找不到文字」，实际是「压根没让它找」。
                print("      [machine] click_text 缺 region，动作作废")
                return False
            # 先刷帧再找 —— find 内部会读帧，而 Vision 的 OCR 有 0.35s TTL 缓存。
            # 上一步动作刚点完的话，这里读到的可能是旧帧。
            self.vs.frame(force=True)
            hit = self.vs.find(a.arg, a.region)
            if not hit:
                return False
            self.inp.click(hit["cx"], hit["cy"], wait=a.wait)
        elif k == "press":
            if a.n > 1:
                self.inp.pad_taps(a.arg, a.n, wait=a.wait)
            else:
                self.inp.pad_tap(a.arg, wait=a.wait)
        elif k == "wheel":
            self.inp.wheel(-a.n, wait=a.wait)
        elif k == "mouse_mode":
            self.inp.mouse_mode(wait=a.wait)
        elif k == "key":
            self.inp.key(a.arg, wait=a.wait)
        elif k == "esc_to_world":
            # 一路 ESC 退到大世界。层数不固定（各页面的出口不一样），
            # 所以循环到认出「世界」为止，最多 8 次。
            for _ in range(a.n or 8):
                self.vs.frame(force=True)
                if self.state() == "世界":
                    return True
                self.inp.key("esc", wait=a.wait or 1.5)
            return self.state() == "世界"
        elif k == "click_slot":
            # 装备页盘位：优先找「等级xx/xx」标签（图标在标签上方约 60px）；
            # 空盘位没有标签，最后退回环形固定坐标
            from .slots import slot_xy
            FIXED = {1: (1253, 339), 2: (1150, 560), 3: (1252, 782),
                     4: (1570, 783), 5: (1675, 561), 6: (1571, 339)}
            xy = slot_xy(self.vs, a.n or 1)
            if xy is None:
                labels = [i for i in self.vs.items((900, 300, 1850, 950))
                          if "等级" in i["text"]]
                xy = ((labels[0]["cx"], labels[0]["cy"] - 62)
                      if labels else FIXED.get(a.n or 1))
            if not xy:
                return False
            self.inp.click(xy[0], xy[1], wait=a.wait)
        elif k == "click_template":
            ok = self.ui_click_template(a)
            if not ok:
                return False
        elif k == "template":
            hit = self.vs.template(a.arg, a.region)
            if not hit:
                return False
            self.inp.click(hit[0], hit[1], wait=a.wait)
        else:
            return False
        return True

    def ui_click_template(self, a: Action) -> bool:
        hit = self.vs.template_at(a.arg, pad=40)
        if hit:
            self.inp.click(hit[0], hit[1], wait=a.wait)
            return True
        if a.xy:      # 兜底坐标
            self.inp.click(a.xy[0], a.xy[1], wait=a.wait)
            return True
        return False

    def run(self, tr: Transition) -> bool:
        if self.verbose:
            print(f"  → {tr.src}→{tr.dst}  ({tr.note})")
        for a in tr.actions:
            ok = self._do(a)
            if not ok and self.verbose:
                print(f"      动作失败：{a.kind} {a.arg} {a.xy}")
        # 验证：先看指定文字，再确认状态真的变成了目标状态。
        # 只看文字不够——比如技能详情页和代理人列表页都有「代理人攻略」，
        # 光查文字会误判成已经到位。
        ok = True
        if tr.verify and tr.verify_region:
            ok = self.vs.wait_for(tr.verify_region, *tr.verify, timeout=8.0)
            if self.verbose:
                print(f"     验证文字 {'✔' if ok else '✖'} {tr.verify}")
        if tr.dst not in ("*",):
            # 先等画面稳定再判状态——过渡动画中途读到的是混合画面，
            # 会把刚进仓库认成「装备页」之类的鬼状态
            try:
                self.vs.wait_still(quiet=0.25, timeout=4.0)
            except Exception:
                pass
            self.vs.frame(force=True)
            real = self.state()
            if real == tr.dst:
                # 状态对就算成功。文字验证可能因 OCR 抖动失败，
                # 但页面确实到了，不应该判失败（实测踩过这个坑）
                #
                # **但分歧要记下来**（RT-REPORT 柱 2）：原来文字验证的结果
                # 在这里被直接丢掉，于是「verify 层」等于不存在 ——
                # 写错了也没人知道（比如 `verify=("12",)` 恒真、`("前往任务目标",)` 恒假）。
                if not ok:
                    self._verify_mismatch += 1
                    if self.verbose:
                        print(f"     ⚠ 文字验证没过但状态对"
                              f"（{tr.verify}）—— 这个 verify 条件可能写错了")
                    log_fail = getattr(self, "_verify_log", None)
                    if log_fail is not None:
                        log_fail.append((tr.src, tr.dst, tr.verify))
                return True
            if self.verbose:
                print(f"     验证状态 ✖ 期望 {tr.dst}，实际 {real}")
            return False
        return ok

    # ---------- 路径规划 ----------
    def _path(self, src: str, dst: str) -> list[Transition] | None:
        """BFS 找最短转移路径"""
        from collections import deque
        if src == dst:
            return []
        q = deque([[ ]])
        seen = {src}
        while q:
            path = q.popleft()
            cur = src if not path else path[-1].dst
            for tr in TRANSITIONS:
                if tr.src not in (cur, "*"):
                    continue
                if tr.dst in seen and tr.dst != dst:
                    continue
                np_ = path + [tr]
                if tr.dst == dst:
                    return np_
                if tr.dst not in seen:
                    seen.add(tr.dst)
                    q.append(np_)
        return None
    def _at(self, target: str, tries: int = 2) -> bool:
        """**稳定确认**：连续 tries 帧都认成 target 才算到。

        为什么要这个（实测 2026-11-26）：
        连续切换标签时，`go_to('技能页')` 有一次 **2.5 秒就返回 True，
        但画面还停在基础页**。一次点击+验证要 2 秒，所以不是「没生效」——
        是**过渡帧上 `describe()` 瞬时命中了目标页面**，
        而 `go_to` 单帧判定就打了勾。

        和 `reset_to_world` 当初一个毛病：单帧可能是动画中间态。
        """
        # **多数决**，不是「全部都要对」。
        #
        # 第一版写成「连续 2 帧都认成 target 才算」，实测**太严**：
        # OCR 对同一个页面会间歇性漏词（比如技能页的「影画」偶尔读不出），
        # 于是真到了技能页也判 False。
        #
        # 现在取 3 帧，**至少 2 帧**认成 target 才算。
        # 这既能挡掉「过渡帧瞬时命中」，又不会因为一次 OCR 抖动判失败。
        hits = 0
        for k in range(3):
            self.vs.frame(force=True)
            if self.state() == target:
                hits += 1
            if k < 2:
                time.sleep(0.12)
        return hits >= max(2, tries)

    def go_to(self, target: str) -> bool:
        """从当前状态走到目标状态，自动规划并执行。"""
        for rnd in range(self.max_rounds):
            cur = self.state()
            if cur == "未知":
                if self.verbose:
                    print("  [machine] 状态未知，先复位")
                self.recover()
                cur = self.state()
            if cur == target and self._at(target):
                return True
            path = self._path(cur, target)
            if not path:
                if self.verbose:
                    print(f"  [machine] 没有从「{cur}」到「{target}」的路径")
                return False
            if self.verbose:
                print(f"  [machine] {cur} → {target}：共 {len(path)} 步")
            for tr in path:
                ok = self.run(tr)
                if not ok:
                    break       # 重新规划
            if self._at(target):
                return True
            if self.verbose:
                print(f"  [machine] 第 {rnd + 1} 轮没到，重试")
        return self._at(target)

    def recover(self) -> bool:
        """无脑回大世界"""
        tr = next((t for t in TRANSITIONS if t.src == "*" and t.dst == "世界"), None)
        if not tr:
            return False
        self.run(tr)
        return self.state() == "世界"