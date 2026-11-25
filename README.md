# ZZZ 角色养成托管

> 绝区零（Zenless Zone Zero）的**驱动盘 / 材料 / 电量**自动养成助手。
> 指定一个角色，每天自动上号看它缺什么，把电量花在刀刃上，直到养成完成。

---

## ⚠️ 前置依赖：必须装 OneDragon

**本项目不能单独运行。** 它建立在 [OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon) 之上。

| 功能 | 谁提供 |
|---|---|
| 识别游戏画面（OCR） | **OneDragon**（`OnnxOcrMatcher`） |
| 自动战斗刷本 | **OneDragon**（`ZzzContext` + 电量计划） |
| 截图 | 本项目（纯 Win32 + PIL） |

### 边界：本项目**不做**游戏日常

| 你想要的 | 谁做 |
|---|---|
| **角色养成**（驱动盘 / 技能 / 等级 / 音擎） | **本项目** |
| 邮件 / 每日签到 / 活跃度奖励 | OneDragon 自己的「游戏日常」应用组 |
| 丽都城募 / 丽都周纪 / 咖啡店 | 同上 |
| 录像店营业 / 锄大地 | 同上 |

**验证到哪一步了？** 见 [VERIFIED.md](VERIFIED.md) —— 老实列了哪些状态验过、哪些没验。

**这两件事互不相关。** 本项目只读「角色的装备和面板」，不碰签到邮件那些。
想跑游戏日常，直接用 OneDragon 本体的应用组，别经过本项目。

> 早期文档把 `zzz_daily.py` 叫「完整日常」，容易和 OneDragon 的游戏日常混淆。
> 现在统一叫「**角色养成一轮**」——它做的是音擎→等级→材料转化→技能→
> 核心技→刷本→驱动盘→训练回收，全程围绕**一个角色**。
| 鼠标键盘输入 | 本项目（Win32 SendInput） |
| 状态机导航 | 本项目 |
| 驱动盘判断 / 养成规划 / 电量分配 | **本项目** |

**没装 OneDragon 会直接报错**，`vision.py` 会提示你怎么装。

### 装 OneDragon

1. 从 [Releases](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/releases)
   下载**完整包**（`ZenlessZoneZero-OneDragon-vX.X.X-Full.zip`，不是源码包）
2. 解压到任意目录，例如 `E:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full`
3. **先跑一次它的 GUI**，确认能连上游戏、能刷本
4. 把它记下来，填进 `paths.json`

> 完整包自带 `.venv\Scripts\python.exe` 和 OCR 模型，不需要另装。

**版本要求**：需要包含 `one_dragon.base.matcher.ocr.onnx_ocr_matcher` 的版本（v2.x 都有）。
`check_config.py` 会实测这个模块能不能加载。

---

## 它解决什么

绝区零的养成有 6 个系统（音擎 / 等级 / 技能 / 核心技 / 驱动盘 / 调律），
每个系统都有材料、进度、优先级。手动玩很容易：

- **不知道先升哪个**：材料有限，升错了浪费
- **驱动盘看不懂**：主词条 / 副词条 / roll 次数 / 4+2 套装 / 毕业标准
- **电量乱花**：240 点该刷哪个本
- **换了角色从头再来**：配置和判断全要重学

这个项目把这些变成**可执行、可验证**的流程。

---

## 核心能力

### 一、驱动盘判断（最复杂的一块）

| 能力 | 说明 |
|---|---|
| **主词条校验** | 5 号位出「火属性伤害」但角色是以太 → 判定无效，优先级高于副词条 |
| **副词条评分** | 按角色权重算有效词条（口径：存在 1 分 + 每 roll 1 分） |
| **roll 反推** | 从显示数值反推升了几次（如暴击伤害 24% ÷ 4.8% = 5 次） |
| **升级潜力** | 3 条副词条的盘要扣掉解锁第 4 条那一次 |
| **4+2 套装** | 主套必须恰好 4 件，副套 2 件，位号不固定 |
| **颜色判有效** | 游戏按角色标蓝有效词条，直接采 RGB 判断 |

**毕业标准**（社区通用，已核对）：

```
小毕业   28 条   565444（1/2/3 号位任选其一六词条）
实战够用 32 条
大毕业   37 条   7+7+7+5+6+5
```

### 二、每日养成闭环

```
① 盘点     读 6 个位号状态 + 资源
② 找缺口   主词条错 > 空位 > 弱位号
③ 电量规划  距满多久 / 够刷几次
④ 刷本     按缺口选副本（不是固定刷一个）
⑤ 养成     音擎 → 等级 → 转化 → 技能 → 核心技 → 盘训练 → 换装 → 回收
⑥ 记账     今天涨了多少，存档看趋势
```

一条命令跑完：

```bash
python tools/zzz_daily.py 佩洛伊斯 --run
```

### 三、能自己启动游戏

```bash
python tools/zzz_launch.py
# → 开客户端 → 等窗口 → 点「进入游戏」→ 到世界（实测 72 秒）
```

---

## 快速开始

