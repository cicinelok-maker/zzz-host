# 从这里开始

绝区零的角色养成自动化：**说一个角色名，它自己把能做的都做了**——
读装备、算缺口、升级音擎/技能/等级/核心技、调律训练驱动盘、刷本补材料、换装。

不是库，是命令行程序。所有交互都通过 `python tools/xxx.py` + 文件输出。

---

## 前置条件（缺一个就跑不了）

| 要求 | 说明 |
|---|---|
| Windows | 本工具用 `ImageGrab` + 虚拟手柄，只支持 Windows |
| 游戏分辨率 1920×1080 | 坐标按这个分辨率标定 |
| 游戏窗口化或全屏窗口化 | 独占全屏抓不到画面 |
| OneDragon 已安装 | 提供 OCR 和刷本能力 |
| 管理员权限 | 注入键鼠需要 |

一条命令查全部：

```powershell
python tools/check_config.py
```

**它会告诉你缺什么。** 退出码 0 = 环境齐了；非 0 = 有致命项（缺 `disc_meta.json`、角色没有定位等）。

---

## 五条命令跑通

```powershell
python tools/check_config.py                     # 1 环境
python tools/zzz_launch.py                       # 2 游戏（约 72 秒，没开就自己启动）
python tools/zzz_status.py 佩洛伊斯 --json        # 3 读状态（**必须先做**）
python tools/zzz_disc_daily.py 佩洛伊斯 --offline # 4 出计划（秒出，不碰游戏）
python tools/zzz_daily.py 佩洛伊斯 --run          # 5 真跑
```

第 3 步是必须的：不盘点一次，后面所有工具都读不到数据。

想看账号上有哪些角色：`python tools/zzz_who.py --scan`

---

## 常用命令

```powershell
# 只出计划，不花任何东西（约 1 秒，不碰游戏）
python tools/zzz_daily.py 佩洛伊斯

# 真跑一轮（会花电量和材料）
python tools/zzz_daily.py 佩洛伊斯 --run

# 刷到毕业为止（每轮看进展，没进展就补材料）
python tools/zzz_grind.py 佩洛伊斯 --run

# 看还差多少
python tools/zzz_who.py 佩洛伊斯

# 只做某几步（跳过其他）
python tools/zzz_daily.py 佩洛伊斯 --run --skip wengine,core,disc,farm
```

**不确定会发生什么就跑不带 `--run` 的版本**——所有工具都支持「计划模式」，
计划模式**保证零副作用**（不读游戏、不写文件、不花资源）。

---

## 一定要知道的几件事

**① 退出码有意义**

| 码 | 含义 | 你该做什么 |
|---|---|---|
| 0 | 成功 | — |
| 1 | 一般失败 | 看输出 |
| 2 | 配置错 | 跑 `check_config.py` |
| 3 | 选不中角色 | 确认角色名 |
| 4 | 到不了目标界面 | 游戏可能卡在某个面板 |
| 5 | 找不到游戏窗口 | 启动游戏 |

完整表见 [AGENTS.md](AGENTS.md)。

**② 哪些操作不可逆**

会消耗资源的：`--run`、`zzz_convert.py --confirm`、`run_dismantle.py --run`、
`zzz_disc_cycle.py`。这些工具**不加确认参数就只出计划**，加了才真做。

**③ 数据都在 `state/` 目录**

`status_<角色>.json` 是最重要的中间产物，所有分析都基于它。

---

## 出问题了

1. `python tools/check_config.py` —— 先看环境
2. `python tools/zzz_status.py <角色> --json` —— 看能不能读到数据
3. 卡在某个界面：`python tools/zzz_launch.py --check` 看状态

更多细节见 [AGENTS.md](AGENTS.md)（面向调用方）、
[TOOLS.md](TOOLS.md)（工具清单）、[DISC_LOOP.md](DISC_LOOP.md)（驱动盘养成的原理）。
