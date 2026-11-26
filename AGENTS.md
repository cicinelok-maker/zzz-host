# AGENTS.md

> 给「接进去就要跑」的 AI agent 看的。人类请看 [README.md](README.md)。
> 机器可读清单：[tools.json](tools.json)

---

## 这是什么

操作绝区零游戏的 CLI 工具集。要养哪个角色，就跑对应的命令。

**不是库，是命令行程序。** 所有交互都通过 `python tools/xxx.py` + 文件输出。

---

## 前置条件（缺一个就跑不了）

```bash
python tools/check_config.py     # 一条命令查全部
```

它会检查：

| 检查项 | 缺了会怎样 |
|---|---|
| 路径配置（OneDragon / 游戏 exe） | 所有工具都报配置缺失 |
| **OneDragon OCR 模块** | 读不了游戏画面 |
| 角色配置（disc_meta.json） | 不知道角色的套装/词条要求 |

**另需：游戏开着。** 没开就先跑：

```bash
python tools/zzz_launch.py       # 启动 + 等窗口 + 点进入游戏，约 72 秒
```

---

## 五条命令跑通

```bash
python tools/check_config.py                    # 1 环境
python tools/zzz_launch.py                      # 2 游戏
python tools/zzz_status.py <agent> --json       # 3 读状态（必须先做）
python tools/zzz_disc_daily.py <agent> --offline # 4 出计划（秒出，不碰游戏）
python tools/zzz_daily.py <agent> --run         # 5 真跑
```

`<agent>` 是角色名，如 `佩洛伊斯`。可用角色见 `tools/disc_meta.json`。

---

## 重要约定

### 退出码

```
0  成功
1  一般失败
2  配置缺失 / 参数错误
3  选不中角色
4  到不了目标界面
5  等窗口/条件超时   ← **游戏没开也走这个**（Vision 直接 SystemExit(5)）
6  需要人工登录      ← 不要重试，叫人
7  等进入游戏超时
8  读不到数据
```

### 哪些工具有副作用

**标了 `destructive: true` 的会真的改游戏数据**（花电量、花材料、换盘、拆解）：

```
zzz_daily          角色养成一轮（最重，会花电量/材料）
zzz_disc_daily     驱动盘养成一天
zzz_grind          多轮收敛
zzz_equip          换装 / 升级驱动盘（花材料，不可逆）
od_material_farm   刷本（消耗电量）
run_dismantle      拆解已弃置驱动盘 ← **不可逆，必须先看清数量**
zzz_disc_cycle     升级+判定+标记弃置+拆解（-recycle 时不可逆）
zzz_disc_train     驱动盘训练（真花材料升级，不可逆）
```

**拆解类没有「撤销」。** `run_dismantle` 不加 `--run` 只统计会拆多少张；
`zzz_disc_cycle --recycle` 拆前有两道闸（比例 + 数量），任一不过就中止。
**别在没看清数量的情况下加 `--run`。**

**安全做法：先跑不带 `--run` 的版本看计划。**

```bash
python tools/zzz_daily.py 佩洛伊斯            # 只出计划
python tools/zzz_daily.py 佩洛伊斯 --run      # 真跑
```

### 结构化输出

**实测过**（对每个工具跑 `--help` 看有没有 `--json`），现在只有这 6 个有：

```
zzz_status.py          → state/status_<agent>.json
zzz_gap.py
zzz_guide.py
zzz_guide_agents.py
zzz_uid.py
gen_manifest.py
```

其余工具输出**只是给人看的文本**，要数据就读 `state/*.json`。

**注意：`zzz_daily` / `zzz_grind` / `zzz_disc_daily` / `zzz_plan` 都没有 `--json`。**
它们会往 `state/` 写文件，但**标准输出不是 JSON** ——
对着它们调 `--json` 会被 argparse 当成未知参数，**exit 2**，
看起来像「配置缺失」，很容易误判。

（这份清单原来是错的：写着 `zzz_plan` / `zzz_auto` / `zzz_daily` /
`zzz_disc_daily` / `zzz_grind` 有 `--json`，实际 6 个里 5 个没有。
文档和代码脱节比没有文档更糟 —— 照着它调用只会得到一个 exit 2。）

### 状态文件

```
state/status_<agent>.json     角色当前状态（最重要的中间产物）
state/plan.json               换装计划
state/disc_progress.json      养成历史（list，每次跑追加一条）
state/core_status.json        核心技 A~F
state/skill_status.json       技能等级
```

字段定义见 [tools.json](tools.json) 的 `state_schema`。

---

## 场景：用户想养个角色，但没说哪个

**这是最常见的第一次用法。** 按这个顺序走：

```bash
# ① 确保游戏开着（没开就启动，约 72 秒）
python tools/zzz_launch.py

# ② 扫账号上有哪些角色 —— 输出一份可以直接给用户看的菜单
python tools/zzz_who.py --scan
```

`--scan` 的输出长这样，**直接把整段贴给用户**：

