<#
.SYNOPSIS
    一键重建 tools/ 下的全部本地运行时（Python / Node）。

.DESCRIPTION
    默认装「当前最新的可用版本」，脚本里不写死任何版本号：
      - Python : python-build-standalone 最新发布里，取 3.14 / 3.15 中最高的补丁版本
                 （源码用了 PEP 758 的无括号 except，3.13 及以下跑不了；3.16 起 pythonnet 没有轮子）
      - Node   : nodejs.org 官方索引里的最新 LTS（-NodeVersion latest 可切到最新正式版）

    视频识别功能已下线（动图只读首帧），因此不再需要 FFmpeg。

    已装版本与最新一致时只跳过本体、不重复下载；Python 的依赖每次都会对齐一遍。
    加 -Force 强制重装。

.PARAMETER Component
    要处理的组件，默认 all（两个都装）。可多选，如 -Component python,node。

.PARAMETER PythonVersion
    指定 Python 版本（3.15 / 3.15.2 都可以）。留空 = 自动取最新兼容版本。

.PARAMETER NodeVersion
    指定 Node 版本（如 v24.21.0）。留空 = 最新 LTS；latest = 最新正式版。

.PARAMETER Force
    即使版本已相同也重新下载安装。

.PARAMETER DryRun
    只解析版本和下载地址，不实际下载。

.PARAMETER IndexUrl
    pip 使用的索引地址，默认清华源。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\setup.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\setup.ps1 -DryRun

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\setup.ps1 -Component node -Force
#>
param(
    [ValidateSet('all', 'python', 'node')]
    [string[]]$Component = 'all',
    [string]$PythonVersion = '',
    [string]$NodeVersion = '',
    [switch]$Force,
    [switch]$DryRun,
    [string]$IndexUrl = 'https://pypi.tuna.tsinghua.edu.cn/simple'
)

$ErrorActionPreference = 'Stop'
# 5.1 的下载进度条会让大文件慢十倍以上，必须关掉。
$ProgressPreference = 'SilentlyContinue'

$tools = $PSScriptRoot
$pythonHome = Join-Path $tools 'python'
$nodeHome = Join-Path $tools 'node'
$pythonRange = '^3\.(14|15)\.'

function Write-Step([string]$text) {
    Write-Host ""
    Write-Host "== $text" -ForegroundColor Cyan
}

function Write-Info([string]$text) {
    Write-Host "   $text"
}

function Get-Json([string]$url) {
    return Invoke-RestMethod -Uri $url -UseBasicParsing -TimeoutSec 120
}

function Get-File([string]$url, [string]$dest) {
    Write-Info "下载 $url"
    # 大文件不用 -TimeoutSec 限死，避免网慢时半途失败。
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    $size = (Get-Item -LiteralPath $dest).Length / 1MB
    Write-Info ("完成 {0:N1} MB" -f $size)
}

