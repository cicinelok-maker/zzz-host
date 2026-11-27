# 工具清单（自动生成）

> 数据从代码抽：行数、argparse 子命令和参数都是实时的。
> 用途优先取手工标注，其次是模块 docstring。

## 一、总控（4 个）—— 从这里开始

| 工具 | 行数 | 用途 |
|---|---|---|
| `zzz_daily.py` | 820 | 日常总控：音擎→等级→转化→技能→核心技→驱动盘→刷本→训练回收　`参数 --from-targets --max --force-unknown --convert --run --resume` |
| `zzz_grind.py` | 348 | 多轮收敛：反复跑到目标或电量耗尽　`参数 --force-unknown --run --rounds --target --wait-charge --patience` |

**怎么选**：
- 想「一键养成一轮」→ `zzz_daily.py 佩洛伊斯 --run`
- 想「只做某几步」→ `zzz_daily.py <角色> --run --skip wengine,core,disc,farm`
- 想「一直刷到目标」→ `zzz_grind.py 佩洛伊斯 --run`

## 二、驱动盘（10 个）

| 工具 | 行数 | 用途 |
|---|---|---|
| `zzz_disc_v2.py` | 179 | 批量读仓库驱动盘 → JSON　`参数 --out` |
| `zzz_disc_train.py` | 323 | 单盘读+判（read_disc / evaluate 被 status 复用）　`参数 --train --no-stop-loss --slots --limit --max-steps` |
| `zzz_disc_cycle.py` | 434 | 升级→判定→换下→标记弃置→拆解 完整闭环　`参数 --train --recycle --keep-min --slots` |
| `zzz_equip.py` | 339 | 装备/升级驱动盘（equip 带 --level 指定等级）　`子命令 upgrade/equip/show；参数 --slot --set --agent --level` |
| `zzz_plan.py` | 455 | 4+2 最优分配决策，可 --apply 直接换装　`参数 --apply --eff-loss-limit --secondary --out` |
| `zzz_status.py` | 390 | 全状态总览：位号/等级/主属性/有效词条/达标度　`参数 --force-unknown --json` |
| `zzz_tune.py` | 394 | 定向调律：音轨设定 + 定向分区 + 调律　`参数 --times --slot --dry` |
| `run_dismantle.py` | 161 | 批量拆解所有已弃置的驱动盘　`参数 --run` |
| `disc_gaps.py` | 142 | 调律套装自动推导 + 升级中途止损　`参数 --agent` |
| `filter_terms.py` | 96 | 角色有效词条 → 筛选面板选项映射 |

## 三、其他四系统（8 个）

| 工具 | 行数 | 用途 |
|---|---|---|
| `zzz_resource.py` | 199 | 读电量/母盘（只在主菜单可见）　`子命令 check/wait；参数 --json --need --timeout` |
| `zzz_convert.py` | 197 | 材料转化（合成高阶材料）　`参数 --slot --all --agent --confirm` |
| `zzz_level.py` | 387 | 角色等级/晋升（含转化获取自动合成）　`子命令 read/up/roster；参数 --agent --auto --times` |
| `zzz_skill.py` | 302 | 技能升级　`参数 --agent --max --out` |
| `zzz_skill_target.py` | 117 | 按岗位给技能目标等级（强攻/异常/击破…）　`参数 --all` |
| `zzz_core.py` | 398 | 核心技读取/升级（A-F 六个圈）　`参数 --agent --goto --out --times` |
| `zzz_wengine.py` | 555 | 音擎强化/进阶/改装　`子命令 read/up/recommend/auto；参数 --agent --times` |
| `zzz_cost.py` | 215 | 养成成本表（EXP/证书/芯片/高维/蓄电池）　`参数 --all` |

## 四、刷本（3 个）

| 工具 | 行数 | 用途 |
|---|---|---|
| `od_material_farm.py` | 350 | 刷本入口（--training/--challenge/--patrol）　`参数 --training --patrol --challenge --hunt --times --mission` |
| `zzz_farm_plan.py` | 629 | 刷本计划：按材料缺口自动分配电量　`参数 --battery --convert --run` |

## 五、辅助（4 个）

| 工具 | 行数 | 用途 |
|---|---|---|
| `live.py` | 480 | 真机操作底层：识屏→点文字/模板→再截图确认　`参数 --probe --enter --enter-loop --click-text --click-tpl --shot` |
| `pick_agent.py` | 614 | 切换代理人（头像模板匹配）　`参数 --list` |
| `selfcheck.py` | 153 | 兼容性自检（6 项） |

## 六、体检/校验（11 个）

| 工具 | 行数 | 用途 |
|---|---|---|
| `audit_all.py` | 166 | 全量体检：常量冲突/口径/系统/总控链路/状态文件 |
| `audit_eff.py` | 39 | 逐行审计有效值计算口径 |
| `audit_coords.py` | 65 | 坐标/阈值重复定义审计 |
| `smoke_test.py` | 152 | 全部 canonical 工具的冒烟测试 |