```bash
# 0 先装 OneDragon（见上面「前置依赖」）

# 1 拿本项目
git clone <本项目地址> zzz-host && cd zzz-host

# 2 配置路径
copy paths.example.json paths.json
# 编辑 paths.json：one_dragon_home / game_exe

# 3 验证（会实测 OCR 模块能不能加载）
python tools/check_config.py

# 4 检查游戏
python tools/zzz_launch.py --check

# 5 自检
python tools/smoke_test.py

# 6 第一次跑
python tools/zzz_launch.py                        # 确保游戏开着
python tools/zzz_status.py 佩洛伊斯 --json          # 读一次状态
python tools/zzz_disc_daily.py 佩洛伊斯             # 看今天该做什么
python tools/zzz_daily.py 佩洛伊斯 --run            # 真跑
```

详细步骤见 **[INSTALL.md](INSTALL.md)**。

---

## 工具怎么选

| 想做什么 | 用哪个 |
|---|---|
| 每日自动养成 | `zzz_daily.py <角色> --run` |
| 只看驱动盘该做什么 | `zzz_disc_daily.py <角色>` |
| 看角色当前状态 | `zzz_status.py <角色>` |
| 看驱动盘换装建议 | `zzz_plan.py <角色>` |
| 一直刷到毕业 | `zzz_grind.py <角色> --run` |
| 检查配置/环境 | `check_config.py` |
| 出 bug 自查 | `smoke_test.py` / `audit_*.py` |

完整工具清单见 **[TOOLS.md](TOOLS.md)**，维护规则见 **[MAINTENANCE.md](MAINTENANCE.md)**。

---

## 支持的角色

`tools/disc_meta.json` 里配好了 **14 个角色**：

```
佩洛伊斯  蕾米埃尔  维琳娜  安比  苍角  简  丽娜
莱卡恩    猫又      妮可    派派  真斗  潘引壶  凯撒
```

每个角色配了：四件套 / 两件套候选 / 主词条要求 / 有效副词条 / 属性。

**加新角色**：在 `disc_meta.json` 里加一段，格式照抄现有的。
最少要四个字段：`定位` / `四件套` / `主词条` / `有效副词条`。

---

## 数据准确性

所有数值都标注了来源：

| 数据 | 来源 |
|---|---|
| 副词条基础值（暴击率 2.4%/roll 等） | 社区实测 + [GameVika](https://gamevika.com/zh-tw/zzz/wiki/disc-score-explained) |
| 毕业标准（28/32/37 条） | NGA 社区讨论 |
| 角色主词条要求 | 各角色攻略（9game / 3dmgame / 米游社） |
| 副本 → 套装掉落 | [萌娘百科](https://mobile.moegirl.org.cn/绝区零/驱动盘) |
| 电量机制（240 上限 / 6 分钟 1 点） | 游戏内实测 |

**角色的配装数据分两级，写在 `disc_meta.json` 的 `_来源` 字段里：**

| `_来源` | 数量 | 怎么来的 | 可靠性 |
|---|---|---|---|
| `手工` | 10 | 自己养的角色，按游戏实测校对 | 高 |
| `查证` | 54 | 逐个搜攻略站的推荐，带 `_依据` 和 `_源` | 中高（二手来源） |

**没有 `_来源: 推导` 的条目了** —— 早期按「属性 → 属性伤害套」推过 30 个，
其中 27 个是错的（例：星见雅是烈霜，但最优是折枝剑歌暴伤套，
和属性无关），已全部替换成查证数据。

**如果你发现某个角色的配装不对：**
```bash
# 看它现在用的是什么、依据是什么
python tools/zzz_who.py <角色名>

# 改 tools/disc_meta.json 里对应那条，然后验证
python tools/check_config.py
```

数值类（副词条基础值 / 毕业线 / 电量机制）都是实测或社区口径，过时了改一处就行。

---

## 已知限制

| 限制 | 说明 |
|---|---|
| **必须装 OneDragon** | 没有它就没有 OCR 和刷本 |
| 只支持 **1920x1080** | 所有坐标按这个分辨率标定，其他分辨率要重新标 |
| Windows only | 用了 Win32 API |
| 不能自动登录 | 账号密码/扫码要人工 |
| 不能处理游戏更新 | launcher 的更新流程要人工 |
| 游戏窗口必须在前台 | 最小化或被遮挡会失败（靠 Win32 截图 + 注入输入） |
| **别并发跑** | 两个会动游戏的工具同时跑会让彼此的判断错乱，串行执行 |
| `od_test/` 是产物目录 | 名字是历史遗留（早期开发目录名），里面放截图和中间 JSON |

**跑之前建议先用计划模式看一眼**（不动游戏，10 秒出结果）：

```bash
python tools/zzz_disc_daily.py 佩洛伊斯            # 出计划（会读一次游戏）
python tools/zzz_disc_daily.py 佩洛伊斯 --offline  # 秒出，只读缓存
python tools/zzz_daily.py 佩洛伊斯 --run    # 真跑
```

---

## 免责

本项目**不修改游戏内存、不注入游戏进程、不改网络包**。
所有操作等价于「人坐在电脑前移动鼠标、点击、按键」。

但**任何第三方工具都有风险**，使用前自己判断。作者不承担账号处罚的责任。

---

## 开源协议

[MIT](LICENSE)
