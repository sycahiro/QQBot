"""Exercise the single-file installer's clean-install paths without network access."""

import hashlib
import io
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")


def run_installer_functions(tmp_path, extra):
    source = (ROOT / "Install.bat").read_text(encoding="utf-8")
    payload = source.rsplit(":__QQBOT_POWERSHELL__", 1)[1]
    prefix = payload.split("Write-Step '检查系统与运行时'", 1)[0]
    script = tmp_path / "exercise.ps1"
    script.write_text(prefix + "\n" + extra, encoding="utf-8-sig")
    env = os.environ.copy()
    # Keep PowerShell 5.1 from importing unrelated PowerShell 7 modules injected
    # into the test runner's environment.
    env["PSModulePath"] = str(
        Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "Modules"
    )
    env["QQBOT_INSTALL_FILE"] = str(tmp_path / "project" / "Install.bat")
    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        env=env,
        check=False,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def quoted(path):
    return str(path).replace("'", "''")


def test_python_install_keeps_requirements_outside_runtime(tmp_path):
    project = tmp_path / "project"
    tools = project / "tools"
    runtime = tools / "python"
    runtime.mkdir(parents=True)
    (runtime / "old-runtime.txt").write_text("old", encoding="utf-8")
    requirements = tools / "requirements.txt"
    requirements.write_text("pywebview\n", encoding="utf-8")
    archive = tmp_path / "python.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        item = tarfile.TarInfo("python/python.exe")
        content = b"fixture interpreter"
        item.size = len(content)
        tar.addfile(item, io.BytesIO(content))
    extra = f"""
function Get-File([string]$url, [string]$dest) {{ Copy-Item -LiteralPath '{quoted(archive)}' -Destination $dest }}
Install-PythonBase @{{ Url = 'fixture'; Version = '3.15.2' }}
"""
    run_installer_functions(tmp_path, extra)
    assert requirements.read_text(encoding="utf-8") == "pywebview\n"
    assert (runtime / "python.exe").read_bytes() == b"fixture interpreter"
    assert not (runtime / "old-runtime.txt").exists()
    assert not (runtime / "requirements.txt").exists()


def test_snowluma_install_checks_hash_and_preserves_existing(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    archive = tmp_path / "snowluma.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("index.mjs", "fixture")
        zip_file.writestr("package.json", '{}')
        zip_file.writestr("native/snowluma-win32-x64.node", b"fixture")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    extra = f"""
$script:fixtureHash = '{'0' * 64}'
function SnowLuma-Release {{ return @{{ Version = 'fixture'; Url = 'fixture'; Hash = $script:fixtureHash }} }}
function Invoke-WebRequest {{ param($Uri, $OutFile, [switch]$UseBasicParsing) Copy-Item -LiteralPath '{quoted(archive)}' -Destination $OutFile }}
try {{ Install-SnowLuma; throw 'Unexpected success with wrong hash' }} catch {{ if ($_.Exception.Message -notmatch 'SHA-256') {{ throw }} }}
if (Test-Path -LiteralPath $engine) {{ throw 'Invalid archive was installed' }}
$script:fixtureHash = '{digest}'
Install-SnowLuma
Install-SnowLuma
"""
    run_installer_functions(tmp_path, extra)
    assert (project / "src" / "SnowLuma" / "index.mjs").read_text(encoding="utf-8") == "fixture"
