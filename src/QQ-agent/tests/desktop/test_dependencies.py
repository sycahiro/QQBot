import json
from types import SimpleNamespace

from qqbot.desktop import dependencies
from qqbot.desktop.paths import DesktopPaths


def test_inventory_reads_manifests_and_installed_packages(tmp_path, monkeypatch):
    paths = DesktopPaths(tmp_path, tmp_path / "runtime")
    requirements = tmp_path / "tools" / "requirements.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text("httpx\n# 开发检查工具\npytest\n", encoding="utf-8")
    manifest = tmp_path / "src" / "DesktopShell" / "package.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"dependencies": {"react": "1", "missing": "1"}, "devDependencies": {"vite": "1"}}), encoding="utf-8")
    for name, version in [("react", "1.0"), ("vite", "2.0"), ("extra", "3.0")]:
        folder = paths.frontend / "node_modules" / name
        folder.mkdir(parents=True)
        (folder / "package.json").write_text(json.dumps({"name": name, "version": version, "license": "MIT"}), encoding="utf-8")
    parent_package = paths.frontend.parent / "node_modules" / "parent-only"
    parent_package.mkdir(parents=True)
    (parent_package / "package.json").write_text(
        json.dumps({"name": "parent-only", "version": "5.0", "license": "ISC"}), encoding="utf-8"
    )
    dist = SimpleNamespace(metadata={"Name": "httpx", "License-Expression": "BSD-3-Clause"}, version="4.0")
    monkeypatch.setattr(dependencies.metadata, "distributions", lambda: [dist])
    monkeypatch.setattr(dependencies.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="v24.0\n"))
    result = dependencies.inventory(paths)
    py = {item["name"]: item for item in result["pythonPackages"]}
    node = {item["name"]: item for item in result["nodePackages"]}
    assert result["nodeVersion"] == "v24.0"
    assert py["httpx"]["kind"] == "direct" and py["httpx"]["license"] == "BSD-3-Clause"
    assert py["pytest"]["kind"] == "development" and py["pytest"]["version"] == "未安装"
    assert node["react"]["kind"] == "direct" and node["vite"]["kind"] == "development"
    assert node["extra"]["kind"] == "installed" and node["missing"]["version"] == "未安装"
    assert node["parent-only"]["version"] == "5.0"


def test_official_project_pages_are_whitelisted_and_open_in_browser(tmp_path, monkeypatch):
    from qqbot.desktop.bridge import DesktopBridge

    bridge = DesktopBridge(DesktopPaths(tmp_path, tmp_path / "runtime"), lambda **_: None)
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, new=0: opened.append((url, new)) or True)
    expected = {
        "python": "https://www.python.org/",
        "node": "https://nodejs.org/",
        "snowluma": "https://snowluma.github.io/",
    }
    for key, url in expected.items():
        assert bridge.open_project_page(key) == {"ok": True, "url": url}
    assert opened == [(url, 2) for url in expected.values()]
    for value in ("https://example.com", "unknown", None, [], 1):
        assert bridge.open_project_page(value)["error"]["code"] == "INVALID_INPUT"
    assert len(opened) == 3
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: False)
    assert "浏览器" in bridge.open_project_page("python")["error"]["message"]