## 七、分析/展示（4 个）

| 工具 | 行数 | 用途 |
|---|---|---|
| `gap_analysis.py` | 69 | 距离小毕业还差多少，差在哪个位号 |
| `explain_crit.py` | 83 | 命中率说明：全歪/部分/全中 |
| `show_discs_v2.py` | 35 | 读盘结果展示 |
| `cleanup_tools.py` | 196 | 工具清理（canonical 清单 → _legacy）　`参数 --apply` |

## 八、核心库 `tools/core/`（17 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `__init__.py` | 116 | 包声明 |
| `agent_cfg.py` | 381 | 角色配置的统一入口：具体角色数据 → 职业模板回退。 |
| `agent_name.py` | 220 | 角色名归一化：书名号 / 简称 / 繁简 / OCR 错字。 |
| `anchors.py` | 446 | 页面指纹识别（21 个页面） |
| `atomic.py` | 90 | 原子写：先写临时文件再 `os.replace`，避免半截 JSON。 |
| `characters.py` | 100 | 本地角色覆盖层。 |
| `charge_plan.py` | 114 | 电量规划：今天能刷几次、先刷哪个、什么时候回满。 |
| `click.py` | 98 | 统一点击：点下去 → 验证结果 → 不对就换方式重试。 |
| `cost_data.py` | 69 | 养成成本数据的**单一来源**（E2）。 |
| `disc_cfg.py` | 230 | 驱动盘区域/阈值/坐标（唯一权威） |
| `disc_color.py` | 145 | 用游戏自己标的颜色判断有效副词条。 |
| `disc_initial.py` | 210 | 驱动盘的「初始判定」：升不升，在升之前就决定。 |
| `disc_main.py` | 200 | 主词条校验：这个位号的主词条适不适合这个角色。 |
| `disc_potential.py` | 96 | 彻底修正 disc_potential：命中率要用「解锁后」的词条构成。 |
| `disc_stats.py` | 220 | 词条数值表 + roll 反推 + 百分比归名 |
| `disc_stoploss.py` | 121 | 升级节点止损：每个 Lv3/6/9/12/15 判断该不该继续。 |
| `farm_cmd.py` | 63 | 副本名 → od_material_farm 参数：**唯一的实现，给多个工具共用**。 |
| `farm_gap.py` | 201 | 刷本按缺口：根据当前状态算「今天该刷哪个本、刷几次」。 |
| `farm_log.py` | 131 | 刷本日志 `state/farm_log.json` 的**唯一读写入口**（RT-08）。 |
| `fingerprint.py` | 223 | 指纹采集 |
| `flows.py` | 113 | 通用流程 |
| `focus.py` | 122 | 窗口焦点保护。 |
| `game_cfg.py` | 174 | 电量/刷本成本/卡片（唯一权威） |
| `input.py` | 444 | 键鼠输入（键盘必须 SCANCODE） |
| `inventory.py` | 142 | 材料库存记账。 |
| `journal.py` | 84 | 任务日志（jsonl） |
| `jsonout.py` | 87 | 统一的 --json 输出格式。 |
| `locate.py` | 131 | 元素定位 |
| `machine.py` | 753 | 状态机导航（43 条转移） |
| `material_nav.py` | 320 | 材料弹窗 → 直接传送到获取副本。 |
| `paths.py` | 243 | 路径配置：把本机绝对路径变成可配置 + 自动探测。 |
| `pause.py` | 109 | 暂停 / 断点 / 续跑。 |
| `portrait.py` | 161 | 灰色头像 → 改成「看徽章」：S/A = 已拥有，锁 = 未解锁。 |
| `progress.py` | 86 | 进度记录 |
| `recovery.py` | 137 | 异常恢复 |
| `slots.py` | 69 | 驱动盘位几何（环形 6 位 + 空位兜底） |
| `state.py` | 248 | 读取角色状态的唯一入口（读不到时给清晰提示）。 |
| `tune_plan.py` | 151 | 修 tune_plan：定向调律的母盘成本是 6，不是 1。 |
| `ui.py` | 183 | UI 封装（click/key/find/text） |
| `vision.py` | 385 | 截图 + OCR（PPOCRv6） |
| `vocab.py` | 115 | 属性词表 + stat_name_of |
| `weekly.py` | 115 | 周本 / 免费次数的电量模型。 |
| `zh.py` | 170 | 繁简归一：游戏里同一个名字，OCR 有时读简体有时读繁体。 |

## 九、已归档 `tools/_legacy/`

共 89 个历史文件，不参与运行。需要查旧实现时可以看，
但**不要再 import**。详见 `DISC_CHAIN.md` 的「历史遗留」表。

> 注：早期版本这里提过一个「自动判断下一步」的工具，它**从来没有存在过** ——
> 是文档先行、代码没跟上留下的幽灵条目（已删）。
> 要「下一步该干嘛」用 `tools/zzz_gap.py`。

