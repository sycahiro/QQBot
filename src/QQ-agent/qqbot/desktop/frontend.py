"""从源码生成内存页面；不监听端口，不生成 dist，不保留界面服务。"""

import json
import re
import subprocess
import threading

from .windows import OwnedProcessJob

MAX_OUTPUT = 8 * 1024 * 1024


def _with_theme(html, theme):
    if len(re.findall(r"<head\b[^>]*>", html, re.I)) != 1:
        raise RuntimeError("界面源码缺少唯一的 head 元素，无法初始化主题")
    return re.sub(
        r"<head\b[^>]*>",
        lambda match: (
            match[0] + "<script>window.__QQBOT_THEME__=" + json.dumps(theme) + ";</script>"
        ),
        html,
        count=1,
        flags=re.I,
    )


class FrontendDocument:
    def __init__(self, paths):
        self.paths = paths
        self.html = None
        self.process = None
        self.job = None
        self._reader = None

    def prepare(self, theme="system", *, timeout=45):
        if theme not in ("light", "dark", "system"):
            raise ValueError("无效的初始主题")
        if not self.paths.node.is_file():
            raise RuntimeError("缺少本项目的 Node 工具")
        self.paths.runtime.mkdir(parents=True, exist_ok=True)
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        log_file = self.paths.logs / "frontend.log"
        chunks = []
        overflow = threading.Event()
        try:
            self.job = OwnedProcessJob()
            with log_file.open("ab") as log:
                self.process = subprocess.Popen(
                    [str(self.paths.node), str(self.paths.frontend / "prepare.mjs")],
                    cwd=self.paths.frontend,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.job.assign(self.process)

                def read():
                    size = 0
                    try:
                        while block := self.process.stdout.read(65536):
                            size += len(block)
                            if size > MAX_OUTPUT:
                                overflow.set()
                                self.process.kill()
                                break
                            chunks.append(block)
                    except OSError, ValueError:
                        pass

                reader = self._reader = threading.Thread(
                    target=read, name="frontend-document", daemon=True
                )
                reader.start()
                try:
                    self.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    raise RuntimeError(f"界面源码转换超时，请查看 {log_file}") from None
                reader.join(timeout=5)
                if reader.is_alive() or overflow.is_set() or self.process.returncode != 0:
                    raise RuntimeError(f"界面源码转换失败，请查看 {log_file}")
            try:
                data = json.loads(b"".join(chunks))
                html = data["html"]
                if (
                    not isinstance(html, str)
                    or not html.startswith("<!doctype html>")
                    or len(html.encode()) > 1500000
                ):
                    raise ValueError()
            except ValueError, KeyError, TypeError:
                raise RuntimeError(f"界面源码转换结果无效，请查看 {log_file}") from None
            self.html = _with_theme(html, theme)
            return self.html
        finally:
            self.close()

    def close(self):
        child = self.process
        try:
            if child and child.poll() is None:
                if self.job:
                    self.job.close()
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)
            if self._reader:
                self._reader.join(timeout=5)
            if child and child.stdout:
                child.stdout.close()
        finally:
            if self.job:
                self.job.close()
                self.job = None
