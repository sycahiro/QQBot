@echo off
setlocal EnableExtensions
set "QQBOT_INSTALL_FILE=%~f0"
set "QQBOT_INSTALL_DRY=0"
if /I "%~1"=="--dry-run" set "QQBOT_INSTALL_DRY=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $env:PSModulePath=$env:SystemRoot+'\System32\WindowsPowerShell\v1.0\Modules;'+$env:PSModulePath; $s=[IO.File]::ReadAllText($env:QQBOT_INSTALL_FILE,[Text.Encoding]::UTF8); $m=':__QQBOT_POWERSHELL__'; $i=$s.LastIndexOf($m); if ($i -lt 0) { throw 'Missing installer payload' }; & ([scriptblock]::Create($s.Substring($i+$m.Length))) -DryRun:($env:QQBOT_INSTALL_DRY -eq '1') } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
set "QQBOT_INSTALL_EXIT=%errorlevel%"
if "%QQBOT_INSTALL_NOPAUSE%"=="1" exit /b %QQBOT_INSTALL_EXIT%
if not "%QQBOT_INSTALL_EXIT%"=="0" echo Installation failed. See the message above.
pause
exit /b %QQBOT_INSTALL_EXIT%
:__QQBOT_POWERSHELL__
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$projectRoot = [IO.Path]::GetDirectoryName($env:QQBOT_INSTALL_FILE)
if (-not $projectRoot) { throw '无法定位项目目录' }
$tools = Join-Path $projectRoot 'tools'
$pythonHome = Join-Path $tools 'python'
$nodeHome = Join-Path $tools 'node'
$pythonRange = '^3\.(14|15)\.'
$PythonVersion = ''
$IndexUrl = 'https://pypi.tuna.tsinghua.edu.cn/simple'
$engine = Join-Path $projectRoot 'src\SnowLuma'
$nodeDir = Join-Path $projectRoot 'tools\node'
$python = Join-Path $projectRoot 'tools\python\python.exe'
$pythonw = Join-Path $projectRoot 'tools\python\pythonw.exe'
$frontend = Join-Path $projectRoot 'src\DesktopShell'

function Write-Step([string]$message) {
    Write-Host "`n== $message" -ForegroundColor Cyan
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

function Install-PythonBase($plan) {
    $requirements = Join-Path $tools 'requirements.txt'
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw '缺少 tools\requirements.txt，依赖清单不能删'
    }
    $temp = New-TempDir
    try {
        $archive = Join-Path $temp 'cpython.tar.gz'
        Get-File $plan.Url $archive
        $expanded = Join-Path $temp 'x'
        New-Item -ItemType Directory -Path $expanded -Force | Out-Null
        Write-Info '解压 CPython…'
        & "$env:SystemRoot\System32\tar.exe" -xzf $archive -C $expanded
        if ($LASTEXITCODE -ne 0) { throw '解压 CPython 失败' }
        $payload = Join-Path $expanded 'python'
        if (-not (Test-Path -LiteralPath (Join-Path $payload 'python.exe') -PathType Leaf)) {
            throw '压缩包结构异常：没有 python\python.exe'
        }

        if (Test-Path -LiteralPath $pythonHome) {
            Assert-ToolDirectory $pythonHome 'python'
            Remove-Item -LiteralPath $pythonHome -Recurse -Force
        }
        New-Item -ItemType Directory -Path $pythonHome -Force | Out-Null
        Copy-Item -Path (Join-Path $payload '*') -Destination $pythonHome -Recurse -Force
        Set-Content -LiteralPath (Join-Path $pythonHome 'VERSION') -Value $plan.Version -Encoding ASCII
    }
    finally {
        Remove-TempDir $temp
    }
}

function Sync-PythonDeps {
    $requirements = Join-Path $tools 'requirements.txt'
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


function Latest-Node24 {
    $versions = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json' -UseBasicParsing -TimeoutSec 60
    $version = $versions | Where-Object { $_.version -match '^v24\.' -and $_.files -contains 'win-x64-zip' } | Select-Object -First 1
    if (-not $version -or [version]($version.version.TrimStart('v')) -lt [version]'24.22.1') {
        throw '未找到兼容的 Node 24 Windows x64 版本'
    }
    return $version.version
}

function Assert-SnowLuma {
    if (Test-Path -LiteralPath $engine) {
        if (-not (Test-Path -LiteralPath (Join-Path $engine 'index.mjs') -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $engine 'package.json') -PathType Leaf)) {
            throw "SnowLuma 目录已存在但不完整，请重新按 README 说明解压完整的发行包：$engine"
        }
        Write-Host 'SnowLuma 已就绪。'
        return
    }
    throw (@"
未找到 SnowLuma 引擎。SnowLuma 不随本仓库分发，需要手动安装：

  1. 打开发行页 https://github.com/SnowLuma/SnowLuma/releases
  2. 下载最新发行版中的 Windows 轻量包：SnowLuma-vX.X.X-win-x64-lite.zip
  3. 解压，把压缩包内的全部内容放进项目目录的 src\SnowLuma\
     （放好后应能直接看到 src\SnowLuma\index.mjs 和 src\SnowLuma\package.json）
  4. 重新运行本安装脚本继续

详见 README 的「安装 SnowLuma」一节。
"@)
}

function Get-WebViewVersion {
    $id = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    $paths = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$id",
        "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$id"
    )
    foreach ($path in $paths) {
        $item = Get-ItemProperty -LiteralPath $path -ErrorAction SilentlyContinue
        if ($item -and $item.pv) {
            try { if ([version]$item.pv -gt [version]'0.0.0.0') { return $item.pv } } catch { }
        }
    }
    return $null
}

