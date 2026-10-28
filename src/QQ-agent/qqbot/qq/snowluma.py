"""SnowLuma 独立服务客户端：替代旧的 Node 引擎子进程。

分层（与浏览器控制台同构）：
    管理面  HTTP 127.0.0.1:5099 + Bearer token —— 进程发现、load/unload
    数据面  OneBot 11 —— HTTP 3000 发动作，正向 WS 3001 收事件

服务是全局单例（SnowLuma 内部按 QQ 号管理数据库），不随单次连接起停；
桌面进程退出时由 SnowLumaDiscovery.close() 统一回收。
对外接口覆盖 connection.py / bridge.py 需要的引擎能力（发现、接管、动作、事件）。
"""

import base64
import json
import logging
import os
import queue
import secrets as pysecrets
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import httpx

from ..desktop.windows import OwnedProcessJob
from .discovery import DiscoveryError
from .engine import EngineError

logger = logging.getLogger(__name__)

WEBUI_PORT = 5099
ONEBOT_HTTP_PORT = 3000
ONEBOT_WS_PORT = 3001
START_TIMEOUT = 30.0

MANAGE_ROUTES = {
    ("GET", "/api/processes"),
    ("GET", "/api/qq-list"),
    ("GET", "/api/connections"),
    ("GET", "/api/system"),
    ("GET", "/api/agreements"),
    ("POST", "/api/agreements/record-consent"),
}

# onebot.json 的受控默认值：端口固定、token 由本端生成，避免首启时序问题。
ONEBOT_DEFAULT_CONFIG = {
    "networks": {
        "httpServers": [{
            "name": "http-default", "host": "127.0.0.1", "port": ONEBOT_HTTP_PORT,
            "path": "/", "enableWebSocket": False, "accessToken": None,
            "messageFormat": "array", "reportSelfMessage": False,
        }],
        "httpClients": [],
        "wsServers": [{
            "name": "ws-default", "host": "127.0.0.1", "port": ONEBOT_WS_PORT,
            "path": "/", "role": "Universal", "accessToken": None,
            "messageFormat": "array", "reportSelfMessage": False,
        }],
        "wsClients": [],
    },
    "statusCommand": {"enabled": False, "swallow": False, "cooldownSeconds": 5, "trigger": "#sl"},
    "historySync": {"enabled": False},
    "notifications": {"channelIds": []},
}


def _http_error(response):
    """SnowLuma 错误响应统一为 {error:{code,message}}；响应体非该形状时带原文片段。"""
    try:
        detail = response.json()
    except ValueError:
        body = response.text[:200].replace("\n", " ")
        return EngineError(
            f"HTTP_{response.status_code}", f"SnowLuma 返回 HTTP {response.status_code}: {body}"
        )
    error = detail.get("error") or {}
    code = str(error.get("code") or f"HTTP_{response.status_code}")
    message = str(error.get("message") or f"SnowLuma 返回 HTTP {response.status_code}")
    return EngineError(code, message)