```
你的账号有 14 个角色：

 1. 佩洛伊斯　强攻·以太　24.0/28　·未毕业　主词条错3个
 2. 丽娜　　　支援·电　　0.0/28　·未毕业
 …
14. 波可娜　击破·物理　未盘点

要养哪个？直接说名字就行（例如「养佩洛伊斯」）
```

```bash
# ③ 用户说了名字之后，先盘点一次（必须，否则后续读不到数据）
python tools/zzz_status.py <角色名> --json

# ④ 真跑
python tools/zzz_daily.py <角色名> --run
```

**注意这几件事：**

| 情况 | 怎么办 |
|---|---|
| `--scan` 一个也扫不到 | 游戏没开 / 不是 1920x1080 → 先跑 `zzz_launch.py` |
| 用户说的名字不在菜单里 | 可能是错字 → 直接跑，`resolve_agent` 会自动纠正或报错 |
| 菜单里显示「未盘点」 | 正常，说明还没读过那个角色，跑了 `zzz_status` 就有数了 |
| 想一直养到毕业 | 用 `zzz_grind <角色> --run --target 28` |
| 想每天自动跑 | 见 INSTALL.md 的 schtasks 那一节 |

**没扫过想直接看菜单？** `python tools/zzz_who.py --menu` ——
它会提示你「先扫」，并把**角色库里的全部 64 个**列出来（那不是账号角色，别混）。

---

## 场景：用户说「养 XXX」但没说做什么

**默认动作是「跑一轮完整养成」**：

```bash
python tools/zzz_status.py XXX --json     # 先盘点
python tools/zzz_daily.py XXX --run       # 再跑
```

**跑之前先用计划模式看一眼。** 注意「计划模式」分两种，快慢差 100 倍：

| 命令 | 耗时 | 会不会碰游戏 |
|---|---|---|
| `zzz_daily XXX`（计划） | **~1 秒** | 不碰（2026-11-26 起，之前要 76 秒） |
| `zzz_disc_daily XXX --offline` | **~0.3 秒** | 不碰，只读缓存（数据可能过期） |
| `zzz_disc_daily XXX` | ~4 分钟 | **读一次游戏** |
| `zzz_plan XXX` | **~80 秒** | **读一次游戏**（要扫描全部盘） |
| `zzz_grind XXX`（计划） | 数分钟 | 内部要多次盘点 |

```bash
python tools/zzz_daily.py XXX                 # 出计划，约 1 秒，不碰游戏
python tools/zzz_disc_daily.py XXX --offline  # 秒出，只读缓存
```

**别指望 `zzz_plan` 是秒级的** —— 它必须把驱动盘仓库扫一遍才知道该换什么。

计划里会写清楚「今天该做什么」，你可以把它转述给用户确认，再 `--run`。

---

## 典型任务怎么组合

### 任务：看这个角色现在什么水平

```bash
python tools/zzz_status.py 佩洛伊斯 --json
# 读 state/status_佩洛伊斯.json
# total=质量分  blue_total=有效副词条个数  slots=[6个位号]
```

### 任务：今天该做什么（不动游戏）

```bash
python tools/zzz_disc_daily.py 佩洛伊斯 --offline
# 输出分 ①~④ 段：盘点 / 缺口 / 电量 / 动作建议
# 加 --offline 是 0.5 秒；不加会读一次游戏，约 4 分钟
```

### 任务：跑一轮完整养成

```bash
python tools/zzz_daily.py 佩洛伊斯 --run
# 会花电量、材料。跑完追加一条到 state/disc_progress.json
```

### 任务：一次养多个角色

编辑 `targets.json`：

```json
{"agents": ["佩洛伊斯", "丽娜"]}
```

```bash
python tools/zzz_daily.py --from-targets                  # 计划
python tools/zzz_daily.py --from-targets --run            # 真跑
python tools/zzz_daily.py --from-targets --max 2 --run    # 今天只养 2 个
```

按 `targets.json` 里的顺序跑，不重新排序（你想先养谁就写前面）。
单个角色失败不会中断整批，只打印返回码然后继续。

### 任务：看养成进度曲线

```bash
python tools/zzz_who.py 佩洛伊斯 --history
```

输出长这样：

```
  11-24 22:52    20.5   ██████████░░░░  蓝10
  11-25 07:41    24.0   ████████████░░  蓝11   ▲ +3.5
  起点 20.5 → 现在 24.0，涨了 3.5
  距小毕业 28 还差 4.0
  位号变化：
    3号位  5.5 → 6.5   ▲ +1.0
    4号位  1.5 → 4.0   ▲ +2.5 （啄木鸟电音 → 拂晓行纪）
```

**记录少于 3 条时会警告「速率是单次跳跃外推的」** ——
一次大改造（同时换装+训练+刷本）不是每天都能做到。

### 任务：只看驱动盘换装建议

```bash
python tools/zzz_plan.py 佩洛伊斯          # 只看
python tools/zzz_plan.py 佩洛伊斯 --apply  # 真换
```

---

## 容易踩的坑

### 1. `zzz_status` 必须至少跑一次

其他工具读 `state/status_<agent>.json`，没有这个文件会报：

