"""Each launch owns its logs; exercise real startup logging without a QQ/window."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from qqbot.desktop.diagnostics import read_logs
from qqbot.desktop.paths import DesktopPaths

ROOT = Path(__file__).resolve().parents[4]


def test_log_reader_reads_only_its_launch_never_old_root_or_other_sessions(tmp_path):
    first = DesktopPaths(ROOT, tmp_path)
    second = DesktopPaths(ROOT, tmp_path)
    assert first.logs != second.logs
    for paths, text in [(first, "first launch"), (second, "second launch")]:
        paths.logs.mkdir(parents=True)
        (paths.logs / "desktop.log").write_text(text, encoding="utf-8")
    (tmp_path / "desktop.log").write_text("legacy launch", encoding="utf-8")
    assert read_logs(first) == ["first launch"]
    assert read_logs(second) == ["second launch"]
    assert read_logs(DesktopPaths(ROOT, tmp_path)) == []


def test_two_real_main_calls_keep_logs_and_pythonw_streams_separate(tmp_path):
    script = r"""
import json,logging,sys
import qqbot.main as app
from qqbot.desktop.diagnostics import read_logs
results=[]
def isolated_run(paths):
    index=len(results)+1
    logging.info('launch-marker-%s',index)
    print('third-party-marker-'+str(index),file=sys.stderr)
    results.append({'session':paths.log_session,'lines':read_logs(paths)})
    return 0
app.run=isolated_run
sys.argv=['qqbot','--runtime',sys.argv[1],'--no-dialog']
original_out,original_err=sys.stdout,sys.stderr
for _ in range(2):
    sys.stdout=sys.stderr=None
    assert app.main()==0
    assert sys.stdout is None and sys.stderr is None
    sys.stdout,sys.stderr=original_out,original_err
print(json.dumps(results))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src" / "QQ-agent")},
    )
    assert result.returncode == 0, result.stderr
    launches = json.loads(result.stdout)
    assert len(launches) == 2 and launches[0]["session"] != launches[1]["session"]
    assert not (tmp_path / "desktop.log").exists() and not (tmp_path / "launcher.log").exists()
    for index, launch in enumerate(launches, 1):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.\d{6}-\d+", launch["session"])
        directory = tmp_path / "logs" / launch["session"]
        text = (directory / "desktop.log").read_text(encoding="utf-8")
        assert f"launch-marker-{index}" in text and f"launch-marker-{3 - index}" not in text
        assert "QQBot 启动" in text and "QQBot 本次运行结束" in text
        assert f"launch-marker-{index}" in "\n".join(launch["lines"])
        assert (directory / "launcher.log").read_text(
            encoding="utf-8"
        ) == f"third-party-marker-{index}\n"
