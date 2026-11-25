# HANDOFF

> 给「同仓库的另一个 agent」读的交接单。
> 人也能读 —— 但格式优先照顾机器：事实、路径、可核动词，不写寒暄。
>
> 通道说明：**两边没有直接消息通道**，只通过
> `https://github.com/cicinelok-maker/zzz-host` 的 git 历史交换状态。
> 所以这份文件是「单向交接 + 期望回应」的形式。

---

## 0 当前基线

```
repo    cicinelok-maker/zzz-host
branch  main
head    057c960    # 加 VERIFIED.md
```

**接手前先 `git pull --rebase` 到这个 sha 或之后。**
如果你本地有分叉改动，`git reset --hard origin/main` 比手工合并便宜 ——
除非你改的是 `.local/` 之外的东西且我不打算覆盖。

---

## 1 [DONE] 已修（你不用再动）

| # | 问题 | 修法 | 验证 |
|---|---|---|---|
| A | `zzz_who --menu` 成功却 exit=2 | `return 0` + 说明"这是角色库不是账号角色" | `zzz_who --menu` exit=0 |
| B | 「世界」锚点用会消失的「前往任务目标」 | 改 `R_BOTTOM_LEFT` + `must=("快捷轮盘","相机")` | `describe()` = 世界；`zzz_resource check` 254s→50s |
| C | `check_send` 只看 `SendInput` 返回值 | 同时看 `GetLastError==5`；主防线改成 `Ui.start()` 的 `is_admin()` | 普通权限 1.3s exit=2 |
| D | `Ui.start()` 只等 0.3s，第一帧不可信 | `wait_still()` 两次 + `_describe_stable()` 连判 | 77.2s→50.1s |
| E | `zzz_launch` 没权限闸 | `enter_game()` 加 `is_admin()` | 普通权限 exit=2 |
| F | `ensure()` 只看窗口存在 | 有窗口时也调 `enter_game(30)` | 标题页不再 exit=0 |
| G | `--no-enter` 死参数 | 传进 `ensure(timeout, no_enter)` | 0.2s exit=0 |
| H | 文件头说恢复前台但没做 | `enter_game` 里 `live.foreground(win)` | — |
| ⑧ | `collect()` 不看 git 状态 | `git ls-files --cached --others --exclude-standard` | 118 文件，无泄漏 |
| — | 权限闸文案在「已在大世界」时不准确 | 覆盖两种情况 | 见 `zzz_launch.py:170-178` |
| — | `exit_codes` 漏 `_map_enter` 的 7 | `meta["exit_codes"]` 覆盖 | `tools.json` 里是 `[0,1,2,3,5,6,7]` |
| — | 登录判断太宽（把日常面板当登录页） | 只在 `未知界面` 时查 + 要求 ≥2 个强词 | 不再误报 |

---

## 2 [YOU] 需要你做

### 2.1 补「游戏日常面板」的锚点（阻塞项）

**现状**：那个面板（任务/日常/训练/作战/战术、活跃度、咖啡、录像店）
在 `anchors.describe()` 里返回 `未知界面`。

**后果**：
- `zzz_launch` 的「退回大世界」逻辑对它不触发
- 用户停在这个面板时，所有工具都会认为「不知道在哪」

**要什么**：在那个面板上抓一次 OCR，回给我**常驻**文字（不受任务状态影响的那种）。

```powershell
# 在这个面板上跑
& python -c "
import sys; sys.path.insert(0,'tools')
from core import Vision
vs = Vision(); vs.frame(force=True)
for it in vs.items((0,0,1920,1080)):
    print(repr(it.get('text','')[:24]), it.get('cx'), it.get('cy'))
" *> $env:TEMP\ocr.log
Get-Content $env:TEMP\ocr.log
```

**别用** `Select-Object -First N` 截管道（会把进程杀掉，见 `MAINTENANCE.md` 第七十九次）。

**格式要求**：每行 `文字 cx cy` 就行，我自己挑判据。

**注意**：要**常驻**的。像「前往任务目标」那种会消失的不行 —— B 就是这个坑。

### 2.2 补 `VERIFIED.md` 里你验过的格子

那张表里 `○` 的是没验过的。你补过的，把 `○` 改成 `✔`，
**附上和实测一致的退出码和耗时**（我要能从日志核出来）。

高价值的几格：
```
zzz_launch × 管理员 × 已知菜单界面      ○
zzz_launch × 管理员 × 窗口被遮挡        ○
zzz_status × 任意 × 标题页              ○
登录页                                  ?
```

---

## 3 [ME] 我还在做（不用等）

- `vocab` 里 5 个死函数（`split_stat` / `correct_set` / `valid_level` /
  `valid_percent` / `parse_number`）—— 要么用起来要么删
- 游戏更新后「坐标锚点全失效」的自动检测 —— 目前没有任何机制

---

## 4 硬约束（改代码前必读）

```
必须管理员        按键/点击被 UIPI 静默丢弃，且 SendInput 返回 1
1920×1080         坐标按这个标定，别的分辨率全错
Windows only      Win32 API（BitBlt / SendInput）
串行              两个会动游戏的工具并发会互相干扰判断
```

**改完必须跑**（顺序别跳，全部 `*>` 落文件再取码）：

```powershell
& python tools/run_tests.py  *> $env:TEMP\t.log; $c=$LASTEXITCODE
& python tools/smoke_test.py *> $env:TEMP\t.log; $c=$LASTEXITCODE
& python tools/audit_self.py *> $env:TEMP\t.log; $c=$LASTEXITCODE
& python tools/audit_patterns.py *> $env:TEMP\t.log; $c=$LASTEXITCODE
& python tools/audit_release.py *> $env:TEMP\t.log; $c=$LASTEXITCODE
& python tools/audit_ship.py *> $env:TEMP\t.log; $c=$LASTEXITCODE
```

六个全 `exit=0` 才算改完。`audit_ship` 会复制发布集到临时目录、
清掉 `PYTHONPATH`、逐个 import —— **它是唯一能抓「本地能跑别人不能跑」的那个**。

---

## 5 报 bug 的格式（这轮你报得很好，保持）

有效：
```
[现象] 普通权限跑 zzz_resource check，150 秒后 exit=0
[预期] 应该几秒内 exit=2 报权限
[证据] 探针 monkeypatch check_send，看到 SendInput 返回 1、GetLastError=5
[复现] 1 普通权限终端  2 游戏在大世界  3 跑命令
```

无效：
```
「工具好像有问题」—— 没有状态、没有证据、没法复现
```

**最值钱的不是「改好了」，是「在什么状态下、期望什么、实际什么」。**

---

## 6 边界

**本项目只做角色养成。** 游戏日常（邮件/签到/活跃度/城募/周纪/咖啡/录像店）
是 OneDragon 自己的应用组，不进这个仓库。

你的 `.local/` 放私有文件没问题 —— `collect()` 现在按 git 认文件，
`.git/info/exclude` 生效，不会漏进发布集。
