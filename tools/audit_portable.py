"""可移植性审计：能不能给别人用 / 发 GitHub。

## 用户需求（2026-11-25）

「你再深入体检一下，看有什么bug，我想让我的朋友也用上，后面我还想发GitHub」

## 要查什么

1. **硬编码绝对路径** —— 别人的用户名/盘符不同，直接跑不了
2. **个人隐私数据** —— UID / token / chat_id / 账号，发 GitHub 就泄露了
3. **依赖缺失** —— 没有 requirements.txt，别人装不上
4. **文档缺失** —— 没有 README，别人不知道怎么用
5. **.gitignore 缺失** —— 状态文件、日志会一起提交
"""
import pathlib
import re
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

BASE = pathlib.Path(__file__).resolve().parent.parent

print("=" * 80)
print("① 硬编码绝对路径（别人电脑上不存在）")
print("=" * 80)

# 用 chr 拼出来 —— 否则本文件自己会被自己报出来（自指问题）
_B = chr(92)
_C = chr(58)
_USER = "[A-Za-z0-9_]+"      # 任意用户名，不写死
PATTERNS = [
    (rf"C{_C}{_B}{_B}Users{_B}{_B}{_USER}[^\s\"')]*", "本机用户目录"),
    (r"E" + _C + _B + _B + r"OneDragon[^\s\"')]*", "本机 OneDragon"),
    (r"A" + _C + _B + _B + r"miHoYo[^\s\"')]*", "本机游戏路径"),
    (r"E" + _C + _B + _B + r"deepseek[^\s\"')]*", "本机 DSH"),
]
hits_by_file = {}
for f in sorted((BASE / "tools").rglob("*.py")):
    s = f.read_text(encoding="utf-8", errors="replace")
    for pat, label in PATTERNS:
        for m in re.finditer(pat, s):
            hits_by_file.setdefault(str(f.relative_to(BASE)), []).append(
                (label, m.group(0)[:60]))

for name, hits in sorted(hits_by_file.items(), key=lambda x: -len(x[1])):
    print(f"\n  {name}  {len(hits)} 处")
    for label, txt in hits[:3]:
        print(f"     [{label}] {txt}")

print()
print("=" * 80)
print("② 个人隐私数据（发 GitHub 会泄露）")
print("=" * 80)

PRIVACY = [
    (r"UID[:：]\s*(\d{8,})", "游戏 UID"),
    (r"oc_[a-f0-9]{20,}", "飞书 chat_id"),
    (r"cli_[a-f0-9]{16,}", "飞书 app_id"),
    (r"app_secret\s*[:=]\s*['\"]([^'\"]+)", "飞书 secret"),
    (r"app_id\s*[:=]\s*['\"]([^'\"]+)", "飞书 app_id"),
]
for f in sorted(BASE.rglob("*")):
    if not f.is_file() or f.suffix not in (".py", ".json", ".md", ".yml", ".txt"):
        continue
    if "_legacy" in str(f) or "od_test" in str(f):
        continue
    try:
        s = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    for pat, label in PRIVACY:
        for m in re.finditer(pat, s):
            val = m.group(0)[:50]
            rel = str(f.relative_to(BASE))
            print(f"  [{label}] {rel}")
            print(f"     {val}")
            break

print()
print("=" * 80)
print("③ 缺哪些发 GitHub 必备的文件")
print("=" * 80)
NEED = {
    "README.md": "项目说明 / 安装步骤 / 用法",
    "requirements.txt": "Python 依赖",
    ".gitignore": "排除状态/日志/缓存",
    "LICENSE": "开源协议",
    "config.example.json": "配置模板（不含私人数据）",
    "INSTALL.md": "详细安装步骤",
}
for name, why in NEED.items():
    exists = (BASE / name).exists()
    print(f"  {'✔' if exists else '✘'} {name:<24} {why}")

print()
print("=" * 80)
print("④ 会被误提交的个人文件")
print("=" * 80)
RISKY = [
    ("tools/feishu_conf.json", "飞书凭证"),
    ("state/", "运行时状态（含 UID）"),
    ("od_test/", "测试输出/截图/日志"),
    ("state/disc_progress.json", "养成记录"),
]
for p, why in RISKY:
    full = BASE / p
    if full.exists():
        n = len(list(full.rglob("*"))) if full.is_dir() else 1
        size = sum(x.stat().st_size for x in full.rglob("*") if x.is_file()) if full.is_dir() else full.stat().st_size
        print(f"  ⚠ {p:<28} {why}　{n} 个文件 {size // 1024} KB")

print()
print("=" * 80)
print("⑤ 依赖清单（从 import 反推）")
print("=" * 80)
imports = set()
for f in (BASE / "tools").rglob("*.py"):
    s = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"^(?:import|from)\s+([a-zA-Z_][\w]*)", s, re.M):
        imports.add(m.group(1))
STD = set("abc argparse ctypes dataclasses datetime enum functools hashlib io "
          "itertools json logging math os pathlib random re shutil string "
          "subprocess sys threading time traceback typing unicodedata uuid "
          "warnings collections contextlib queue signal socket struct tempfile "
          "textwrap types urllib csv base64 copy difflib glob html inspect "
          "operator pickle platform pprint secrets statistics".split())
LOCAL = {"core", "live", "zzz_launch", "pick_agent", "input", "vision", "ui",
         "anchors", "machine", "fingerprint", "slots", "vocab", "disc_cfg",
         "disc_stats", "game_cfg", "journal", "progress", "recovery", "flows",
         "locate", "feishu", "state"}
third = sorted(imports - STD - LOCAL)
print(f"  第三方库：{third}")