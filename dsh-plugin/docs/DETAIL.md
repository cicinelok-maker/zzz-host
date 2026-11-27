# 绝区零养成托管

把 [zzz-host](../README.md) 的养成工具接成 DSH 可调用的工具。

**这不是一个独立的插件** —— 它是个 MCP 客户端配置，
把 `zzz-host/tools/zzz_mcp.py` 接进来。


> 英文版：[DETAIL.en.md](DETAIL.en.md)。**两份要一起改** —— 有一个测试会数工具个数对不对得上。
---

## 它提供什么

9 个工具，覆盖「看 → 想 → 做」三个阶段：

| 工具 | 干什么 | 有副作用 |
|---|---|---|
| `zzz_environment` | 检查环境（路径 / OneDragon OCR / 角色配置） | 否 |
| `zzz_launch` | 确保游戏开着（没开就启动 + 点进入） | 否 |
| `zzz_read_status` | 读角色状态（结构化 JSON） | 否 |
| `zzz_read_resource` | 读电量 / 母盘 | 否 |
| `zzz_plan` | 4+2 换装建议（结构化） | 否 |
| `zzz_daily_plan` | 今天该做什么（文本） | 否 |
| `zzz_daily_run` | 跑一轮完整养成 | **是**（需 `confirm:true`） |
| `zzz_list_agents` | 列出支持的角色 | 否 |
| `zzz_scan_roster` | 扫**账号上实际有**哪些角色（游戏要开着，实测约 6 分钟） | 否 |

**只有 `zzz_daily_run` 会改游戏数据**（花电量/材料），
且必须显式传 `confirm: true`，否则只返回计划。

---

## 装之前必须准备

这个插件**只是接口**，实际工作靠 `zzz-host` + OneDragon。

1. **装 OneDragon**（完整包）
   - [Releases](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/releases)
   - 下 `-Full.zip`，解压，先跑一次它的 GUI 确认能刷本

2. **拿到 zzz-host** 并配好 `paths.json`

3. **确认能用**
   ```bash
   cd zzz-host
   python tools/check_config.py     # 应该全绿
   python tools/smoke_test.py       # 应该 15/15
   ```

---

## 安装

### 1 改 patch

编辑 `cordis.patch.yml`，把两个占位改掉：

```yaml
cwd: C:\path\to\zzz-host          # ← 你的 zzz-host 绝对路径
command: python                    # ← 能跑 python 3.11+ 的解释器
args:
  - tools/zzz_mcp.py
```

**`command` 用哪个 python**：
- 系统 `python`（有 3.11+）就行 —— MCP 服务器本身只用标准库
- 实际跑游戏工具时，它会自己去找 OneDragon 的 python

### 2 装

```
plugin_manager install_bundle  .../zzz-host/dsh-plugin
```

或按 DSH 的本地 bundle 安装方式。

### 3 验证

装好后在对话里试：

```
用 zzz_environment 看看环境
```

应该返回 `check_config.py` 的输出（全绿或告诉你缺什么）。

---

## 典型用法

```
看一下佩洛伊斯现在什么水平 → 会调 zzz_read_status
今天该做什么？           → 会调 zzz_daily_plan
帮我跑一轮               → 会调 zzz_daily_run，但需要你确认
```

**agent 应该的调用顺序**：

```
1 zzz_environment   ← 环境不对就别继续
2 zzz_launch        ← 游戏没开就开
3 zzz_read_status   ← 拿到当前状态
4 zzz_daily_plan    ← 看今天该做什么
5 zzz_daily_run     ← 你确认后才真跑
```

---

## 已知限制

| 限制 | 说明 |
|---|---|
| **必须自己装 OneDragon** | 插件不含 OCR 模型和刷本逻辑 |
| **必须改 cwd** | 本地路径没法自动推断 |
| **只支持 1920x1080** | 所有坐标按这个分辨率标定 |
| Windows only | 用了 Win32 API |
| 不能自动登录 | 账号密码/扫码要人工 |
| 单实例 | 别并发跑两个会动游戏的工具 |

---

## 数据口径

调用 `zzz_read_status` 后，返回的 JSON 里有两个容易混的数：

```
blue_total = 10     游戏里标蓝的副词条有几条（肉眼能数的）
total      = 24.0   口径B：存在1分 + 每升1次1分（升过的算更多）
```

- 说「几条有效词条」→ 用 `blue_total`
- 说「离毕业还差多少」→ 用 `total`（目标 28 / 32 / 37）

`slots[].main_verdict` 是主词条判定：

```
good     在角色推荐列表里
weak     不在推荐里但能用
bad      对这个角色完全无效（如以太角色装火伤）
unknown  读不到
```

**`bad` 的优先级高于副词条好坏** —— 主词条错等于这条主属性白丢。

---

## 卸载

`plugin_manager remove_bundle zzz-host-mcp`

不影响 `zzz-host` 本身，也不改游戏任何文件。