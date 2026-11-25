"""统一点击：点下去 → 验证结果 → 不对就换方式重试。

## 为什么需要这个

这套系统全靠固定坐标硬点，实测的失败模式：

    点了，但界面还没渲染完 / 点到了别的地方

之前每个工具各写各的重试，四套写法：
```
zzz_status:  for _try, (dx, dy) in enumerate([(0,0),(0,0),(8,8),(-8,-8)])
zzz_wengine: for _ in range(3): ...
zzz_core:    手动点两次
zzz_equip:   for attempt in range(tries): ... 再点一次偏移 (10,10)
```

## 只保留一个函数

`click_verify(ui, xy, check, tries, wait, label)`

```python
ok = click_verify(
    ui, (1231, 309),
    check=lambda: anchors.is_(ui.vs, "驱动盘定制"),
    tries=4,
)
```

重试策略（按实测频率排序）：
```
第1次：原点
第2次：原点，多等 1.2s（应对加载慢——最常见，也最安全）
第3次：+8,+8（应对坐标偏左上）
第4次：-8,-8（应对坐标偏右下）
```

先试「同一位置再点一次」是因为它最常见且不会点到相邻元素；
换位置有风险，放后面。

## 2026-11-24 修正：删掉了没用的函数

原来还写了 `click_until` / `click_first` / `safe_click`，
但全项目零调用者（而且 `locate.py` / `ui.py` 里已有同名但语义不同的实现，
容易混）。按「不用的代码不留」原则删掉，只留 `click_verify`。
"""
from __future__ import annotations

# 重试策略：(dx, dy, 额外等待秒数)
RETRY_PLAN = [
    (0, 0, 0.0),      # 原点
    (0, 0, 1.2),      # 同位置，多等
    (8, 8, 0.0),      # 偏左上 → 往右下挪
    (-8, -8, 0.0),    # 偏右下 → 往左上挪
]


def click_verify(ui, xy: tuple[int, int], check, tries: int = 4,
                 wait: float = 2.0, label: str = "") -> bool:
    """点一个坐标并验证结果，失败按策略重试。

    ui     Ui 对象
    xy     目标坐标
    check  无参函数，返回 True 表示成功（通常是 anchors.is_ 或自写的判定）
    tries  最多试几次
    wait   每次点击后等多久
    label  出错信息里显示的名字
    """
    vs, inp = ui.vs, ui.inp
    x, y = xy
    for i in range(max(1, tries)):
        dx, dy, extra = RETRY_PLAN[min(i, len(RETRY_PLAN) - 1)]
        inp.click(x + dx, y + dy, wait=wait + extra)
        vs.frame(force=True)
        try:
            if check():
                return True
        except Exception:
            pass
    if label:
        print(f"    点「{label}」失败（试了 {tries} 次）")
    return False
