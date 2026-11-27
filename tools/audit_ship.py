"""终极验证：把发布集复制到临时目录，模拟别人的机器完整跑一遍。

## 为什么需要这个（朋友的三个 bug 教会我的）

朋友的 agent 一装就报：
```
① tools.json 登记了不存在的 capture_fp_we
② status.py 崩溃（import zzz_host）
③ 截图/探针残留
```

**我的 12 个 audit 工具一个都没抓到。** 共同原因：
```
① gen_manifest 扫本地目录，本地有 capture_fp_we.py
② 本地有 zzz_host.py，所以 import 成功、status.py 能跑
③ 本地有那些残留文件
```

**「在本地能跑」这件事本身没有信息量。**

这个工具做的事：
1. 只复制**发布集**到临时目录
2. **显式清掉 PYTHONPATH**
3. 逐个 `import` 每个 core 模块（不只是 `--help`）
4. 跑所有自检工具
5. 确认没有本地独有文件泄漏

```
python tools/audit_ship.py
```
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "tools"))

from publish_github import collect  # noqa: E402
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

PY = sys.executable
# state/ 和 od_test/ 是 core/__init__.py 自己建的（运行时产物目录），
# targets.json 是故意发布的空模板 —— 这三个都不算泄漏。
# **按模式拦，不只按名字**（BUG-050）。
#
# `EXPECT_ABSENT` 是一份**名字黑名单** —— 只有写进去的文件会被检查。
# 新出现一个没登记过的敏感文件（比如以后加了 `ai_config.json` 带 key），
# 它照样会被打进发布集，而且**没人知道**。
#
# 这里按文件名/路径模式再拦一道。这份清单宁可宽一点：
# 误报的代价是「多看一眼」，漏报的代价是「把密钥发到 GitHub」。
SENSITIVE_PATTERNS = [
    (r"(^|[/\\])state[/\\]", "运行时数据（含 UID / chat_id / 养成记录）"),
    (r"(^|[/\\])feishu_conf\.json$", "飞书凭证"),
    (r"(^|[/\\])paths\.json$", "本机路径配置（不含 .example）"),
    (r"(^|[/\\])config\.local\.json$", "本机配置"),
    (r"(^|[/\\])\.env", "环境变量文件"),
    (r"(^|[/\\])\.git[/\\]", "git 内部文件"),
    (r"\.(pem|key|pfx|p12|keystore)$", "私钥/证书"),
    (r"(^|[/\\])id_(rsa|dsa|ecdsa|ed25519)", "SSH 私钥"),
    (r"(secret|credential|apikey|api_key)", "名字里带密钥字样"),
    (r"(^|[/\\])journal[/\\]", "运行日志（含坐标和截图记录）"),
]

EXPECT_ABSENT = ["zzz_host.py", "status.py", "graduate.py", "od_bridge.py",
                 "paths.json", "tools/feishu.py", "tools/capture_fp_we.py",
                 "roster.json", "feishu_conf.json"]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="zzz_ship_"))
    files = collect(BASE)
    for rel in files:
        dst = tmp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASE / rel, dst)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)          # ★ 关键：不给便利

    print("=" * 74)
    print(f"发布集：{len(files)} 个文件")
    print("=" * 74)

    fails = []

    def run(label, args, timeout=900):
        r = subprocess.run([PY, "-u"] + args, cwd=str(tmp),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=timeout)
        ok = r.returncode == 0
        print(f"  {'✔' if ok else '✘'} {label:<32} exit={r.returncode}")
        if not ok:
            tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-4:]
            for ln in tail:
                print(f"      {ln[:70]}")
            fails.append(label)
        return r

    print()
    print("① 自检工具能在干净环境跑吗")
    print("-" * 74)
    for label, args in [
        ("check_config", ["tools/check_config.py"]),
        ("run_tests（单元测试）", ["tools/run_tests.py"]),
        ("smoke_test", ["tools/smoke_test.py"]),
        ("audit_self", ["tools/audit_self.py"]),
        ("audit_patterns", ["tools/audit_patterns.py"]),
        ("audit_lessons", ["tools/audit_lessons.py"]),
        ("audit_release", ["tools/audit_release.py"]),
    ]:
        run(label, args)

    print()
    print("② 逐模块 import（不只是 --help）")
    print("-" * 74)
    mods = [f"core.{p.stem}" for p in sorted((tmp / "tools" / "core").glob("*.py"))
            if p.name != "__init__.py"]
    code = (
        "import sys, importlib\n"
        "sys.path.insert(0, 'tools')\n"
        f"mods = {mods!r}\n"
        "bad = []\n"
        "for m in mods:\n"
        "    try:\n"
        "        importlib.import_module(m)\n"
        "    except Exception as e:\n"
        "        bad.append((m, type(e).__name__, str(e)[:64]))\n"
        "for m, t, e in bad:\n"
        "    print(f'  X {m}: {t}: {e}')\n"
        "print(f'  {len(mods) - len(bad)}/{len(mods)} 个 core 模块能 import')\n"
        "sys.exit(1 if bad else 0)\n"
    )
    r = subprocess.run([PY, "-u", "-c", code], cwd=str(tmp),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=300)
    print((r.stdout or "").strip() or (r.stderr or "").strip()[:300])
    if r.returncode != 0:
        fails.append("core 模块 import")

    print()
    print("③ 每个工具的 --help")
    print("-" * 74)
    bad_help = 0
    total = 0
    for t in sorted((tmp / "tools").glob("*.py")):
        # live.py 是开发工具：模块级直接干活（argparse 之前就有副作用），
        # 测 --help 没意义。core/input.py 只用它的 find_window()。
        if t.stem.startswith(("audit_", "selftest_", "_", "run_tests",
                              "gen_", "cleanup", "publish_", "live")):
            continue
        # 只有带 argparse 的工具才有 --help。
        # 有些工具是纯脚本（模块级读文件、直接报错退出），测 --help 没意义。
        src = t.read_text(encoding="utf-8", errors="replace")
        if "argparse" not in src:
            continue
        total += 1
        r = subprocess.run([PY, "-u", f"tools/{t.name}", "--help"],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env,
                           timeout=120)
        if r.returncode != 0:
            err = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()
            print(f"  ✘ {t.name}: {(err[-1] if err else 'no output')[:60]}")
            bad_help += 1
    print(f"  {total - bad_help}/{total} 个工具 --help 正常")
    if bad_help:
        fails.append(f"{bad_help} 个工具 --help 失败")

    print()
    print("④ 本地独有文件有没有泄漏")
    print("-" * 74)
    leaked = [x for x in EXPECT_ABSENT if (tmp / x).exists()]
    if leaked:
        print(f"  ✘ {leaked}")
        fails.append("文件泄漏")
    else:
        print(f"  ✔ {len(EXPECT_ABSENT)} 个都不在")

    # **按模式再扫一遍**（BUG-050）
    import re as _re
    hits = []
    for rel in files:
        r = str(rel).replace("\\", "/")
        for pat, why in SENSITIVE_PATTERNS:
            if _re.search(pat, r):
                hits.append((r, why))
                break
    # **内容级隐私扫描**（RT-16 / RT-18）。
    #
    # 原来只有「按文件名」的黑名单，而 RT-18 的问题是
    # **一个正常的文件名里装着 PII**（`config.json` 里的 nickname/uid）。
    # 光看文件名永远发现不了。
    #
    # 扫的是一小撮高危模式，宁少勿滥（避免把正常文档也判红）：
    #   · 真实游戏 UID：9 位数字且不是全 0 / 全占位
    #   · 平台 token：ghp_ / ghp_ 前缀 / sk- 开头
    #   · 本机绝对路径带真实用户名
    import re as _re2
    _RISKY = [
        (r"\b(?!0{9})[0-9]{9}\b", "像是游戏 UID（9 位数字）"),
        (r"gh[pousr]_[A-Za-z0-9]{20,}", "GitHub token"),
        (r"sk-[A-Za-z0-9]{20,}", "API key"),
        (r"C:\\Users\\(?!cicin)[A-Za-z0-9_.-]{3,}", "别人的本机路径"),
        (r'"nickname"\s*:\s*"(?![A-Z_]{4,})[^"]{2,}"', "真昵称"),
    ]
    _hits = []
    for rel in files:
        _p = tmp / rel
        if not _p.exists() or _p.suffix.lower() not in (
                ".md", ".json", ".py", ".txt", ".yml", ".yaml", ".ps1"):
            continue
        try:
            _txt = _p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for _pat, _why in _RISKY:
            for _m in _re2.finditer(_pat, _txt):
                _hits.append((str(rel), _why, _m.group(0)[:40]))
    print()
    print("⑥ 发布集里有没有隐私内容（按内容）")
    print("-" * 74)
    if _hits:
        for _r, _w, _v in _hits[:12]:
            print(f"  ✘ {_r}  {_w}：{_v!r}")
        if len(_hits) > 12:
            print(f"  … 还有 {len(_hits) - 12} 处")
        fails.append("隐私内容")
    else:
        print(f"  ✔ {len(_RISKY)} 条隐私模式都没命中")

    print()
    print("⑤ 发布集里有没有敏感文件（按模式）")
    print("-" * 74)
    if hits:
        for r, why in hits:
            print(f"  ✘ {r}  ← {why}")
        print(f"\n→ {len(hits)} 个不该进发布集的文件")
        fails.append("敏感文件")
    else:
        print(f"  ✔ {len(SENSITIVE_PATTERNS)} 条模式都没命中")

    print()
    print("=" * 74)
    if fails:
        print(f"✘ {len(fails)} 项失败：{fails}")
        print(f"   副本保留在：{tmp}")
        return 1
    print("✔ 干净副本完全可用（模拟别人的机器）")
    print("=" * 74)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())