class SnowLumaService:
    """SnowLuma 守护进程生命周期：spawn → 登录 → 协议确认；幂等可复用。"""

    def __init__(self, paths):
        self._paths = paths
        self._lock = threading.Lock()
        self._child = None
        self._job = None
        self._origin = None
        self._token = None
        self._password = None
        self._onebot_token = None
        self._stage = "stopped"
        self._stage_error = None

    # -- 状态 ------------------------------------------------------------

    def status(self):
        stage, error = self._stage, self._stage_error
        # _stage 只在 ensure/stop 回写；子进程意外退出时以存活状态实时纠正，
        # 避免顶栏绿点与真实状态矛盾。
        if stage == "running" and not self.running:
            stage, error = "error", "SnowLuma 进程已意外退出，请重新启动引擎"
        return {"stage": stage, "error": error}

    @property
    def running(self):
        # 不拿锁：ensure() 持锁期间会调本属性，threading.Lock 不可重入会死锁。
        # 字段读取在 GIL 下原子，无竞态风险。
        child = self._child
        return child is not None and child.poll() is None and bool(self._token)

    @property
    def onebot_token(self):
        return self._onebot_token

    # -- 生命周期 ----------------------------------------------------------

    def ensure(self, timeout=START_TIMEOUT):
        with self._lock:
            if self.running:
                self._stage = "running"
                return
            self._stage, self._stage_error = "starting", None
            try:
                self._prepare_home()
                self._spawn()
                self._wait_listening(timeout)
                self._login()
                self._record_consent()
            except EngineError as error:
                self._stage, self._stage_error = "error", error.message
                raise
            except Exception as error:
                # OSError / JSONDecodeError 等不能逃逸，否则 stage 永久停在 starting。
                self._stage, self._stage_error = "error", f"引擎启动失败：{error}"
                raise EngineError("START_FAILED", self._stage_error) from error
            self._stage = "running"

    def _prepare_home(self):
        home = self._paths.snowluma_home
        (home / "config").mkdir(parents=True, exist_ok=True)
        self._paths.snowluma_data.mkdir(parents=True, exist_ok=True)
        (self._paths.runtime / "logs" / "snowluma").mkdir(parents=True, exist_ok=True)
        # 服务凭据：首次生成后固定，重启 SnowLuma 也沿用同一密码。
        secret_file = self._paths.runtime / "secrets" / "snowluma-service.json"
        if not secret_file.exists():
            secret_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = secret_file.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"password": "Aa1!" + pysecrets.token_urlsafe(32)}),
                encoding="utf-8",
            )
            os.replace(temporary, secret_file)
        self._password = json.loads(secret_file.read_text(encoding="utf-8"))["password"]
        # OneBot 网络与 token：文件缺失才写，已有配置（含用户手工改过的）一律尊重。
        onebot_file = home / "config" / "onebot.json"
        if onebot_file.exists():
            self._onebot_token = self._read_onebot_token(onebot_file)
        else:
            self._onebot_token = pysecrets.token_urlsafe(32)
            config = json.loads(json.dumps(ONEBOT_DEFAULT_CONFIG))
            config["networks"]["httpServers"][0]["accessToken"] = self._onebot_token
            config["networks"]["wsServers"][0]["accessToken"] = self._onebot_token
            temporary = onebot_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
            os.replace(temporary, onebot_file)

    @staticmethod
    def _read_onebot_token(onebot_file: Path):
        try:
            config = json.loads(onebot_file.read_text(encoding="utf-8"))
            networks = config.get("networks") or {}
            token = ((networks.get("wsServers") or [{}])[0].get("accessToken")) or (
                (networks.get("httpServers") or [{}])[0].get("accessToken")
            )
            return token or ""
        except (OSError, ValueError):
            raise EngineError("ONEBOT_CONFIG", "OneBot 配置无法读取，请检查 config/onebot.json")

    def _spawn(self):
        node = self._paths.node
        entry = self._paths.snowluma_entry
        if not node.is_file():
            raise EngineError("MISSING_NODE", "缺少 Node 运行工具（tools/node）")
        if not entry.is_file():
            raise EngineError("MISSING_ENGINE", "缺少 SnowLuma 服务入口（src/SnowLuma）")
        log_directory = self._paths.runtime / "logs" / "snowluma"
        env = os.environ | {
            "SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD": self._password,
            "SNOWLUMA_WEBUI_HOST": "127.0.0.1",
            "SNOWLUMA_WEBUI_PORT": str(WEBUI_PORT),
            "SNOWLUMA_WEBUI_TLS": "0",
            "SNOWLUMA_WEBUI_TRUST_PROXY": "",
            "SNOWLUMA_UPDATE_ROOT": "",
            "SNOWLUMA_HOOK_AUTOLOAD": "0",
            "SNOWLUMA_ACCEPT_EULA": "0",
            "SNOWLUMA_ACCEPT_PRIVACY": "0",
            "SNOWLUMA_LOG_DIR": str(log_directory),
            "QQBOT_MANAGED_SNOW": "1",
        }
        self._child = subprocess.Popen(
            [str(node), str(entry)],
            cwd=self._paths.snowluma_home,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._job = OwnedProcessJob()
        self._job.assign(self._child)

    def _wait_listening(self, timeout):
        # readline 是无限阻塞的，必须放到线程里读，主线程按 deadline 收口；
        # 否则 node 启动卡死（例如完整性标签错误）会让检测永远停在「正在检测」。
        lines = queue.Queue()

        def drain():
            try:
                for line in iter(self._child.stdout.readline, b""):
                    lines.put(line)
            except (OSError, ValueError):
                pass

        reader = threading.Thread(target=drain, name="snowluma-startup", daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        buffer = ""
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=1.0)
            except queue.Empty:
                if self._child.poll() is not None:
                    raise EngineError(
                        "ENGINE_EXITED",
                        f"SnowLuma 在就绪前退出（code={self._child.returncode}），请查看运行日志",
                    )
                continue
            buffer += line.decode("utf-8", "replace")
            if "listening http://127.0.0.1:" in buffer:
                return
        raise EngineError("START_TIMEOUT", "SnowLuma 启动超时，请查看运行日志")

    def _client(self):
        return httpx.Client(base_url=self._origin, timeout=20.0)

    def _login(self):
        self._origin = f"http://127.0.0.1:{WEBUI_PORT}"
        with self._client() as client:
            response = client.post(
                "/api/login", json={"password": self._password}, headers={"origin": self._origin}
            )
            if response.status_code != 200:
                raise _http_error(response)
            result = response.json()
            if result.get("mustChangePassword"):
                raise EngineError("SNOW_AUTH", "SnowLuma 登录状态需要处理，请先用 WebUI 完成初始化")
            token = result.get("token")
            if not token:
                raise EngineError("SNOW_AUTH", "SnowLuma 登录未返回会话令牌")
            self._token = token

    def _record_consent(self):
        """版本化协议确认：body 必须携带 GET /api/agreements 返回的当前 version。"""
        payload = self.request("GET", "/api/agreements")
        version = payload.get("version") if isinstance(payload, dict) else None
        if not version or payload.get("consentRequired") is False:
            return
        self.request("POST", "/api/agreements/record-consent", {"version": version})

    # -- 管理面 ----------------------------------------------------------

    def request(self, method, route, body=None, timeout=20.0):
        if (method, route) not in MANAGE_ROUTES and not route.startswith("/api/processes/"):
            raise EngineError("SNOW_ROUTE", f"不支持的 SnowLuma 管理操作：{method} {route}")
        if not self.running:
            raise EngineError("SNOW_STOPPED", "SnowLuma 服务未运行")
        headers = {"authorization": f"Bearer {self._token}", "origin": self._origin}
        try:
            with httpx.Client(base_url=self._origin, timeout=timeout) as client:
                response = client.request(method, route, json=body if body is not None else {}, headers=headers)
        except httpx.HTTPError as error:
            raise EngineError("NETWORK_ERROR", f"SnowLuma 管理请求失败：{error}") from error
        if response.status_code >= 400:
            raise _http_error(response)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    def processes(self):
        result = self.request("GET", "/api/processes")
        items = result.get("list") if isinstance(result, dict) else None
        return items if isinstance(items, list) else []

    def load(self, pid, expected_uin, timeout=45.0):
        try:
            result = self.request(
                "POST", f"/api/processes/{pid}/load", {"expectedUin": expected_uin}, timeout=timeout
            )
        except EngineError as error:
            # 幂等：已被接管（含本端或控制台接管）不算失败，身份一致性由调用方轮询复核。
            if error.code != "SNOW_PROCESS_ACTIVE":
                raise
        else:
            # SnowLuma 用 HTTP 200 + success:false 表示接管失败；解析真实原因，
            # 不要降级成超时后的"请确认 QQ 已登录"误导文案。
            if isinstance(result, dict) and result.get("success") is False:
                process = result.get("process") or {}
                reason = str(process.get("error") or process.get("status") or "原因未知")
                raise EngineError("ATTACH_FAILED", f"接管 QQ 进程失败：{reason}")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for item in self.processes():
                if item.get("pid") != pid:
                    continue
                # 与 list_processes 同一规则：顶层 uin 未接管时是占位 "0"。
                top = str(item.get("uin") or "")
                uin = top if top not in ("", "0") else str((item.get("account") or {}).get("uin") or "")
                if uin and uin != expected_uin:
                    raise EngineError("IDENTITY_MISMATCH", "该 QQ 进程已被其他账号接管，请刷新后重试")
                if item.get("loggedIn") and item.get("connected"):
                    return item
            time.sleep(1.0)
        raise EngineError("ATTACH_TIMEOUT", "接管 QQ 进程超时，请确认 QQ 已登录后重试")

    def unload(self, pid, timeout=40.0):
        try:
            self.request("POST", f"/api/processes/{pid}/unload", {}, timeout=timeout)
        except EngineError as error:
            if error.code not in ("SNOW_PROCESS_ACTIVE", "NOT_FOUND", "HTTP_404"):
                raise

    # -- 回收 ------------------------------------------------------------

    def stop(self):
        with self._lock:
            child, self._child = self._child, None
            job, self._job = self._job, None
            self._token = None
            self._origin = None
            self._stage = "stopped"
        if child and child.poll() is None:
            try:
                child.terminate()
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
            except OSError:
                pass
        if job:
            job.close()


_VERSION_CACHE = {}  # pid -> (monotonic, version)；TTL 短，防 PID 复用错标。
_VERSION_TTL = 300.0
_POWERSHELL = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"),
    "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
)