function Install-WebView2 {
    $installed = Get-WebViewVersion
    if ($installed) { Write-Host "WebView2 $installed 已安装。"; return }
    if ($DryRun) { Write-Host 'WebView2 缺失：将安装微软官方运行时。'; return }
    $installer = Join-Path ([IO.Path]::GetTempPath()) ('qqbot-webview2-' + [guid]::NewGuid().ToString('N') + '.exe')
    try {
        Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $installer -UseBasicParsing
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'CN=Microsoft Corporation') {
            throw 'WebView2 安装器的微软数字签名验证失败'
        }
        $process = Start-Process -FilePath $installer -ArgumentList '/silent', '/install' -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0 -or -not (Get-WebViewVersion)) {
            throw "WebView2 安装未完成（代码 $($process.ExitCode)），请检查系统权限或网络"
        }
        Write-Host 'WebView2 已安装。'
    }
    finally { Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue }
}

function Create-Launcher {
    if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw '缺少 pythonw.exe，无法创建启动快捷方式' }
    $entry = Join-Path $frontend 'start.py'
    $icon = Join-Path $frontend 'frontend\public\qqbot.ico'
    $linkPath = Join-Path $projectRoot 'QQBot.lnk'
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $linkPath) {
        $existing = $shell.CreateShortcut($linkPath)
        if ($existing.TargetPath -ne $pythonw -or $existing.Arguments -ne ('-B "' + $entry + '"')) {
            throw "项目目录已有其他 QQBot 快捷方式，未覆盖：$linkPath"
        }
    }
    $shortcut = $shell.CreateShortcut($linkPath)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = '-B "' + $entry + '"'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = 'QQBot 桌面助手'
    $shortcut.IconLocation = $icon + ',0'
    $shortcut.Save()
    Write-Host '已创建项目目录的 QQBot 快捷方式：双击即可无控制台启动。'
}

Write-Step '检查系统与运行时'
if (-not [Environment]::Is64BitOperatingSystem) { throw 'QQBot 需要 64 位 Windows' }
Assert-SnowLuma
$nodeVersion = Latest-Node24
Write-Host "选择 Node $nodeVersion（与项目的 Node 24 要求一致）"
$pythonPlan = Find-PythonBuild
Write-Host "选择 Python $($pythonPlan.Version)（发布 $($pythonPlan.Release)）"
if ($DryRun) {
    Write-Host "Python 下载地址：$($pythonPlan.Url)"
    Write-Host "Node 下载地址：https://registry.npmmirror.com/-/binary/node/$nodeVersion/node-$nodeVersion-win-x64.zip"
    Install-WebView2
    Write-Host 'DryRun：不修改任何文件。'
    return
}
Write-Step 'Python 与依赖'
$installedPython = Get-InstalledVersion $pythonHome
if ((Test-Path -LiteralPath $python -PathType Leaf) -and $installedPython -eq $pythonPlan.Version) {
    Write-Host "Python $installedPython 已安装。"
} else {
    Install-PythonBase $pythonPlan
}
Sync-PythonDeps

Write-Step 'Node.js'
$installedNode = Get-InstalledVersion $nodeHome
if ((Test-Path -LiteralPath (Join-Path $nodeHome 'node.exe') -PathType Leaf) -and $installedNode -eq $nodeVersion) {
    Write-Host "Node $installedNode 已安装。"
} else {
    Install-Node @{ version = $nodeVersion }
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python 安装未完成' }
$node = Join-Path $nodeDir 'node.exe'
$npm = Join-Path $nodeDir 'npm.cmd'
if (-not (Test-Path -LiteralPath $npm -PathType Leaf)) { throw 'Node 安装缺少 npm' }

Write-Step '安装前端依赖'
$previousPath = $env:PATH
try {
    $env:PATH = $nodeDir + ';' + $previousPath
    & $npm --prefix $frontend install --no-package-lock --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
}
finally { $env:PATH = $previousPath }

Write-Step '确认 SnowLuma'
Assert-SnowLuma

Write-Step '检查运行环境'
$semver = Join-Path $nodeDir 'node_modules\npm\node_modules\semver'
$engineManifest = Join-Path $engine 'package.json'
& $node -e 'const s=require(process.argv[1]),f=process.getBuiltinModule(String.fromCharCode(102,115)),p=JSON.parse(f.readFileSync(process.argv[2]));if(p.engines&&p.engines.node&&!s.satisfies(process.version,p.engines.node))process.exit(1)' $semver $engineManifest
if ($LASTEXITCODE -ne 0) { throw 'SnowLuma 与 Node 版本检查失败，已保留原文件' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖检查失败' }
& $node (Join-Path $frontend 'frontend\prepare.mjs') | Out-Null
if ($LASTEXITCODE -ne 0) { throw '前端构建失败，请检查前端依赖' }

Write-Step '检查桌面运行时'
Install-WebView2

Write-Step '创建启动入口'
Create-Launcher
Write-Host "`n安装完成。双击项目目录的 QQBot 快捷方式启动。"
Write-Host '联网搜索需要系统 Microsoft Edge；QQ 需要另行安装并登录。'
