# HANDOFF

> 交接单。**每轮重写，不追加** —— git log 是变更历史，这里只写「此刻该做什么」。
> 通道：两边没有直接消息通道，只通过 `cicinelok-maker/zzz-host` 的 git 交换状态。

---

## 0 基线

```
head    99c8fd0 之后（先 git pull --rebase origin main）
分叉     有本地改动就 reset --hard，除非改的是 .local/
```

**改完必跑六个自检，全 `exit=0` 才算完**（`*>` 落文件再取码，别用 `Select-Object -First`）：

```
run_tests.py  smoke_test.py  audit_self.py
audit_patterns.py  audit_release.py  audit_ship.py
```

`audit_ship` 最关键 —— 复制发布集到临时目录、清 PYTHONPATH、逐模块 import。
**只有它能抓「本地能跑别人不能跑」。**

---

## 1 [YOU] 两件

### 1.1 补「游戏日常面板」的锚点（阻塞）

那个面板（任务/日常/训练/作战/战术、活跃度、咖啡、录像店）在
`anchors.describe()` 里返回 `未知界面`，导致所有导航都认为「不知道在哪」。

在那个面板上抓一次 OCR，回给我 **常驻**文字（不受任务状态影响的那种）：

```powershell
& python -c "
import sys; sys.path.insert(0,'tools')
from core import Vision
vs = Vision(); vs.frame(force=True)
for it in vs.items((0,0,1920,1080)):
    print(repr(it.get('text','')[:24]), it.get('cx'), it.get('cy'))
" *> $env:TEMP\ocr.log
Get-Content $env:TEMP\ocr.log
```

格式 `文字 cx cy` 每行一条就行。

**别用会消失的字** —— 「前往任务目标」那种只在追踪任务时出现，
拿它当判据会导致任务做完后整个导航链断掉（已修过一次，见 git log `25421c7`）。

### 1.2 补 `VERIFIED.md` 里你验过的格子

把 `○` 改成 `✔`，**附实测的退出码和耗时**（要能从日志核出来）。

优先这几格：
```
zzz_launch × 管理员 × 已知菜单界面
zzz_launch × 管理员 × 窗口被遮挡
zzz_status × 任意 × 标题页
登录页
```

---

## 2 [ME] 在做

- `vocab` 里 5 个死函数
- 游戏更新后「坐标锚点全失效」的自动检测

---

## 3 硬约束

```
必须管理员      UIPI 静默丢弃按键/点击，且 SendInput 返回 1（看不出被拦）
1920×1080      坐标按这个标定
Windows only   Win32 API
串行           两个会动游戏的工具并发会互相干扰
权限 × 状态    验证样本要按这个矩阵铺开，见 VERIFIED.md
```

---

## 4 报 bug 的格式

有效：
```
[现象] 普通权限跑 zzz_resource check，150 秒后 exit=0
[预期] 应该几秒内 exit=2 报权限
[证据] 探针 monkeypatch check_send，SendInput 返回 1、GetLastError=5
[复现] 1 普通权限终端  2 游戏在大世界  3 跑命令
```

无效：「工具好像有问题」。

**最值钱的不是「改好了」，是「在什么状态下、期望什么、实际什么」。**

---

## 5 边界

**只做角色养成。** 游戏日常（邮件/签到/活跃度/城募/周纪/咖啡/录像店）
是 OneDragon 自己的应用组，不进这个仓库。

`.local/` 放私有文件没问题 —— `collect()` 按 git 认文件，`.git/info/exclude` 生效。

---

## 维护规则

**这份文件每轮重写。** 下次交接时把上面那节 `[YOU]` 整个换掉，
不要在后面加「第 N 轮修了……」。

- 只留「现在」—— 做过什么去看 `git log`
- 超 120 行就是屎山（`audit_self.py` 会报）
- 细节写在 `MAINTENANCE.md` / `VERIFIED.md`，这里只写「去看哪个文件」
