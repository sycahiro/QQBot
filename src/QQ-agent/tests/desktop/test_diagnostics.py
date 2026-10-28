from qqbot.desktop.diagnostics import read_logs
from qqbot.desktop.paths import DesktopPaths


def test_log_tail_is_bounded_and_hides_saved_keys_and_bearer_tokens(tmp_path):
    paths = DesktopPaths(tmp_path, tmp_path)
    paths.logs.mkdir(parents=True)
    file = paths.logs / "desktop.log"
    file.write_text(
        "中文" * 30000
        + "\n"
        + "".join(f"2026 INFO module line {i}\n" for i in range(250))
        + "ERROR model my-private-key Authorization: Bearer token-value\n",
        encoding="utf-8",
    )
    lines = read_logs(paths, ["my-private-key"])
    assert len(lines) == 200 and "line 249" in lines[-2]
    assert "my-private-key" not in "\n".join(lines) and "token-value" not in "\n".join(lines)
    assert "[密钥已隐藏]" in lines[-1]
