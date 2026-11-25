# 早上好 —— 30 秒版

## 现在在跑什么

每天 **20:00** 会自动跑一轮（任务名 `ZZZ养成托管`）：
体检 → 扫描 20 个角色真实等级 → 算缺口/ETA → 执行能执行的升级 → 写记录。
游戏没开的话它会自己启动。

昨晚实测 7 轮，7 轮全绿，最后一轮是完整路径：

```
✔ 启动游戏 10s  ✔ 体检 4s  ✔ 扫描 145s  ✔ 导入 2s  ✔ 计划 2s  ✔ 执行 97s
```

## 刷本：已跑通（2026-11-22 00:05 首次全自动进战斗）

`tools/od_farm.py` 不开 GUI 就能把缺口写进 OneDragon「体力刷本」并触发它。
现在能一路走到自动战斗，跑到电量耗尽自己回大世界：

```
实战模拟室·共鸣测试 → 向前移动准备战斗 → 开始自动战斗
→ 战斗结果-完成 → 回到快捷手册 → 下一轮 → 电量不足 → 返回大世界
执行结果：成功  剩余电量 40
```

```powershell
python tools/od_farm.py --plan-only    # 只写配置
python tools/od_farm.py --run          # 触发 OneDragon（已实测可跑）
python tools/loop.py --farm            # 连刷本一起跑
```

刷本前会先跑 `tools/to_world.py` 退回大世界 —— 停在仓库/装备页时，
OneDragon 第一步「打开快捷手册」就会失败，整段白跑（昨晚 359s 全废就是这个）。

## 代理人晋升：现在可以直接交给刷本

以前这张表要手动打，现在同一件事有一条命令：

```powershell
python tools/od_farm.py --agent 莱卡恩 --times 10 --run    # 代理人晋升 · 击破演练 ×10
python tools/od_farm.py --agent 苍角  --times 5  --run     # 支援演练 ×5
```

它写进 OneDragon 的「体力刷本」再自己开跑（导航 + 自动战斗 + 回大世界）。
电量不够会自己用储蓄电量，还不行就停在「剩余电量 N」并回大世界。

| 角色 | 缺多少 | 刷哪个本 | 次数 |
|---|---|---|---|
| 莱卡恩 | 0/20 | 击破认证章 | 10 |
| 安比 | 0/20 | 击破认证章 | 10 |
| 苍角 | 3/12 | 支援认证章 | 5 |

一共 **25 次 ≈ 500 电量**。20:00 那轮会自动把能升的升掉。

## 想看状态

```powershell
cd C:\Users\<user>\Documents\deepseek-harness\default-workspace\zzz-host
python status.py
```

## 想临时关掉自动跑

```powershell
schtasks /change /tn "ZZZ养成托管" /disable   # 关
schtasks /change /tn "ZZZ养成托管" /enable    # 开
```

## 已知限制（不用怀疑是自己没弄好）

- 打副本得手动：手柄没有快捷手册入口，键盘 F2 被反作弊过滤
- 商城买不到材料：那是付费时装商店
- 11 个角色里只有 4 个读到完整三维数据，ETA 因此偏乐观（系统会自己标注）
- 如果游戏停在**登录/协议页**，自动化进不去，需要你手动过

## 文件在哪

- `status.py` 一屏状态 · `daily.ps1` 每日入口 · `TASKS.md` 全部决策与踩坑记录
- `README.md` 系统说明 · `legacy/` 早期实验脚本
