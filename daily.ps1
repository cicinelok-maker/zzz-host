# 每日养成托管 —— 指定一个角色，跑到毕业
#
# 用法：
#   .\daily.ps1 -List                          先看有哪些角色
#   .\daily.ps1 -Agent 佩洛伊斯                 只算不动游戏
#   .\daily.ps1 -Agent 佩洛伊斯 -Run            真跑一轮
#   .\daily.ps1 -Agent 佩洛伊斯 -Run -UntilGraduated   一直跑到毕业
#
# 注册成每天 19:00 自动跑（用户级任务，不需要管理员）：
#   schtasks /create /tn "ZZZ养成托管" /tr "powershell -NoProfile -ExecutionPolicy Bypass -File \"$PWD\daily.ps1\" -Agent 佩洛伊斯 -Run -UntilGraduated" /sc daily /st 19:00 /f
#
# 跑完后看日志：state\daily.log
# 删除定时任务：schtasks /delete /tn "ZZZ养成托管" /f
#
# ⚠️ 这是 2026-11-25 重写版。旧版引用了已删除的 tools/loop.py 和 data/plan.json，
#    跑起来只会报「找不到文件」。新版改成调 zzz_who / zzz_daily / zzz_grind。

param(
    [string]$Agent = '',
    [switch]$Run,
    [switch]$UntilGraduated,
    [switch]$List,
    [double]$Target = 0,
    [int]$Rounds = 5,
    [string]$Python = ''
)

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$log = Join-Path $here 'state\daily.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

function Say($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

# ---- 找 python
# 顺序：显式传 > 环境变量 > paths.json > OneDragon 常见位置 > 本目录 .venv
# 不能回退到裸 'python' —— Windows 上那可能是 Microsoft Store 的占位程序。
if (-not $Python) { $Python = $env:ZZZ_PYTHON }

if (-not $Python) {
    $paths = Join-Path $here 'paths.json'
    if (Test-Path $paths) {
        try {
            $pj = Get-Content $paths -Raw -Encoding utf8 | ConvertFrom-Json
            if ($pj.zzz_python -and (Test-Path $pj.zzz_python)) {
                $Python = $pj.zzz_python
            }
        } catch {}
    }
}

if (-not $Python) {
    $odGuess = @(
        'E:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full',
        'D:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full',
        'C:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full',
        'E:\OneDragon\ZenlessZoneZero-OneDragon',
        'D:\OneDragon\ZenlessZoneZero-OneDragon',
        'C:\OneDragon\ZenlessZoneZero-OneDragon'
    )
    foreach ($g in $odGuess) {
        $cand = Join-Path $g '.venv\Scripts\python.exe'
        if (Test-Path $cand) { $Python = $cand; break }
    }
}

if (-not $Python) {
    $cand = Join-Path $here '.venv\Scripts\python.exe'
    if (Test-Path $cand) { $Python = $cand }
}

Say '──────────────── 每日养成 ────────────────'

if (-not $Python) {
    Say '✘ 找不到 python。三选一：'
    Say '   1) 参数：-Python "C:\path\to\python.exe"'
    Say '   2) 环境变量：$env:ZZZ_PYTHON = "C:\path\to\python.exe"'
    Say '   3) 写 paths.json（见 paths.example.json）'
    Say '   推荐用 OneDragon 的 .venv\Scripts\python.exe'
    exit 2
}
Say "   python: $Python"

if ($List -or -not $Agent) {
    & $Python -u tools\zzz_who.py
    if (-not $Agent) {
        Say '没指定 -Agent，只列角色。用法：.\daily.ps1 -Agent 佩洛伊斯 -Run'
        exit 0
    }
}

# ---- 校验角色名
Say "① 检查角色：$Agent"
& $Python -u tools\zzz_who.py $Agent 2>&1 | ForEach-Object { Say "   $_" }
if ($LASTEXITCODE -ne 0) {
    Say '   角色名不认识，先跑 .\daily.ps1 -List 看可用列表'
    exit 2
}

# ---- 目标分数
if ($Target -le 0) { $Target = 28 }
Say "② 目标：$Target 条有效词条（小毕业线 28）"

if (-not $Run) {
    Say '③ 计划模式（加 -Run 真跑）'
    & $Python -u tools\zzz_daily.py $Agent 2>&1 | ForEach-Object { Say "   $_" }
    Say '──────────────── 结束（没动游戏）────────────────'
    exit 0
}

# ---- 真跑
if ($UntilGraduated) {
    Say "③ 跑到毕业：最多 $Rounds 轮，目标 $Target"
    & $Python -u tools\zzz_grind.py $Agent --run --target $Target --rounds $Rounds 2>&1 |
        ForEach-Object { Say "   $_" }
} else {
    Say '③ 跑一轮'
    & $Python -u tools\zzz_daily.py $Agent --run 2>&1 | ForEach-Object { Say "   $_" }
}

$code = $LASTEXITCODE
Say '④ 收尾：看进度'
& $Python -u tools\zzz_who.py $Agent 2>&1 | ForEach-Object { Say "   $_" }

Say "──────────────── 结束（exit=$code）────────────────"
exit $code
