param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$projectRoot = $PSScriptRoot
$engine = Join-Path $projectRoot 'src\SnowLuma'
$nodeDir = Join-Path $projectRoot 'tools\node'
$python = Join-Path $projectRoot 'tools\python\python.exe'
$pythonw = Join-Path $projectRoot 'tools\python\pythonw.exe'
$frontend = Join-Path $projectRoot 'src\DesktopShell'

function Write-Step([string]$message) {
    Write-Host "`n== $message" -ForegroundColor Cyan
}

function Latest-Node24 {
    $versions = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json' -UseBasicParsing -TimeoutSec 60
    $version = $versions | Where-Object { $_.version -match '^v24\.' -and $_.files -contains 'win-x64-zip' } | Select-Object -First 1
    if (-not $version -or [version]($version.version.TrimStart('v')) -lt [version]'24.22.1') {
        throw '未找到兼容的 Node 24 Windows x64 版本'
    }
    return $version.version
}

function SnowLuma-Release {
    try {
        $headers = @{ 'User-Agent' = 'QQBot-Setup'; 'Accept' = 'application/vnd.github+json' }
        $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/SnowLuma/SnowLuma/releases/latest' -Headers $headers -UseBasicParsing -TimeoutSec 60
        $assets = @($release.assets | Where-Object { $_.name -match '^SnowLuma-v[0-9][A-Za-z0-9.\-]*-win-x64-lite\.zip$' })
        if ($assets.Count -ne 1 -or $assets[0].digest -notmatch '^sha256:[0-9a-fA-F]{64}$') { throw '官方发行信息缺少唯一的 Windows 轻量版或 SHA-256' }
        if ($assets[0].browser_download_url -notmatch '^https://github\.com/SnowLuma/SnowLuma/releases/download/') { throw '官方发行包下载地址无效' }
        return @{ Version = $release.tag_name; Url = $assets[0].browser_download_url; Hash = $assets[0].digest.Substring(7) }
    }
    catch {
        # GitHub unauthenticated API can rate-limit. This official release was
        # verified against its release metadata; keep it only as a fallback.
        Write-Warning '无法查询官方最新发行信息，将使用已验证的 SnowLuma v2.2.1。'
        return @{
            Version = 'v2.2.1'
            Url = 'https://github.com/SnowLuma/SnowLuma/releases/download/v2.2.1/SnowLuma-v2.2.1-win-x64-lite.zip'
            Hash = '29e11c07978f2e970ad918a574650573b74f8ee796e6fa39747dbfb5f74c08f6'
        }
    }
}

function Install-SnowLuma {
    if (Test-Path -LiteralPath $engine) {
        if (-not (Test-Path -LiteralPath (Join-Path $engine 'index.mjs') -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $engine 'package.json') -PathType Leaf)) {
            throw "SnowLuma 目录已存在但不完整，已保留原目录：$engine"
        }
        Write-Host 'SnowLuma 已存在，保留现有发行包。'
        return
    }
    $release = SnowLuma-Release
    Write-Host "SnowLuma $($release.Version)（官方 Windows x64 Lite）"
    if ($DryRun) { return }
    $scratch = Join-Path ([IO.Path]::GetTempPath()) ('qqbot-snowluma-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $scratch -ErrorAction Stop | Out-Null
    try {
        $archive = Join-Path $scratch 'snowluma.zip'
        $expanded = Join-Path $scratch 'package'
        Invoke-WebRequest -Uri $release.Url -OutFile $archive -UseBasicParsing
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $release.Hash) { throw 'SnowLuma 压缩包 SHA-256 校验失败' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($archive)
        try {
            foreach ($item in $zip.Entries) {
                if ($item.FullName -match '(^/|^[A-Za-z]:|\\|(^|/)\.\.(/|$))') { throw 'SnowLuma 压缩包包含无效路径' }
            }
        }
        finally { $zip.Dispose() }
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded
        if (-not (Test-Path -LiteralPath (Join-Path $expanded 'index.mjs') -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $expanded 'native\snowluma-win32-x64.node') -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $expanded 'package.json') -PathType Leaf)) {
            throw 'SnowLuma 发行包结构不符合预期，未安装'
        }
        if (Test-Path -LiteralPath $engine) { throw 'SnowLuma 目录在安装期间已出现，未覆盖' }
        $sourcePath = (Resolve-Path -LiteralPath $expanded).Path
        $destinationPath = [IO.Path]::GetFullPath($engine)
        $expectedDestination = [IO.Path]::GetFullPath((Join-Path $projectRoot 'src\SnowLuma'))
        if ($sourcePath -ne $expanded -or $destinationPath -ne $expectedDestination) { throw 'SnowLuma 安装路径异常，未移动文件' }
        Move-Item -LiteralPath $sourcePath -Destination $destinationPath -ErrorAction Stop
        Write-Host 'SnowLuma 已安装。'
    }
    finally {
        if (Test-Path -LiteralPath $scratch) {
            $resolved = (Resolve-Path -LiteralPath $scratch).Path
            if ($resolved -eq $scratch -and [IO.Path]::GetDirectoryName($resolved) -eq [IO.Path]::GetTempPath().TrimEnd('\')) {
                Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
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
$nodeVersion = Latest-Node24
Write-Host "选择 Node $nodeVersion（与项目的 Node 24 要求一致）"
if ($DryRun) {
    & (Join-Path $projectRoot 'tools\setup.ps1') -NodeVersion $nodeVersion -DryRun
    Install-SnowLuma
    Install-WebView2
    Write-Host 'DryRun：不修改任何文件。'
    return
}
& (Join-Path $projectRoot 'tools\setup.ps1') -NodeVersion $nodeVersion
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

Write-Step '准备 SnowLuma'
Install-SnowLuma

Write-Step '检查运行环境'
$semver = Join-Path $nodeDir 'node_modules\npm\node_modules\semver'
$engineManifest = Join-Path $engine 'package.json'
& $node (Join-Path $projectRoot 'tools\check-snowluma.cjs') $semver $engineManifest
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
