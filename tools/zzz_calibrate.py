"""生成界面指纹库 —— 让每个用户都能给自己的机器校准。

## 用户问的（2026-11-26 09:55）

> 还有为什么别人不能用指纹库

## 答案：因为我从来没给过生成它的命令

```
state/ 在 .gitignore 里        → git ls-files state/ = 0 个文件
state/fingerprints.json        → 从来没进过仓库
```

`core/fingerprint.py` 里有 `capture(vs, name, samples)` 能生成指纹，
**但没有任何工具调用它。** 所以：
· 我本机有一份（早期手工调出来的）
· 别人 clone 下来是空的
· `describe()` 退化成只用文字锚点

## 而且「硬塞给别人」是错的

指纹依赖三个东西：**分辨率、游戏 UI 版本、界面语言**。
别人的机器上大概率不一样 —— 塞一份我的过去，反而会让他误判
（踩过：我的旧指纹把「更多功能」判成了「驱动盘拆解页」）。

**所以正确做法是「给生成工具」，不是「给成品」。**

## 用法

```powershell
python tools/zzz_calibrate.py --list          # 看有哪些界面要校准
python tools/zzz_calibrate.py 代理人列表       # 站在这个界面上校准
python tools/zzz_calibrate.py --auto          # 逐个引导校准全部
```

## 校准原理

对一个界面连拍 3 帧，取**每帧都有、且不跨界面通用**的词条，
存成「这个界面的特征词集合」。判定时按「命中的特征词数 / 该界面的特征词数」打分。

**关键是「不跨界面通用」** —— 「等级」「UID」这种到处都有的词会被过滤掉，
否则所有界面都长得一样。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _names() -> list[str]:
    from core import anchors
    return [a.name for a in anchors.ANCHORS]


def _status(name: str) -> str:
    from core import fingerprint as fp
    d = fp.load()
    if not d:
        return "空"
    v = d.get(name)
    if not v:
        return "未校准"
    # **fingerprints.json 的结构是 {界面名: [特征词, ...]}** ——
    # v 是 list 不是 dict（`fingerprint.capture` 里 `data[name] = sorted(stable)`）
    return f"已校准（{len(v)} 个特征词）"


def main() -> int:
    from core import Vision, anchors
    from core import fingerprint as fp
    import live

    ap = argparse.ArgumentParser(description="生成界面指纹库")
    ap.add_argument("name", nargs="?", help="要校准的界面名（先用 --list 看）")
    ap.add_argument("--list", action="store_true", help="列出所有界面和校准状态")
    ap.add_argument("--auto", action="store_true",
                    help="引导式：一个个来，站在界面上按回车")
    ap.add_argument("--samples", type=int, default=3, help="拍几帧（默认 3）")
    args = ap.parse_args()

    names = _names()

    if args.list or (not args.name and not args.auto):
        print(f"共 {len(names)} 个界面：")
        print()
        print(f"  {'界面':<16}{'校准状态'}")
        print("  " + "-" * 40)
        for n in names:
            print(f"  {n:<16}{_status(n)}")
        print()
        print("校准某个界面：先让游戏停在这个界面，然后")
        print("  python tools/zzz_calibrate.py 界面名")
        print()
        print("或者一个个引导：")
        print("  python tools/zzz_calibrate.py --auto")
        return 0

    vs = Vision()
    win = live.find_window()
    if not win:
        print("✘ 没找到游戏窗口。先跑 python tools/zzz_launch.py")
        return 5
    live.foreground(win)
    time.sleep(0.5)

    def do_one(name: str) -> bool:
        vs.frame(force=True)
        cur = anchors.describe(vs)
        print(f"  当前界面判定为：{cur}")
        if cur != name:
            print(f"  ⚠ 和要校准的「{name}」不一致")
            print("     如果判定错了，说明文字锚点也认不出 —— 先把界面站对")
            ans = input("  仍然继续？(y/N) ").strip().lower()
            if ans != "y":
                return False
        print(f"  拍 {args.samples} 帧…")
        # **capture() 自己会存盘**，不要在外面再 save 一遍
        # （之前写成 data[name] = rec 会把整个库覆盖成一个 dict）
        fp.capture(vs, name, samples=args.samples)
        print(f"  ✔ 已写入 state/fingerprints.json（{name}）")
        return True

    if args.auto:
        print("引导式校准。对每个界面：")
        print("  1 手动把游戏停到那个界面")
        print("  2 按回车让它拍")
        print("  3 输入 s 跳过 / q 退出")
        print()
        for n in names:
            print(f"── {n} ──  （{_status(n)}）")
            cmd = input("  站好了按回车，s 跳过，q 退出： ").strip().lower()
            if cmd == "q":
                break
            if cmd == "s":
                continue
            do_one(n)
            print()
        print()
        print("完成。当前指纹库：")
        for n in names:
            print(f"  {n:<16}{_status(n)}")
        return 0

    if args.name not in names:
        print(f"✘ 「{args.name}」不在界面清单里。用 --list 看看")
        return 2
    ok = do_one(args.name)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
