"""资源体检 + 等回体。

## 为什么要单独一块

闭环的「资源不够就等回体」需要先知道：
    电量多少 / 需要多少 / 每小时回多少 / 够不够跑一轮

而且拆解产出镀剂和母盘（用户确认），所以要能读这两样。

## 用法

    python tools/zzz_resource.py              # 体检：电量/母盘/镀剂
    python tools/zzz_resource.py wait         # 等到电量够一轮再返回
    python tools/zzz_resource.py wait --need 60
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core import Vision, Input, Ui, anchors  # noqa: E402
from core.machine import Machine  # noqa: E402
from pick_agent import reset_to_world  # noqa: E402
from core.jsonout import emit
from core.game_cfg import FARM_COST  # 唯一权威来源（core/game_cfg.py）


R_TOP = (900, 10, 1920, 130)
R_TUNE_TOP = (1000, 10, 1920, 110)
CHARGE_PER_MIN = 1 / 6  # 实测：每次 6 分钟回 1 点


def read_charge(vs: Vision) -> int:
    """读电量。读不到返回 -1"""
    t = vs.text(R_TOP)
    # **`\d{2,3}` 要求至少两位**（BUG-074）—— 电量 9/240 是**一位数**，
    # 那时 `re.search` 匹配不到，函数返回 -1（未知），
    # 上层就当「读不到电量」，刷本决策全被跳过。
    #
    # 改成 `\d{1,3}`。不会误配：模式后面强制要求 `/240`，
    # 所以 `1240/240` 这种会从第 2 位开始匹配到 `240/240`。
    m = re.search(r"(\d{1,3})\s*/\s*240", t)
    return int(m.group(1)) if m else -1


def read_disk(vs: Vision) -> int:
    """读母盘数（调律界面顶部的 8 位计数，共三个，最后一个是母盘）"""
    t = vs.text(R_TUNE_TOP)
    nums = re.findall(r"(\d{8})", t)
    return int(nums[-1]) if nums else -1


def goto_world(ui: Ui) -> Machine:
    m = Machine(ui, verbose=False)
    reset_to_world(ui)
    return m


def cmd_check(ui: Ui, as_json: bool = False) -> int:
    vs = ui.vs
    m = goto_world(ui)
    vs.frame(force=True)
    print(f"当前界面：{anchors.describe(vs)}")
    # 电量只在主菜单显示，大世界看不到
    if m.go_to("主菜单"):
        vs.frame(force=True)
    n = read_charge(vs)
    _data = {"battery": n if n >= 0 else None, "battery_max": 240}
    if n >= 0:
        print(f"电量：{n}/240")
        print(f"  一次区域巡防需要 {FARM_COST} 点"
              f"　{'够' if n >= FARM_COST else f'还差 {FARM_COST - n} 点'}")
        if n < FARM_COST:
            need = FARM_COST - n
            mins = need / CHARGE_PER_MIN
            print(f"  约 {mins:.0f} 分钟回满一轮（每 6 分钟 1 点）")
    else:
        print("电量：读不到（可能不在大世界或主菜单界面）")

    # 母盘要去调律界面读
    if m.go_to("调律界面"):
        vs.frame(force=True)
        d = read_disk(vs)
        _data["mother_discs"] = d if d >= 0 else None
        print(f"母盘：{d if d >= 0 else '读不到'}")
        bot = vs.text((0, 900, 1920, 1080))
        print(f"  调律界面：{bot[:90]}")
        m.go_to("世界")
    emit("zzz_resource", data=_data, enabled=as_json)
    _write_cache(_data)
    return 0


def cmd_wait(ui: Ui, need: int, timeout_min: int) -> int:
    vs = ui.vs
    m = goto_world(ui)
    t0 = time.time()
    miss = 0
    while True:
        # 电量只在主菜单显示，大世界读不到（= -1）。
        # 每次都要切过去读，读完回大世界——不然会一直等到超时。
        if m.go_to("主菜单"):
            vs.frame(force=True)
        n = read_charge(vs)
        if n < 0:
            # 切回大世界重试一次，避免卡在奇怪界面
            goto_world(ui)
            if m.go_to("主菜单"):
                vs.frame(force=True)
            n = read_charge(vs)
        elapsed = (time.time() - t0) / 60
        print(f"[{datetime.now():%H:%M:%S}] 电量 {n}（需要 {need}）"
              f"　已等 {elapsed:.0f} 分钟", flush=True)
        if n >= need:
            print("电量够了")
            return 0
        if n < 0:
            miss += 1
            if miss >= 3:
                print("连续 3 次读不到电量，放弃（检查游戏是不是在主菜单/大世界）")
                return 2
        else:
            miss = 0
        if elapsed > timeout_min:
            print(f"等超过 {timeout_min} 分钟，放弃")
            return 1
        # 一次等 5 分钟再查
        time.sleep(300)


def _write_cache(data: dict) -> None:
    """把电量/母盘写进 state/resource_cache.json，供 --offline 模式读。

    只写读到的值，读不到的不写（避免把 None 当成 0）。
    """
    import datetime
    import json
    out = {}
    b = data.get("battery")
    if isinstance(b, (int, float)) and b >= 0:
        out["battery"] = int(b)
    m = data.get("mother_discs")
    if isinstance(m, (int, float)) and m >= 0:
        out["mother"] = int(m)
    if not out:
        return
    out["ts"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        d = BASE / "state"
        d.mkdir(parents=True, exist_ok=True)
        (d / "resource_cache.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    # **子命令不是必填，默认 check**（BUG-073）。
    #
    # 文件头第一条用法就是：
    #     python tools/zzz_resource.py              # 体检：电量/母盘/镀剂
    # 而 `required=True` 让这条命令直接 exit 2
    # （「the following arguments are required: cmd」）——
    # **最自然的那个写法，文档说能用，实际不能用。**
    sub = ap.add_subparsers(dest="cmd", required=False)
    # --json 加在每个子命令上（子命令后面写才自然）
    pc = sub.add_parser("check")
    pc.add_argument("--json", action="store_true", help="输出结构化 JSON")
    p = sub.add_parser("wait")
    p.add_argument("--need", type=int, default=FARM_COST)
    p.add_argument("--timeout", type=int, default=240, help="最多等多少分钟")
    args = ap.parse_args()

    vs, inp = Vision(), Input()
    ui = Ui(vs, inp)
    ui.start()

    # 没给子命令 -> 默认 check（体检）
    if not getattr(args, "cmd", None):
        args.cmd = "check"

    if args.cmd == "check":
        return cmd_check(ui, as_json=getattr(args, "json", False))
    return cmd_wait(ui, args.need, args.timeout)


if __name__ == "__main__":
    sys.exit(main())