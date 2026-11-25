# 以管理员权限重开终端 —— 本项目动游戏前的必需步骤
#
# 为什么必须：没有管理员权限时，Windows 的 UIPI
# （User Interface Privilege Isolation）会静默丢弃所有按键/点击注入。
# 工具不会报错，而是白等到超时（实测 150~254 秒）。
#
# 用法：
#   .\admin.ps1                     重开成管理员终端
#   .\admin.ps1 -Check              只检查当前是不是管理员
#   .\admin.ps1 -Command "python tools/zzz_who.py"   提权后跑一条命令
#
# 原理：检测到自己不是管理员时，用 Start-Process -Verb RunAs 重开自己。

param(
    [switch]$Check,
    [string]$Command = ''
)

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$isAdmin = Test-Admin

if ($Check) {
    if ($isAdmin) {
        Write-Host "✔ 管理员权限：有" -ForegroundColor Green
        exit 0
    }
    Write-Host "⚠ 管理员权限：没有" -ForegroundColor Yellow
    Write-Host "  按键/点击会被 UIPI 静默丢弃，工具会白等到超时。"
    Write-Host "  用：.\admin.ps1"
    exit 1
}

if (-not $isAdmin) {
    Write-Host "⚠ 当前不是管理员，正在提权重开…" -ForegroundColor Yellow
    $self = $MyInvocation.MyCommand.Path
    $here = Split-Path -Parent $self

    # 重新拼参数：把 -Command 带过去
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$self`"")
    if ($Command) {
        $argList += @('-Command', "`"$Command`"")
    }

    try {
        Start-Process -FilePath 'powershell.exe' `
                      -ArgumentList $argList `
                      -WorkingDirectory $here `
                      -Verb RunAs
        Write-Host "✔ 已在新窗口打开管理员终端" -ForegroundColor Green
        exit 0
    } catch {
        Write-Host "✘ 提权失败：$($_.Exception.Message)" -ForegroundColor Red
        Write-Host ""
        Write-Host "  手动做法："
        Write-Host "    1 右键「Windows PowerShell」或「终端」"
        Write-Host "    2 选「以管理员身份运行」"
        Write-Host "    3 cd $here"
        exit 1
    }
}

# ---- 已经是管理员 ----
Write-Host "✔ 管理员权限：有" -ForegroundColor Green
Write-Host ""

$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $root

# 找 python：和 daily.ps1 一致的顺序
$Python = $env:ZZZ_PYTHON
if (-not $Python -and (Test-Path "$root\paths.json")) {
    try {
        $pj = Get-Content "$root\paths.json" -Raw -Encoding utf8 | ConvertFrom-Json
        if ($pj.zzz_python -and (Test-Path $pj.zzz_python)) { $Python = $pj.zzz_python }
    } catch {}
}
if (-not $Python) {
    foreach ($g in @(
        'E:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full',
        'D:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full',
        'C:\OneDragon\ZenlessZoneZero-OneDragon-v2.6.1-Full',
        'E:\OneDragon\ZenlessZoneZero-OneDragon',
        'D:\OneDragon\ZenlessZoneZero-OneDragon',
        'C:\OneDragon\ZenlessZoneZero-OneDragon'
    )) {
        $cand = Join-Path $g '.venv\Scripts\python.exe'
        if (Test-Path $cand) { $Python = $cand; break }
    }
}

Write-Host "  项目：$root"
Write-Host "  python：$(if ($Python) { $Python } else { '✘ 没找到（设 ZZZ_PYTHON 或写 paths.json）' })"
Write-Host ""

# 有 -Command 就跑完退出
if ($Command) {
    if (-not $Python) { Write-Host "✘ 没有 python" -ForegroundColor Red; exit 2 }
    Write-Host "▶ $Command" -ForegroundColor Cyan
    Write-Host ("-" * 62)
    & $Python -u $Command.Split(' ')
    exit $LASTEXITCODE
}

Write-Host "常用命令：" -ForegroundColor Cyan
Write-Host ""
Write-Host "  第一次用"
Write-Host "    python tools/check_config.py                环境自检"
Write-Host "    python tools/zzz_launch.py                  启动游戏"
Write-Host "    python tools/zzz_who.py --scan              扫账号角色，出菜单"
Write-Host ""
Write-Host "  看进度 / 出计划（不动游戏）"
Write-Host "    python tools/zzz_who.py                     列全部角色"
Write-Host "    python tools/zzz_who.py 佩洛伊斯 --history   养成曲线"
Write-Host "    python tools/zzz_disc_daily.py 佩洛伊斯 --offline   今日计划（秒出）"
Write-Host ""
Write-Host "  真跑（会花电量/材料）"
Write-Host "    python tools/zzz_daily.py 佩洛伊斯 --run    跑一轮"
Write-Host "    python tools/zzz_daily.py --from-targets --run   按 targets.json 批量"
Write-Host ""
Write-Host "  自检"
Write-Host "    python tools/run_tests.py                   单元测试"
Write-Host "    python tools/smoke_test.py                  冒烟"
Write-Host "    python tools/audit_ship.py                  干净副本验证"
Write-Host ""
Write-Host "这个窗口已经是管理员，可以直接跑上面的命令。" -ForegroundColor Green
