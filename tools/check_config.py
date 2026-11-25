"""检查配置是否齐全（第一次用先跑这个）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

from core.paths import (summary, check, one_dragon_python, one_dragon_env)  # noqa: E402


def main() -> int:
    print("=" * 64)
    print("配置检查")
    print("=" * 64)

    s = summary()
    for k, v in s.items():
        print(f"  {k:<18} {v}")

    missing = check()
    print()
    if missing:
        print("✘ 配置不完整：")
        for m in missing:
            print(f"    {m}")
        print()
        print("  做法（二选一）：")
        print("    1 复制 config.example.json 成 config.json，改成本机路径")
        print("    2 设环境变量 ONE_DRAGON_HOME / GAME_EXE")
        return 1

    print("✔ 路径配置齐全")

    # 检查 OneDragon 的 OCR 模块（核心依赖）
    print()
    import subprocess as _sp
    _py = one_dragon_python()
    if not _py:
        print("✘ 找不到 OneDragon 的 python.exe")
        return 1
    _code = "import one_dragon.base.matcher.ocr.onnx_ocr_matcher as m; print('ok')"
    _env = {"PYTHONPATH": one_dragon_env().get("PYTHONPATH", ""),
            "PYTHONIOENCODING": "utf-8"}
    _r = _sp.run([_py, "-c", _code], capture_output=True, text=True,
                 encoding="utf-8", errors="replace", env=_env, timeout=120)
    if _r.returncode == 0:
        print("✔ OneDragon OCR 模块可用")
    else:
        print("✘ OneDragon OCR 模块加载失败：")
        print("   ", ("".join((_r.stdout or "", _r.stderr or "")))[:200])
        print("  → OneDragon 可能版本太旧，或不是完整包")
        return 1

    # 检查 disc_meta 和角色
    meta_p = HERE / "disc_meta.json"
    print()
    if meta_p.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        roles = (meta.get("角色") or {})
        print(f"✔ disc_meta.json：{len(roles)} 个角色")
        # 分三级：
        #   完整（有专门配装）→ 精确判定
        #   只有定位（靠职业模板）→ 能跑，精度略低
        #   连定位都没有 → 真有问题
        full, tpl_only, broken = [], [], []
        for n, c in roles.items():
            has_cfg = bool(c.get("四件套") and c.get("主词条")
                           and c.get("有效副词条"))
            has_role = bool(c.get("定位") or c.get("岗位"))
            if has_cfg:
                full.append(n)
            elif has_role:
                tpl_only.append(n)
            else:
                broken.append(n)

        print(f"  ✔ 完整配装 {len(full)} 个")
        if tpl_only:
            print(f"  · 靠职业模板 {len(tpl_only)} 个（能跑，精度略低）")
            print(f"      {tpl_only}")
            print(f"      要精确的话在 disc_meta.json 补「四件套/主词条/有效副词条」")
        if broken:
            print(f"  ✘ 连定位都没有 {len(broken)} 个：{broken}")
            print(f"      → 这些角色会被当成强攻处理，可能判错")
    else:
        print("✘ 缺 tools/disc_meta.json")

    # 检查飞书（本机可选，发布版不含）
    print()
    if not (HERE / "feishu.py").exists():
        print("· 没装飞书通知（可选功能，不影响主流程）")
        fc = None
    else:
        fc = HERE / "feishu_conf.json"
    if fc is not None and fc.exists():
        try:
            d = json.loads(fc.read_text(encoding="utf-8"))
            ok = bool(d.get("app_id") and d.get("app_secret"))
            print(f"{'✔' if ok else '⚠'} 飞书凭证：{'已配' if ok else '不完整'}"
                  f"（可选功能）")
        except Exception:
            print("⚠ 飞书凭证文件读不了（可选功能）")
    elif fc is not None:
        print("· 没配飞书凭证（可选功能，不影响主流程）")

    print()
    print("下一步：")
    print("  python tools/zzz_launch.py --check   # 检查游戏")
    print("  python tools/smoke_test.py           # 跑自检")
    print()

    # 管理员权限：非管理员时按键注入会被 Windows UIPI 静默丢弃，
    # 表现为「工具白等到超时」而不是报错（朋友实测 254 秒才发现）。
    try:
        if str(Path(__file__).resolve().parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
        from core.input import is_admin
        if is_admin():
            print("✔ 管理员权限：有（按键注入正常）")
        else:
            print("⚠ 管理员权限：没有")
            print("   按键/点击会被 Windows UIPI 静默丢弃 ——")
            print("   工具不会报错，而是白等到超时（实测 4 分钟）")
            print("   正确用法：右键终端 → 以管理员身份运行")
    except Exception as e:
        print(f"· 管理员权限：查不到（{type(e).__name__}）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