```
还没有「XXX」的状态数据。先跑：
  python tools/zzz_status.py XXX --json
```

### 2. 分辨率必须是 1920x1080

所有坐标按这个分辨率标定。别的分辨率会全部点错位置。

### 3. 游戏窗口必须在前台

工具靠 Win32 找窗口 + 注入输入。窗口最小化或被遮挡会失败。

### 4. 有些工具很慢

```
zzz_disc_v2        5-40 分钟（逐位号滚动读仓库）
zzz_daily --run    10-40 分钟（含刷本和战斗）
od_material_farm   2-15 分钟（看刷几次）
```

**别设短超时就杀掉**，会留下半完成状态。

### 5. 别并发跑两个会动游戏的工具

它们都靠「截图 → 判断 → 点击」的循环，并发会让彼此的判断错乱。
**串行执行。**

### 6. 电量上限 240，6 分钟回 1 点

```
python tools/zzz_resource.py check      # 看当前电量
```

**满了不回复**，所以电量满了就该刷掉。

---

## 理解数据口径

### 质量分（`total`）vs 有效副词条个数（`blue_total`）

**这是两个不同的数，别混。**

```
blue_total = 4   游戏里标蓝的副词条有几条（肉眼能数）
total    = 12.0  口径B：存在1分 + 每升1次1分（升过的算更多）
```

- 给用户看进度 → 用 `total`（目标 28 / 32 / 37）
- 说「有几条有效词条」→ 用 `blue_total`

### 主词条（`main_verdict`）

```
good     在角色推荐列表里
weak     不在推荐里但能用
bad      对这个角色完全无效（如以太角色装火伤）
unknown  读不到
```

**`bad` 的优先级高于副词条好坏。** 主词条错 = 这条主属性白丢。

---

## 扩展

### 加一个角色

1. 在 `tools/disc_meta.json` 的 `角色` 下加一段：

```json
"角色名": {
  "定位": "强攻|异常|击破|支援|防护",
  "四件套": "套装名",
  "两件套候选": ["套装A", "套装B"],
  "主词条": {"4": ["暴击率"], "5": ["属性伤害", "攻击力"], "6": ["攻击力"]},
  "有效副词条": ["攻击力百分比", "暴击率", "暴击伤害"],
  "次选副词条": ["攻击力", "穿透率"]
}
```

2. 在 `tools/core/game_cfg.py` 的 `AGENT_ELEMENT` 加属性
3. 跑一次 `python tools/zzz_status.py 角色名 --json`

### 加一个界面

见 [MAINTENANCE.md](MAINTENANCE.md)。改完必须跑：

```bash
python tools/smoke_test.py
python tools/audit_stale_frame.py
python tools/audit_patterns.py
```

---

## 自检工具

改完代码或怀疑有问题时：

```bash
python tools/run_tests.py             # 单元测试（判盘/止损/调律/名字/等级匹配/换装确认/成本表，138 个用例）
python tools/smoke_test.py             # 全部工具的语法 + 导入
python tools/audit_self.py             # 有没有违反项目自己的规矩
python tools/audit_stale_frame.py      # 读旧帧（改画面后立刻读）
python tools/audit_patterns.py         # 历史 bug 模式
python tools/audit_release.py          # 发布集自洽（依赖都在发布集里吗）
python tools/audit_ship.py             # 终极验证（复制到临时目录完整跑）
python tools/check_config.py           # 环境
python tools/gen_manifest.py           # 重新生成 tools.json
```

**全绿才算改完。**

### 改了行为 → **必须同步改测试**

```bash
python tools/run_tests.py     # 改完立刻跑，别等提交前
```

**测试是「结论的快照」。** 你改了结论，测试还停在旧结论上 ——
它就从「这个 bug 的防护」变成「这个 bug 的阻碍」。

实测踩过：把 `主菜单 → 世界` 从「单 ESC」改成「交替 B/ESC」，
代码回退了但**测试没跟着回退**，于是 `run_tests` 红了、
`audit_ship` 也红了，而那一次「红」是**对的** ——
它在提醒我「代码和你上次确认的事实不一致了」。

**判断标准**：这条断言写的是「**我实测过的事实**」还是「**当前实现的样子**」？

· 前者（`主菜单上单按 ESC 有效，按 B 会打开别的面板`）→ 事实变了就改测试，
  并在注释里写清「什么时候、为什么变的」
· 后者（`assertIn("ok, out = run(", src)`）→ 尽量改成验证**行为**，
  只保留「守卫存在性」的粗检查

**提交前跑一遍全套**，别只跑 `run_tests`：

```bash
python tools/check_config.py; python tools/run_tests.py; python tools/smoke_test.py
python tools/audit_self.py; python tools/audit_patterns.py; python tools/audit_release.py
python tools/audit_ship.py; python tools/audit_stale_frame.py
```

`audit_ship` 特别重要 —— 它会在**发布集子集**里重跑测试，
能抓到「只在全仓里成立」的假设（我加的一条测试就因为假定
`AGENTS.md` 一定存在而红过）。
