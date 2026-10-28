"""Read installed dependency metadata for the About page, without network access."""

import json
import os
import subprocess
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def _python_packages(paths):
    direct = {}
    development = False
    for line in (paths.root / "tools" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#"):
            if "开发" in line:
                development = True
            continue
        if line:
            direct[canonicalize_name(Requirement(line).name)] = "development" if development else "direct"
    items = []
    for distribution in metadata.distributions():
        meta = distribution.metadata
        name = meta.get("Name")
        if not name:
            continue
        license_name = meta.get("License-Expression")
        if not license_name:
            classifiers = meta.get_all("Classifier") or []
            license_name = next((value.rsplit(" :: ", 1)[-1] for value in classifiers if value.startswith("License ::")), None)
        if not license_name:
            license_name = meta.get("License") or "未提供"
        license_name = license_name.strip().splitlines()[0][:120] or "未提供"
        items.append({"name": name, "version": distribution.version, "license": license_name, "kind": direct.pop(canonicalize_name(name), "installed")})
    items.extend({"name": name, "version": "未安装", "license": "未提供", "kind": kind} for name, kind in direct.items())
    return sorted(items, key=lambda item: item["name"].casefold())


def _node_packages(paths):
    manifest = json.loads((paths.root / "src" / "DesktopShell" / "package.json").read_text(encoding="utf-8"))
    direct = {name: "direct" for name in manifest.get("dependencies", {})}
    direct.update({name: "development" for name in manifest.get("devDependencies", {})})
    found = set()
    items = []
    roots = (paths.frontend / "node_modules", paths.frontend.parent / "node_modules")
    for root in roots:
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if not name.startswith(".") and name not in ("test", "tests", "docs", "examples")]
            if "package.json" not in files:
                continue
            dirs[:] = [name for name in dirs if name == "node_modules"]
            try:
                package = json.loads((Path(folder) / "package.json").read_text(encoding="utf-8"))
                name, version = package.get("name"), package.get("version")
                if not isinstance(name, str) or not isinstance(version, str) or (name, version) in found:
                    continue
                found.add((name, version))
                license_name = package.get("license")
                if not isinstance(license_name, str):
                    license_name = "未提供"
                items.append({"name": name, "version": version, "license": license_name[:120], "kind": direct.get(name, "installed")})
            except (OSError, ValueError, TypeError):
                continue
    present = {item["name"] for item in items}
    items.extend({"name": name, "version": "未安装", "license": "未提供", "kind": kind} for name, kind in direct.items() if name not in present)
    return sorted(items, key=lambda item: (item["name"].casefold(), item["version"]))


def inventory(paths):
    try:
        result = subprocess.run([str(paths.node), "--version"], capture_output=True, text=True, timeout=5, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        node_version = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        node_version = None
    return {"pythonPackages": _python_packages(paths), "nodePackages": _node_packages(paths), "nodeVersion": node_version}
