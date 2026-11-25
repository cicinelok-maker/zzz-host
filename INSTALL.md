# 安装 / 配置

> 面向第一次用这个项目的人。整个过程约 15 分钟。
> **最重要的一步是装 OneDragon —— 没有它什么都跑不起来。**

---

## 需要什么

| 东西 | 必需? | 说明 |
|---|---|---|
| Windows 10/11 | ✔ | 项目用了 Win32 API |
| 绝区零 | ✔ | 装在任意位置 |
| **[OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon) 完整包** | ✔ | **OCR 和刷本都靠它** |
| Python 3.11+ | 通常不用另装 | 用 OneDragon 自带的 |

---

## 第一步：装 OneDragon（必须）

### 为什么必须

本项目**只用 OneDragon 的两样东西**：

| 用它的什么 | 拿来干什么 |
|---|---|
| `one_dragon.base.matcher.ocr.onnx_ocr_matcher` | **OCR** —— 读游戏画面上的文字和数字 |
| `zzz_od.context.zzz_context` + 电量计划 | **自动战斗刷本** |

```
其他部分都是本项目自己实现的：
  截图        纯 Win32 BitBlt + PIL
  键鼠输入     Win32 SendInput（键盘用 SCANCODE）
  状态机      26 个状态 / 49 条转移，全部自己写
  驱动盘判断  完全自己实现
  养成规划    完全自己实现
```

**为什么不自己写 OCR**：OneDragon 的 OnnxOcrMatcher 已经调好了模型和参数，
自己接 PaddleOCR/ONNX 是重复劳动，而且识别率不一定更好。

### 怎么装

1. 打开 [Releases 页面](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/releases)
2. 下载 **`ZenlessZoneZero-OneDragon-vX.X.X-Full.zip`**
   ⚠️ **要「Full」完整包，不是源码包**
3. 解压到任意目录，例如：
   ```
   E:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full
   ```
4. 确认目录里有 `src\` 和 `plugins\` 两个子目录
5. **先跑一次它的 GUI**，确认能连上游戏、能刷本
6. 记下这个路径

### 版本要求

需要包含 `one_dragon.base.matcher.ocr.onnx_ocr_matcher` 模块的版本。
OneDragon v2.x 都有。`check_config.py` 会实测这个模块能不能加载。

---

## 第二步：拿本项目

```bash
git clone <本项目地址> zzz-host
cd zzz-host
```

---

## 第三步：配置路径

复制模板：

```bash
copy paths.example.json paths.json
```

编辑 `paths.json`：

```json
{
  "one_dragon_home": "E:\\OneDragon\\ZenlessZoneZero-OneDragon-v2.6.1-Full",
  "od_home": "E:\\OneDragon\\zzz-clean",
  "game_exe": "A:\\miHoYo Launcher\\games\\ZenlessZoneZero Game\\ZenlessZoneZero.exe",
  "zzz_python": ""
}
```

| 字段 | 填什么 |
|---|---|
| `one_dragon_home` | 第一步解压的 OneDragon 目录 |
| `od_home` | 刷本用的配置目录。只有一个 OneDragon 的话填一样的 |
| `game_exe` | 米哈游启动器 → 设置 → 游戏路径 |
| `zzz_python` | 留空 → 用 `one_dragon_home\.venv\Scripts\python.exe` |

**也可以用环境变量**（不建 paths.json 的话）：

```bash
set ONE_DRAGON_HOME=E:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full
set GAME_EXE=A:\miHoYo Launcher\games\ZenlessZoneZero Game\ZenlessZoneZero.exe
```

---

## 第四步：验证

```bash
python tools/check_config.py
```

应该看到：

```
✔ 路径配置齐全
✔ OneDragon OCR 模块可用          ← 关键：实测 OCR 能不能加载
✔ disc_meta.json：14 个角色
  ✔ 全部角色配置齐全
```

如果 OCR 那行是 ✘，说明 OneDragon 版本不对或不是完整包。

再检查游戏：

```bash
python tools/zzz_launch.py --check
python tools/smoke_test.py
```

---

## 第五步：第一次用

```bash
# 1 确保游戏开着（没开就自动启动 + 点进入游戏）
python tools/zzz_launch.py

# 2 读一次角色状态（必须先做，生成 state/status_<角色>.json）
python tools/zzz_status.py 佩洛伊斯 --json

# 3 看今天该做什么（只出计划，不动游戏）
python tools/zzz_disc_daily.py 佩洛伊斯

# 4 真跑一轮
python tools/zzz_daily.py 佩洛伊斯 --run
```

---

## 常见问题

### Q: 报「缺少 OneDragon」

按第一步装。`check_config.py` 会告诉你现在探测到哪个路径。

### Q: 报「OneDragon OCR 模块加载失败」

- 确认下的是 **Full 完整包**，不是源码包
- 确认 `one_dragon_home\.venv\Scripts\python.exe` 存在
- OneDragon 版本太旧（v2.0 以下可能没有这个模块）

### Q: 报「找不到游戏窗口」

- 游戏没开 → `python tools/zzz_launch.py`
- 游戏开了但尺寸不对 → 必须 **1920x1080**
- 分辨率不是 1920x1080 → 所有坐标按这个标定的，其他分辨率要重新标定

### Q: 想让另一个角色也自动养成

1. 确认 `tools/disc_meta.json` 里有该角色的配置
2. 跑一次 `python tools/zzz_status.py <角色名> --json`
3. 之后所有命令都加角色名参数

目前配好了 14 个角色。

### Q: 会不会被封号

本项目**不修改游戏内存、不注入游戏进程、不改网络包**。
它和你手动操作一样：移动鼠标、点击、按键、看屏幕。

但**任何第三方工具都有风险**，自己判断。OneDragon 本身也是这类工具。

---

## 卸载

删掉项目目录即可。没有安装到系统任何位置，没有注册表，没有后台服务。

OneDragon 是独立安装的，本项目不改它任何文件（只读它的模块 + 写它自己的配置文件）。
