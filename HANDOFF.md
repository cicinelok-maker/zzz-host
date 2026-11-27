# HANDOFF — 接手必读

> 这份文件是给**下一个会话 / 下一个人**看的。
> 只写「此刻的真实状态 + 怎么安全地接着做」。
> 变更历史看 `git log`，修了什么的清单看 `FIXED-REPORT.md`。

---

## 0. 一句话现状

```
代码结构：八项自检全绿，204 个单元测试通过
实机验证：**一条都没有**
功能完整度：还有缺口（见 §3）
```

**最重要的一句：`zzz_daily --run` 这条主链路，从来没被端到端跑过。**

---

## 1. 开跑之前（三个坑，踩过）

### 1.1 必须用 OneDragon 的 python

```powershell
$od = "E:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full\.venv\Scripts\python.exe"
& $od -u tools\zzz_daily.py 佩洛伊斯
```

**不是任何 python 都行。** 用别的 python 会在 `import pynput` 崩，
而报错看起来像「工具坏了」。我为此误判过一次 `--plan-only` 的行为。

纯逻辑/静态工具（`run_tests` / `audit_*` / `check_config`）用哪个 python 都行，
**只要碰游戏就必须用 `$od`**。

### 1.2 系统代理会连累飞书

Windows 系统代理指向 `127.0.0.1:8686`（VPN）。VPN 一断，
`tools/feishu.py` 会连带失败。已经在代码里绕开了（`ProxyHandler({})` +
`NO_PROXY`），但如果哪天飞书又发不出去，先查 `Get-ItemProperty` 里的 `ProxyEnable`。

### 1.3 自检要 `*> 落文件`，别直接管道

```powershell
& $py "tools\run_tests.py" *> "$env:TEMP\a.log"; $LASTEXITCODE
```

`Select-Object -First N` 会提前关管道，**退出码就丢了**。

---

## 2. 改代码时的四条规矩（都是踩出来的）

### 2.1 验证用 `compile()`，不是 `ast.parse()`

`ast.parse` 只做语法分析，**查不出编译期错误**。
我把 `global` 写在函数中间，`ast.parse` 通过，import 直接 `SyntaxError`。

### 2.2 测试里别用「源码文本包含」判定

这叫**自指陷阱**，我踩了 **6 次**：

| 场景 | 测试怎么被骗的 |
|---|---|
| `zzz_cost` 的 `range` | 注释里写了 `range(cur, 12)` |
| outcome rules | 注释里引用了要禁止的正则 |
| `START_HERE.md` | 解释 `od_farm` 的说明里含关键词 |
| `DEFAULT_AGENT` | docstring 里引用了 `DEFAULT_AGENT = "佩洛伊斯"` |
| `zzz_resource` | 注释里写了 `required=True` |
| `--train-n` | 注释里引用了「训练潜力最高的 N 块」 |

**做法**：用 `ast` 找到真正的调用节点再断言，或者只检查 `print` 调用的参数。

### 2.3 改文件时先「数匹配」，最后一次性写

我写过一个补丁脚本：三处替换都成功，但 `compile()` 崩在最后 ——
**`write_text` 没执行，改动全丢**。而脚本已经打印了三个 ✔。

```python
n = 0
if OLD1 in s: s = s.replace(...); n += 1
if OLD2 in s: s = s.replace(...); n += 1
if n == 3:
    compile(s, "x.py", "exec")     # 先编译
    p.write_text(s, ...)           # 再写盘
```

### 2.4 改了行为 → 同步改测试

测试是「结论的快照」。代码改了、测试没改，它就从「bug 的防护」变成「bug 的阻碍」。

---

## 3. 还没做完的（按风险排）

### 3.1 实机验证 —— **最高优先，且只有你能做**

这 60+ 个 commit 改的全是代码结构。**行为对不对，只有跑才知道。**

