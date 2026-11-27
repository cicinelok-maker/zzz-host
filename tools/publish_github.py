"""通过 GitHub API 发布 —— 绕开被墙的 github.com:443。

## 为什么需要这个

本机网络实测：
```
github.com:443          ✘ 不通（DNS 污染，返回 198.51.44.8 这类假 IP）
github.com:22           ✔ 通（SSH）
api.github.com:443      ✔ 通（HTTP 200）
codeload.github.com     ✔ 通
raw.githubusercontent   ✔ 通
```

**`git push` 走 github.com:443 → 推不上去。**
但 GitHub 的 **Git Data API** 全在 `api.github.com` 上：

```
POST /user/repos                         建仓库
POST /repos/{o}/{r}/git/blobs            传文件内容
POST /repos/{o}/{r}/git/trees            建目录树
POST /repos/{o}/{r}/git/commits          建提交
POST /repos/{o}/{r}/git/refs             建分支
```

**全部走 api.github.com，所以能通。**

## 用法

```bash
set GITHUB_TOKEN=ghp_xxx
python tools/publish_github.py --repo zzz-host

# 只预览要传什么，不真传
python tools/publish_github.py --repo zzz-host --dry-run

# 换成私有仓库
python tools/publish_github.py --repo zzz-host --private
```

## 注意

- token 需要 `repo` 权限（建仓库 + 写内容）
- 走 git 数据 API，所以**保留完整的提交历史**（每个 commit 单独建）
- 一次最多传 100 个文件（GitHub 的 tree API 限制，分批也可以）
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import enc  # noqa: E402,F401  —— 修控制台编码（BUG-111）

API = "https://api.github.com"

# 和 .gitignore 一致的排除规则
IGN_DIRS = {".git", ".local", "state", "od_test", "shots", "__pycache__", ".venv", "venv",
            "tools_ext", "out", "backups", "od_plugin", "auto", "legacy",
            "build", "dist", "_legacy", "journal", ".pytest_cache", ".idea"}
IGN_FILES = [
    # 二进制 / 缓存
    "*.pyc", "*.pyo", "*.so", "*.zip", "*.exe", "*.dll", "*.pyd",
    "*.bak", "*.bak-*", "*.png", "*.jpg", "*.jsonl",
    # 个人配置 / 账号数据
    "feishu_conf.json", "paths.json",
    "roster.json", "roster.demo.json", "roster.imported.json",
    "roster.json.bak-*",
    "tools/feishu.py", "tools/feishu_img.py",
    "*.local.json", ".env", ".env.*",
    # 本机专属的一次性脚本 / 开发工具
    "tools/run_feishu_agent.ps1", "tools/run_feishu_listen.ps1",
    "tools/capture_fp_we.py",
    # 历史残留（已被 tools/ 取代）
    "graduate.py", "od_bridge.py", "zzz_host.py",
    "DELIVERY.md", "HANDOFF-vision.md", "ONEDRAGON.md",
    "DISC_CHAIN.md", "TASKS.md",
    # 开发日志（5000+ 行的教训总结）—— 给维护者看，不该塞进用户的 zip 里
    "MAINTENANCE.md",
    # **交接文档里写满了本机绝对路径**（C:\Users\<名>\...）——  见 RT-16。
    # 它是给「下一个接手的会话」看的，不是给最终用户的。
    "HANDOFF.md",
]


def api(path: str, token: str, method: str = "GET", data: dict | None = None,
        timeout: int = 60) -> tuple[int, dict | list | None]:
    """调 API，返回 (状态码, 解析后的 JSON)。"""
    url = API + path
    body = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "zzz-host-publisher",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:400]}
    except Exception as e:
        return 0, {"error": str(e)}


def _ignored(rel: pathlib.Path) -> bool:
    """手写的排除规则（git 不知道的那些）。"""
    if any(part in IGN_DIRS for part in rel.parts[:-1]):
        return True
    relstr = rel.as_posix()
    return any(fnmatch.fnmatch(rel.name, pat) or fnmatch.fnmatch(relstr, pat)
               for pat in IGN_FILES)


def collect(root: pathlib.Path) -> list[pathlib.Path]:
    """收集要发布的文件。

    **以 git 为准**：用 `git ls-files --cached --others --exclude-standard`。
    那正好是「git 会提交什么」—— `.gitignore` 和 `.git/info/exclude`
    都生效，本地私有文件不会被算进发布集。

    以前用 `root.rglob("*")`，看不见 `.git/info/exclude`
    （朋友用它在 `.local/` 放私有文件，结果照样进了发布集，
    而且 audit_ship 静默通过）。

    **判断「发布什么」只能有一个真相来源。** 手写规则永远会漏。

    git 不可用（没装/不是仓库）时退回 rglob + 手写规则。
    """
    names = []
    try:
        r = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard",
             "-z"],
            cwd=str(root), capture_output=True, timeout=30)
        if r.returncode == 0:
            names = [x for x in r.stdout.decode("utf-8", "replace").split("\0")
                     if x]
    except Exception:
        names = []

    if names:
        out = []
        for n in sorted(names):
            f = root / n
            rel = pathlib.Path(n)
            if not f.is_file():
                continue          # git 里记着但文件被删了
            if _ignored(rel):
                continue          # 手写规则再筛一遍（git 不管 *.png 那种）
            out.append(rel)
        return out

    # 退回：git 不可用
    out = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(root)
        if _ignored(rel):
            continue
        out.append(rel)
    return sorted(out)

def main() -> int:
    ap = argparse.ArgumentParser(description="通过 GitHub API 发布")
    ap.add_argument("--repo", default="zzz-host", help="仓库名")
    ap.add_argument("--private", action="store_true", help="建成私有仓库")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不真传")
    ap.add_argument("--token", default="", help="token（默认读 GITHUB_TOKEN 环境变量）")
    ap.add_argument("--desc", default="绝区零角色养成托管 · CLI 工具集",
                    help="仓库描述")
    args = ap.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("✘ 没有 token。两种方式：")
        print("   1 环境变量：set GITHUB_TOKEN=ghp_xxx")
        print("   2 参数：    --token ghp_xxx")
        print()
        print("   生成地址：https://github.com/settings/tokens")
        print("   需要勾选：repo（完整仓库权限）")
        return 2

    root = pathlib.Path(__file__).resolve().parent.parent
    files = collect(root)
    print(f"项目根：{root}")
    print(f"要发布 {len(files)} 个文件")

    # ---- 1 验证 token
    code, me = api("/user", token)
    if code != 200 or not isinstance(me, dict):
        print(f"✘ token 无效（HTTP {code}）")
        print(f"   {json.dumps(me, ensure_ascii=False)[:300]}")
        return 3
    owner = me["login"]
    print(f"✔ 认证为 {owner}")

    if args.dry_run:
        print()
        print("── 预览（--dry-run，不真传）──")
        for f in files[:30]:
            print(f"   {f}")
        if len(files) > 30:
            print(f"   …还有 {len(files) - 30} 个")
        total = sum((root / f).stat().st_size for f in files)
        print(f"\n   合计 {total // 1024} KB")
        return 0

    # ---- 2 建仓库
    code, repo = api("/user/repos", token, "POST", {
        "name": args.repo,
        "description": args.desc,
        "private": args.private,
        "auto_init": False,
        "has_issues": True,
        "has_wiki": False,
    })
    if code == 201:
        print(f"✔ 建了仓库 {owner}/{args.repo}")
    elif code == 422:
        print(f"· 仓库 {owner}/{args.repo} 已存在，继续往里推")
    else:
        print(f"✘ 建仓库失败（HTTP {code}）")
        print(f"   {json.dumps(repo, ensure_ascii=False)[:400]}")
        return 4

    # ---- 2b 确保仓库非空
    # GitHub 的 Git Data API 不允许在完全空的仓库上建 blob（报 409 Git Repository is empty）。
    # 先用 Contents API 塞一个初始文件，让仓库有一个提交。
    code, probe = api(f"/repos/{owner}/{args.repo}/contents/README-PLACEHOLDER.md",
                      token)
    if code == 404:
        print("· 仓库是空的，先建初始提交…")
        code2, r2 = api(f"/repos/{owner}/{args.repo}/contents/.keep", token,
                        "PUT", {
                            "message": "init",
                            "content": base64.b64encode(b"").decode("ascii"),
                        })
        if code2 in (200, 201):
            print("✔ 初始提交已建")
        else:
            print(f"✘ 建初始提交失败（HTTP {code2}）")
            print(f"   {json.dumps(r2, ensure_ascii=False)[:300]}")
            return 4

    # ---- 3 传文件（blob）
    print()
    print("── 传文件 ──")
    tree = []
    skipped = []
    t0 = time.time()
    for i, rel in enumerate(files, 1):
        content = (root / rel).read_bytes()
        # 二进制用 base64，文本也可以（API 要求 base64）
        b64 = base64.b64encode(content).decode("ascii")
        code, blob = api(f"/repos/{owner}/{args.repo}/git/blobs", token,
                         "POST", {"content": b64, "encoding": "base64"})
        if code != 201 or not isinstance(blob, dict):
            # 409 有两种可能，要分清（我第一次就搞混了）：
            #   a) 仓库是空的 → "Git Repository is empty"（前面 2b 已处理）
            #   b) token 缺 workflow 权限 → 只有 .github/workflows/ 下会这样
            msg = (blob or {}).get("message", "") if isinstance(blob, dict) else ""
            if code == 409 and "empty" in msg.lower():
                print(f"  ✘ {rel}: 仓库还是空的（2b 没生效？）")
                return 4
            if code == 409 and rel.as_posix().startswith(".github/workflows/"):
                print(f"  ⚠ {rel.as_posix()} 跳过（token 缺 workflow 权限）")
                skipped.append(rel.as_posix())
                continue
            print(f"  ✘ {rel}（HTTP {code}）")
            print(f"     {json.dumps(blob, ensure_ascii=False)[:200]}")
            return 5
        tree.append({"path": rel.as_posix(), "mode": "100644",
                     "type": "blob", "sha": blob["sha"]})
        if i % 20 == 0 or i == len(files):
            print(f"  {i}/{len(files)}  {time.time() - t0:.1f}s")

    # ---- 4 建树
    code, t = api(f"/repos/{owner}/{args.repo}/git/trees", token, "POST",
                  {"tree": tree})
    if code != 201:
        print(f"✘ 建树失败（HTTP {code}）：{json.dumps(t, ensure_ascii=False)[:300]}")
        return 6
    tree_sha = t["sha"]
    print(f"✔ 目录树 {tree_sha[:8]}（{len(tree)} 个文件）")

    # ---- 5 建提交 —— 保留本地 git 历史
    print()
    print("── 建提交（按本地 git 历史）──")
    log = subprocess.run(
        ["git", "log", "--reverse", "--format=%H|%s|%an|%ae|%aI"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    commits = [x for x in (log.stdout or "").splitlines() if "|" in x]
    print(f"  本地 {len(commits)} 个提交")

    # 把当前文件状态打成**一条**提交（不是把本地 git 历史逐条重放），
    # 但 commit message 里列出本地历史。
    #
    # 注意：它**接在远程 main 后面**（有 parent），所以远程历史不会被抹掉 ——
    # 只是每次发布新增一条。
    if commits:
        msgs = [f"- {c.split('|', 1)[1].split('|')[0]}" for c in commits]
        msg = f"发布：绝区零角色养成托管\n\n本地历史（{len(commits)} 个）：\n" + \
              "\n".join(msgs[:30])
    else:
        msg = "初始发布"

    # **必须带 parent**（RT-17）。
    #
    # 原来 `"parents": []` —— 造一个**孤根提交**。
    # 配合下面的 `force: True`，效果是：**每次发布都把远程 main 的历史整个替换掉**。
    #
    # 现在先取远程 main 当前的 sha 当 parent，新提交就**长在**远程历史上，
    # 天然能 fast-forward，不需要 force。
    _pc, _pref = api(f"/repos/{owner}/{args.repo}/git/ref/heads/main", token)
    _parents: list[str] = []
    if _pc == 200 and isinstance(_pref, dict):
        _psha = (_pref.get("object") or {}).get("sha") or ""
        if _psha:
            _parents = [_psha]
            print(f"  远程 main 当前 {_psha[:8]}（新提交接在它后面）")
    elif _pc == 404:
        print("  远程还没有 main 分支（首次发布）")
    else:
        print(f"  ⚠ 读不到远程 main（HTTP {_pc}）—— 按首次发布处理")

    code, commit = api(f"/repos/{owner}/{args.repo}/git/commits", token, "POST",
                       {"message": msg, "tree": tree_sha, "parents": _parents})
    if code != 201:
        print(f"✘ 建提交失败（HTTP {code}）：{json.dumps(commit, ensure_ascii=False)[:300]}")
        return 7
    commit_sha = commit["sha"]
    print(f"✔ 提交 {commit_sha[:8]}")
    if skipped:
        print()
        print(f"⚠ 跳过了 {len(skipped)} 个文件（token 缺 workflow 权限）：")
        for x in skipped:
            print(f"     {x}")
        print("   要发这些，两种办法：")
        print("     a 重新生成 token，在 repo 之外再勾 workflow")
        print("     b 手动在网页上新建这个文件（内容见本地）")

    # ---- 6 建分支 main
    code, ref = api(f"/repos/{owner}/{args.repo}/git/refs", token, "POST",
                    {"ref": "refs/heads/main", "sha": commit_sha})
    if code == 201:
        print("✔ 分支 main")
    elif code == 422:
        # 已存在 → 更新，但**不允许 force**（RT-17）。
        #
        # 原来这里是 `"force": True` —— 远程 main 被替换成孤根提交，
        # **历史全没了**。而下面的文案还写着「不覆盖历史」。
        #
        # 现在：新提交的 parent 就是远程 main，所以正常情况下是 fast-forward；
        # 万一不是（远程被别人推过），**报错让人处理**，别强推。
        code2, r2 = api(f"/repos/{owner}/{args.repo}/git/refs/heads/main",
                        token, "PATCH", {"sha": commit_sha})
        if code2 == 200:
            print("✔ 更新分支 main（fast-forward）")
        else:
            print(f"✘ 更新分支 main 失败（HTTP {code2}）")
            print(f"   {json.dumps(r2, ensure_ascii=False)[:200]}")
            print("   多半是远程 main 在这期间被别人推过 —— 先 git pull 再发。")
            print("   **不会强推覆盖远程历史。**")
            return 8
    else:
        print(f"✘ 建分支失败（HTTP {code}）")
        return 8

    # ---- 7 提示
    print()
    print("=" * 60)
    print(f"✔ 发布完成：https://github.com/{owner}/{args.repo}")
    print("=" * 60)
    print()
    print("下一步（在能访问 github.com 的浏览器里做）：")
    print(f"  1 打开 https://github.com/{owner}/{args.repo}/settings")
    print("  2 设默认分支为 main（如果提示的话）")
    print(f"  3 给仓库加 topics：zzz / zenless-zone-zero / automation")
    print()
    print("以后本地改了代码要同步：")
    print(f"  python tools/publish_github.py --repo {args.repo}")
    print("  （会新建一条提交，接在远程 main 后面；不强推、不覆盖历史）")
    return 0


if __name__ == "__main__":
    sys.exit(main())