function New-TempDir {
    $path = Join-Path ([IO.Path]::GetTempPath()) ('qqbot-setup-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $path -Force | Out-Null
    return $path
}

function Remove-TempDir([string]$path) {
    if (Test-Path -LiteralPath $path) {
        $resolved = (Resolve-Path -LiteralPath $path).Path
        $parent = [IO.Path]::GetDirectoryName($resolved)
        $tempRoot = [IO.Path]::GetTempPath().TrimEnd('\')
        if ($resolved -ne $path -or $parent -ne $tempRoot -or [IO.Path]::GetFileName($resolved) -notmatch '^qqbot-setup-[0-9a-f]{32}$') {
            throw "临时目录路径异常，未删除：$resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Assert-ToolDirectory([string]$path, [string]$name) {
    $expected = [IO.Path]::GetFullPath((Join-Path $tools $name))
    $resolved = (Resolve-Path -LiteralPath $path).Path
    $item = Get-Item -LiteralPath $path -Force
    if ($resolved -ne $expected -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "运行时目录路径异常，未删除：$resolved"
    }
}

function Get-InstalledVersion([string]$dir) {
    $file = Join-Path $dir 'VERSION'
    if (Test-Path -LiteralPath $file -PathType Leaf) {
        return (Get-Content -LiteralPath $file -Raw).Trim()
    }
    return ''
}

function Find-PythonBuild {
    $base = 'https://registry.npmmirror.com/-/binary/python-build-standalone/'
    $dirs = Get-Json $base
    # 发布目录名就是日期，倒序取最近的几个就够了。
    $releases = @(
        $dirs |
            ForEach-Object { $_.name } |
            Where-Object { $_ -match '^\d{8}/$' } |
            ForEach-Object { $_.TrimEnd('/') } |
            Sort-Object -Descending
    )
    if ($releases.Count -eq 0) { throw 'python-build-standalone 镜像里没有找到任何发布目录' }

    $pattern = '^cpython-(?<ver>\d+\.\d+\.\d+)\+\d+-x86_64-pc-windows-msvc-install_only_stripped\.tar\.gz$'
    foreach ($release in ($releases | Select-Object -First 8)) {
        $assets = Get-Json ($base + $release + '/')
        $picked = $null
        foreach ($item in $assets) {
            if ($item.name -notmatch $pattern) { continue }
            $ver = $Matches['ver']
            if ($PythonVersion) {
                if ($ver -ne $PythonVersion -and $ver -notlike "$PythonVersion.*") { continue }
            }
            elseif ($ver -notmatch $pythonRange) {
                continue
            }
            if ($null -eq $picked) {
                $picked = [pscustomobject]@{ Version = $ver; Release = $release; Name = $item.name }
            }
            elseif ([version]$ver -gt [version]$picked.Version) {
                $picked.Version = $ver
                $picked.Name = $item.name
            }
        }
        if ($picked) {
            $picked | Add-Member -NotePropertyName Url -NotePropertyValue ($base + $release + '/' + $picked.Name)
            return $picked
        }
    }
    throw "没有找到匹配的 CPython 构建（要求 $PythonVersion），请检查网络或换一个版本"
}

function Find-NodeBuild {
    $index = Get-Json 'https://nodejs.org/dist/index.json'
    $candidates = @($index | Where-Object { $_.files -contains 'win-x64-zip' })
    if ($candidates.Count -eq 0) { throw 'nodejs.org 索引里没有 Windows x64 版本' }

    if ($NodeVersion -and $NodeVersion -ne 'latest') {
        $hit = $candidates | Where-Object { $_.version -eq $NodeVersion } | Select-Object -First 1
        if (-not $hit) { throw "nodejs.org 上找不到 Node $NodeVersion" }
        return $hit
    }
    if ($NodeVersion -eq 'latest') { return $candidates[0] }

    # 默认 LTS：索引按版本倒序，第一个 lts 为真的就是最新 LTS。
    $lts = $candidates | Where-Object { $_.lts -ne $false } | Select-Object -First 1
    if ($lts) { return $lts }
    return $candidates[0]
}

function Install-PythonBase($plan) {
    $requirements = Join-Path $pythonHome 'requirements.txt'
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw '缺少 tools\python\requirements.txt，依赖清单不能删'
    }
    $temp = New-TempDir
    try {
        $archive = Join-Path $temp 'cpython.tar.gz'
        Get-File $plan.Url $archive
        $expanded = Join-Path $temp 'x'
        New-Item -ItemType Directory -Path $expanded -Force | Out-Null
        Write-Info '解压 CPython…'
        tar -xzf $archive -C $expanded
        if ($LASTEXITCODE -ne 0) { throw '解压 CPython 失败' }
        $payload = Join-Path $expanded 'python'
        if (-not (Test-Path -LiteralPath (Join-Path $payload 'python.exe') -PathType Leaf)) {
            throw '压缩包结构异常：没有 python\python.exe'
        }

        # tools\python 是整个替换掉的，依赖清单先备份出来。
        $kept = Join-Path $temp 'requirements.txt'
        Copy-Item -LiteralPath $requirements -Destination $kept -Force
        if (Test-Path -LiteralPath $pythonHome) {
            Assert-ToolDirectory $pythonHome 'python'
            Remove-Item -LiteralPath $pythonHome -Recurse -Force
        }
        New-Item -ItemType Directory -Path $pythonHome -Force | Out-Null
        Copy-Item -Path (Join-Path $payload '*') -Destination $pythonHome -Recurse -Force
        Copy-Item -LiteralPath $kept -Destination $requirements -Force
        Set-Content -LiteralPath (Join-Path $pythonHome 'VERSION') -Value $plan.Version -Encoding ASCII
    }
    finally {
        Remove-TempDir $temp
    }
}

function Sync-PythonDeps {
    $requirements = Join-Path $pythonHome 'requirements.txt'
    $python = Join-Path $pythonHome 'python.exe'
    Write-Info '对齐 Python 依赖…'
    # --upgrade：清单不写版本号，每次对齐都拉到当前最新。
    & $python -m pip install --upgrade --disable-pip-version-check --no-warn-script-location --index-url $IndexUrl -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'pip install 失败' }
    $actual = & $python -c "import sys; print(sys.version.split()[0])"
    Write-Info "Python $actual 就绪"
}

function Install-Node($plan) {
    $version = $plan.version
    $temp = New-TempDir
    try {
        $zip = Join-Path $temp 'node.zip'
        $url = "https://registry.npmmirror.com/-/binary/node/$version/node-$version-win-x64.zip"
        Get-File $url $zip
        $expanded = Join-Path $temp 'x'
        Write-Info '解压 Node…'
        Expand-Archive -LiteralPath $zip -DestinationPath $expanded -Force
        $payload = Get-ChildItem -LiteralPath $expanded -Directory | Select-Object -First 1
        if (-not $payload) { throw '压缩包结构异常：解压后没有目录' }

        if (Test-Path -LiteralPath $nodeHome) {
            Assert-ToolDirectory $nodeHome 'node'
            Remove-Item -LiteralPath $nodeHome -Recurse -Force
        }
        New-Item -ItemType Directory -Path $nodeHome -Force | Out-Null
        Copy-Item -Path (Join-Path $payload.FullName '*') -Destination $nodeHome -Recurse -Force
        Set-Content -LiteralPath (Join-Path $nodeHome 'VERSION') -Value $version -Encoding ASCII
        $actual = & (Join-Path $nodeHome 'node.exe') -v
        Write-Info "Node $actual 就绪"
    }
    finally {
        Remove-TempDir $temp
    }
}

# ---------------------------------------------------------------- 主流程

if ($Component -contains 'all') {
    $targets = @('python', 'node')
}
else {
    $targets = @($Component)
}

Write-Step "解析最新版本（$($targets -join ' / ')）"

$pythonPlan = $null
$nodePlan = $null

if ($targets -contains 'python') {
    $pythonPlan = Find-PythonBuild
    if ($pythonPlan.Version -notmatch $pythonRange) {
        Write-Warning "Python $($pythonPlan.Version) 超出本项目可用范围（3.14 / 3.15），启动时会被拦下"
    }
    Write-Info "Python  $($pythonPlan.Version)   (发布 $($pythonPlan.Release))"
}
if ($targets -contains 'node') {
    $nodePlan = Find-NodeBuild
    $channel = 'Current'
    if ($nodePlan.lts -ne $false) { $channel = "LTS $($nodePlan.lts)" }
    Write-Info "Node    $($nodePlan.version)   ($channel)"
}

if ($DryRun) {
    Write-Step 'DryRun：仅解析，不下载'
    if ($pythonPlan) { Write-Info "python -> $($pythonPlan.Url)" }
    if ($nodePlan) { Write-Info "node   -> https://registry.npmmirror.com/-/binary/node/$($nodePlan.version)/node-$($nodePlan.version)-win-x64.zip" }
    return
}

if ($pythonPlan) {
    Write-Step 'Python'
    $installed = Get-InstalledVersion $pythonHome
    $hasBinary = Test-Path -LiteralPath (Join-Path $pythonHome 'python.exe') -PathType Leaf
    if ($hasBinary -and $installed -eq $pythonPlan.Version -and -not $Force) {
        Write-Info "已是 $installed，跳过下载"
    }
    else {
        if ($installed) { Write-Info "当前 $installed，升级到 $($pythonPlan.Version)" }
        else { Write-Info "开始安装 $($pythonPlan.Version)" }
        Install-PythonBase $pythonPlan
    }
    # 依赖每次都对一遍：清单改了但 Python 版本没变时也能生效。
    Sync-PythonDeps
}

if ($nodePlan) {
    Write-Step 'Node'
    $installed = Get-InstalledVersion $nodeHome
    $hasBinary = Test-Path -LiteralPath (Join-Path $nodeHome 'node.exe') -PathType Leaf
    if ($hasBinary -and $installed -eq $nodePlan.version -and -not $Force) {
        Write-Info "已是 $installed，跳过"
    }
    else {
        if ($installed) { Write-Info "当前 $installed，升级到 $($nodePlan.version)" }
        else { Write-Info "开始安装 $($nodePlan.version)" }
        Install-Node $nodePlan
    }
}

Write-Step '完成'
foreach ($name in $targets) {
    $folder = Join-Path $tools $name
    $version = Get-InstalledVersion $folder
    if (-not $version) { $version = '未知' }
    Write-Info ("{0,-8} {1}" -f $name, $version)
}
Write-Host ""
