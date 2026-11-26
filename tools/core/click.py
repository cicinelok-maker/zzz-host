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
    # **验证函数自己抛异常，不能被吞成「点击失败」**（BUG-039）。
    #
    # 原来 `except Exception: pass` —— `check()` 里要是崩了（OCR 挂了、
    # 或者判定函数自己有 TypeError），表现出来是
    # 「点「X」失败（试了 4 次）」，于是人跑去查坐标、查界面，
    # 而真正的问题在判定函数里。
    #
    # 现在：异常记下来，第一次就报一句「验证函数本身抛异常」，
    # 最后那条失败信息也会带上异常类型 —— 让两种失败长得不一样。
    _exc = None
    for i in range(max(1, tries)):
        dx, dy, extra = RETRY_PLAN[min(i, len(RETRY_PLAN) - 1)]
        inp.click(x + dx, y + dy, wait=wait + extra)
        vs.frame(force=True)
        try:
            if check():
                return True
        except Exception as e:
            if _exc is None:            # 只报第一次，别刷屏
                print(f"    ⚠ 验证函数本身抛异常（{type(e).__name__}: {e}）"
                      f"—— 这多半是 bug，不是「点击没生效」")
            _exc = e
    if label:
        if _exc is not None:
            print(f"    点「{label}」未通过验证（试了 {tries} 次；"
                  f"验证函数抛过 {type(_exc).__name__}）")
        else:
            print(f"    点「{label}」失败（试了 {tries} 次）")
    return False