def _read_versions(pids):
    """照抄旧引擎 process-identity：Get-Process -Id 取 ProductVersion，失败返回空。"""
    versions = {}
    now = time.monotonic()
    for pid in pids:
        cached = _VERSION_CACHE.get(pid)
        if cached and now - cached[0] < _VERSION_TTL:
            if cached[1]:
                versions[pid] = cached[1]
            continue
        script = (
            "$ErrorActionPreference='Stop'; "
            f"$qqProcess=Get-Process -Id {pid}; "
            "if ($qqProcess.ProcessName -ne 'QQ') { throw 'Not a QQ main process' }; "
            "$qqProcess.ProductVersion"
        )
        try:
            completed = subprocess.run(
                [_POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                timeout=6,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            version = completed.stdout.decode("utf-8-sig").strip() or None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            version = None
        _VERSION_CACHE[pid] = (now, version)
        if version:
            versions[pid] = version
    return versions


class SnowLumaDiscovery:
    """进程发现：与旧 QqDiscovery 同接口，数据来自 SnowLuma 管理面。

    服务生命周期是显式的：用户在页面上手动启动（与浏览器控制台一致），
    list_processes 不再隐式拉起服务。
    """

    def __init__(self, paths):
        self._paths = paths
        self._service = SnowLumaService(paths)

    @property
    def service(self):
        return self._service

    def service_status(self):
        return self._service.status()

    def stop_service(self):
        """手动停止常驻服务；下次检测前需要重新启动。"""
        self._service.stop()
        return self.service_status()

    def start_service(self, timeout=START_TIMEOUT):
        try:
            self._service.ensure(timeout=timeout)
        except EngineError as error:
            raise DiscoveryError(error.code, error.message) from error
        return self.service_status()

    def list_processes(self, timeout=20):
        if not self._service.running:
            raise DiscoveryError("SERVICE_STOPPED", "SnowLuma 服务未启动，请先在「连接」页启动引擎")
        try:
            items = self._service.processes()
        except EngineError as error:
            raise DiscoveryError(error.code, error.message) from error
        result = []
        for item in items:
            account = item.get("account") or {}
            # 顶层 uin 只有注入接管后才有值，未接管时是占位 "0"；
            # 登录身份以 SnowLuma 从进程内存读到的 account 为准。
            top = str(item.get("uin") or "")
            uin = top if top not in ("", "0") else str(account.get("uin") or "")
            pid = item.get("pid")
            ready = bool(uin)
            if not isinstance(pid, int) or pid <= 0:
                continue
            result.append({
                "pid": pid,
                "processKey": f"{pid}:{uin}",
                "account": {"uin": uin, "nickname": str(account.get("nickname") or "")},
                "accountAmbiguous": False,
                "version": None,
                "identityReady": ready,
            })
        # SnowLuma 不回报客户端版本：照抄旧引擎按 pid 读 ProductVersion。
        versions = _read_versions([item["pid"] for item in result])
        for item in result:
            item["version"] = versions.get(item["pid"])
        return result

    def close(self):
        self._service.stop()


class _WebSocket:
    """RFC6455 最小客户端：明文 ws://、文本帧、ping/pong；只为本机 OneBot 服务。"""

    def __init__(self, host, port, path="/", headers=None, timeout=10.0):
        self._socket = socket.create_connection((host, port), timeout=timeout)
        self._socket.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = [f"GET {path} HTTP/1.1", f"Host: {host}:{port}", "Upgrade: websocket",
                   "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        request += [f"{name}: {value}" for name, value in (headers or {}).items()]
        self._socket.sendall(("\r\n".join(request) + "\r\n\r\n").encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise EngineError("ONEBOT_HANDSHAKE", "OneBot WS 握手被对端关闭")
            response += chunk
        head, _, rest = response.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise EngineError("ONEBOT_HANDSHAKE", f"OneBot WS 握手被拒绝：{status.decode('ascii', 'replace')}")
        self._buffer = rest

    def _read_exact(self, size):
        while len(self._buffer) < size:
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def recv_text(self, timeout=30.0):
        """返回下一条文本消息；ping 自动回 pong，close 抛 ConnectionError。"""
        self._socket.settimeout(timeout)
        while True:
            first, second = self._read_exact(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            payload = self._read_exact(length) if length else b""
            if opcode == 0x9:  # ping → pong
                self._send_control(0xA, payload)
                continue
            if opcode == 0x8:  # close
                raise ConnectionError("closed")
            if opcode in (0x1, 0x2, 0x0):
                return payload.decode("utf-8", "replace")

    def _send_control(self, opcode, payload):
        header = bytearray([0x80 | opcode, 0x80 | len(payload)]) + os.urandom(4)
        masked = bytes(byte ^ header[2 + index % 4] for index, byte in enumerate(payload))
        try:
            self._socket.sendall(bytes(header) + masked)
        except OSError:
            pass

    def close(self):
        try:
            self._socket.close()
        except OSError:
            pass


class SnowLumaEngine:
    """EngineClient 同形适配：attach/action/detach/事件队列，底层走 SnowLuma。"""

    def __init__(self, paths, *, service=None, max_events=256):
        self._paths = paths
        self._service = service or SnowLumaService(paths)
        self._lock = threading.Lock()
        self._state = "new"
        self._closed = False
        self._target = None
        self._events = queue.Queue(maxsize=max_events)
        self._ws = None
        self._reader = None
        self._failure = None

    @property
    def pid(self):
        return None  # SnowLuma 是共享服务，不再有 per-connection 子进程。

    @property
    def service(self):
        return self._service

    def start(self, timeout=15):
        with self._lock:
            if self._state == "running":
                return
            if self._closed:
                raise EngineError("CLOSED", "连接已经关闭")
        # 服务由用户在页面手动启动；连接时不隐式拉起。
        if not self._service.running:
            raise EngineError("SNOW_STOPPED", "SnowLuma 服务未启动，请先在「连接」页启动引擎")
        with self._lock:
            if self._closed:
                raise EngineError("CLOSED", "连接已经关闭")
            self._state = "running"

    def request(self, method, params=None, timeout=45):
        if method == "account.attach":
            return self._attach(params or {}, timeout)
        if method == "account.detach":
            return self._detach(timeout)
        if method == "account.action":
            return self._action(params or {}, timeout)
        if method == "engine.action_docs":
            return {"actions": "OneBot 11 标准动作；业务侧仅允许白名单动作。"}
        raise EngineError("UNKNOWN_METHOD", f"引擎不支持的操作：{method}")

    def _attach(self, target, timeout):
        uin = str(target.get("uin") or "")
        pid = target.get("pid")
        if not uin or not isinstance(pid, int):
            raise EngineError("INVALID_ACCOUNT", "接管目标缺少 pid 或 uin")
        self._service.load(pid, uin, timeout=timeout)
        with self._lock:
            closed = self._closed
            if not closed:
                self._target = dict(target)
        if closed:
            self._service.unload(pid, timeout=timeout)
            raise EngineError("CLOSED", "连接已经关闭")
        token = self._service.onebot_token or ""
        try:
            ws = _WebSocket(
                "127.0.0.1", ONEBOT_WS_PORT,
                headers={"Authorization": f"Bearer {token}"} if token else None,
            )
        except OSError as error:
            raise EngineError("ONEBOT_DISCONNECTED", f"OneBot 连接失败：{error}") from error
        with self._lock:
            if self._closed:
                ws.close()
                raise EngineError("CLOSED", "连接已经关闭")
            self._ws = ws
        self._reader = threading.Thread(
            target=self._read_events, args=(ws,), name="onebot-events", daemon=True
        )
        self._reader.start()
        return {"ready": True, "database": None, "selected": dict(target)}

    def _detach(self, timeout):
        with self._lock:
            target, self._target = self._target, None
        if target and isinstance(target.get("pid"), int):
            self._service.unload(target["pid"], timeout=timeout)
        return {"detached": True}

    def _action(self, payload, timeout):
        action = str(payload.get("action") or "")
        if not action:
            raise EngineError("INVALID_ACTION", "动作名为空")
        token = self._service.onebot_token or ""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = httpx.post(
                f"http://127.0.0.1:{ONEBOT_HTTP_PORT}/{action}",
                json=payload.get("params") or {},
                headers=headers,
                timeout=timeout,
            )
        except httpx.HTTPError as error:
            raise EngineError("ACTION_NETWORK", f"OneBot 动作请求失败：{action}") from error
        if response.status_code >= 400:
            raise EngineError("ACTION_HTTP", f"OneBot 动作返回 HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError:
            raise EngineError("ACTION_RESPONSE", "OneBot 动作响应不是 JSON")
        if result.get("retcode") not in (0, None) or result.get("status") not in ("ok", "async", None):
            message = str(result.get("wording") or result.get("message") or f"retcode={result.get('retcode')}")
            raise EngineError("ACTION_FAILED", f"{action} 失败：{message}")
        return {"status": "ok", "data": result.get("data")}

    def next_event(self, timeout=0.5):
        return self._events.get(timeout=timeout)

    def _read_events(self, ws):
        target_uin = None
        try:
            while True:
                try:
                    text = ws.recv_text(timeout=1.0)
                except socket.timeout:
                    with self._lock:
                        if self._closed:
                            return
                        target_uin = str((self._target or {}).get("uin") or "")
                    continue
                except (ConnectionError, OSError) as error:
                    raise EngineError("ONEBOT_DISCONNECTED", f"OneBot 连接已断开：{error}") from error
                try:
                    payload = json.loads(text)
                except ValueError:
                    continue
                with self._lock:
                    if self._closed:
                        return
                    target_uin = str((self._target or {}).get("uin") or "")
                if not target_uin:
                    continue
                if str(payload.get("self_id") or "") not in ("", target_uin):
                    logger.warning("Discarded OneBot event from a different QQ account")
                    continue
                self._push({"event": "qq.event", "data": {"accountUin": target_uin, "event": payload}})
        except EngineError as error:
            with self._lock:
                if not self._closed:
                    self._failure = error
                    self._push({"event": "engine.state", "data": {"ready": False, "error": error.message}})

    def _push(self, event):
        try:
            self._events.put_nowait(event)
        except queue.Full:
            logger.warning("Event queue full; dropping oldest event")
            try:
                self._events.get_nowait()
                self._events.put_nowait(event)
            except (queue.Empty, queue.Full):
                pass

    def close(self, timeout=40):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            ws, self._ws = self._ws, None
            target, self._target = self._target, None
        if target and isinstance(target.get("pid"), int) and self._service.running:
            try:
                self._service.unload(target["pid"], timeout=timeout)
            except EngineError as error:
                logger.warning("Unload on close failed: %s", error.message)
        if ws:
            ws.close()
        if self._reader:
            self._reader.join(timeout=2)
        with self._lock:
            self._state = "closed"