```powershell
python tools/zzz_daily.py 佩洛伊斯            # 1. 先看计划（约 1 秒，不碰游戏）
python tools/zzz_daily.py 佩洛伊斯 --run      # 2. 真跑一轮（约 100 电量）
```

跑完要核对四件事：
· 状态机导航对不对（51 条转移，我没法静态验证）
· 点击落点对不对（坐标、位号、技能名）
· 材料/电量是不是真按预期消耗
· 退出码符不符合 `AGENTS.md` 那张表

### 3.2 已知的功能缺口（不是 bug，是「这块还没做」）

| 项 | 说明 |
|---|---|
| **没有领域时钟** | 游戏 04:00 重置、周常、双周锚点都不存在。而工具叫「每日养成」——**「每日」这个概念本身没实现** |
| **9 个幽灵状态 / 15 条不可达转移** | 干净安装上，拆解/弃置链路**必然失败**（新审计 D8/RT-04） |
| **弃置/拆解可能误拆毕业盘** | 只按 set+slot+level 定位，同套同级盘会被认错（RT-12，**不可逆**） |
| **执行模式从未真跑过** | 见 §3.1 |

### 3.3 明确还没修的静态条目

| 条目 | 内容 |
|---|---|
| BUG-077 | `zzz_status` 死代码：一段空 `for` 循环、`disc_color.report` 连调两次 |
| BUG-064 | 原子写只改了核心 6 处，还有 ~35 处裸 `write_text(json)` |
| 旧审计 P2 ~60 条 | BUG-099~219，**既没有「已修」的证据，也没被新审计复检** |

---

## 4. 三份审计的关系（别搞混）

| 文件 | 方法 | 能看见什么 |
|---|---|---|
| `AUDIT-BUGS.md`（256 条） | **实机跑** | 时序、导航、点错、材料真消耗、界面判定 |
| `zzz-host-redteam-report.md`（21 条） | **只读代码** | 参数放错、死代码、schema 打架 |
| `zzz-host-audit-full.md`（52 条） | **只读代码** | 同上（和 RT 高度重叠） |

**两者的覆盖面是正交的，不能互相验证。**

我犯过一次错：看到静态审计不再点名 `zzz_mcp`/`zzz_status`，就推断「那些修好了」。
错在**静态审计本来就不会跑游戏** —— 它不提那些文件只说明它的方法。

详见 [`STATUS.md`](STATUS.md)。

---

## 5. 文档地图

| 想知道什么 | 看哪 |
|---|---|
| 怎么用这套工具 | [`README.md`](README.md) / [`START_HERE.md`](START_HERE.md) |
| AI agent 怎么调 | [`AGENTS.md`](AGENTS.md)（含退出码表、`--json` 清单、自检流程） |
| 修了什么 | [`FIXED-REPORT.md`](FIXED-REPORT.md)（大白话版） |
| 256 条旧审计的覆盖情况 | [`STATUS.md`](STATUS.md) |
| 卡在哪、需要谁做什么 | [`BLOCKED.md`](BLOCKED.md) |
| 加界面/改锚点 | [`MAINTENANCE.md`](MAINTENANCE.md) |

---

## 6. 自检命令（改完必跑）

```powershell
$py = "C:\Users\cicin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
foreach ($c in @('check_config','run_tests','smoke_test','audit_self',
                 'audit_patterns','audit_release','audit_ship','audit_stale_frame')) {
    & $py "tools\$c.py" *> "$env:TEMP\$c.log"
    "$c exit=$LASTEXITCODE"
}
```

**八项全 0 才算改完。** 日志里还要 grep 一遍 `✘|FAIL|Traceback` ——
有两项历史上恒返回 0，只看退出码会漏。

---

## 7. 接手时的第一件事

```powershell
git pull --rebase origin main
& $py tools\check_config.py        # 环境对不对
& $py tools\run_tests.py           # 300+ 个用例
```

两个都绿，说明你接手的是一份**结构健康**的代码。
然后：**能不能用，得跑一次 `--run` 才知道。**
