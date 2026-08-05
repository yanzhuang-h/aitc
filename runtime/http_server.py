"""HTTP 雷达接收、配置转发与健康检查服务。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

from infra.data.classifier import DataKind


class HttpRuntimeServer:
    """管理 HTTP 数据入口，保持协议层与数据底座解耦。"""

    _BLOCKED_CORS_HEADERS = {
        "access-control-allow-origin",
        "access-control-allow-credentials",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-expose-headers",
        "access-control-max-age",
    }
    _SECURITY_HEADERS = {
        "X-Permitted-Cross-Domain-Policies": "none",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Strict-Transport-Security": "max-age=16070400; includeSubDomains",
        "X-XSS-Protection": "1; mode=block",
        "X-Download-Options": "noopen",
    }

    def __init__(
        self,
        *,
        host: str,
        port: int,
        ingestor: Any,
        config_service: Any,
        query_service: Any,
        logger: Any | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.ingestor = ingestor
        self.config_service = config_service
        self.query_service = query_service
        self.logger = logger
        self._stop_event = threading.Event()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None:
            return self.host, self.port
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        """在后台线程启动 HTTP 服务。"""
        if self._server is not None:
            return
        self._stop_event.clear()
        self._server = HTTPServer((self.host, self.port), self._build_handler())
        self._server.timeout = 1.0
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._info("Radar HTTP server started on %s:%s", *self.address)

    def stop(self) -> None:
        self._stop_event.set()
        if self._server is not None:
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop_event.is_set():
            try:
                self._server.handle_request()
            except OSError:
                if not self._stop_event.is_set():
                    self._error("HTTP server request handling failed", exc_info=True)
                break

    def _build_handler(self):
        runtime_server = self

        class RuntimeRequestHandler(BaseHTTPRequestHandler):
            server_version = "AITCServer"
            sys_version = ""

            def send_header(self, keyword, value):
                if keyword.lower() in runtime_server._BLOCKED_CORS_HEADERS:
                    return
                super().send_header(keyword, value)

            def end_headers(self):
                for header, value in runtime_server._SECURITY_HEADERS.items():
                    self.send_header(header, value)
                super().end_headers()

            def do_OPTIONS(self):
                if self._reject_cross_origin_request():
                    return
                self.send_response(204)
                self.end_headers()

            def do_POST(self):
                if self._reject_cross_origin_request():
                    return
                body = self._read_json_body()
                if body is None:
                    return

                path = urlparse(self.path).path
                if path.startswith(("/road_info", "/cross_info")) and self._try_handle_config("POST", body):
                    return
                if not isinstance(body, (dict, list)):
                    self._send_json(400, {"error": "Unsupported radar data format"})
                    return

                try:
                    runtime_server.ingestor.ingest_http(body)
                except Exception:
                    runtime_server._error("Error processing radar data", exc_info=True)
                    self._send_json(500, {"error": "internal server error"})
                    return
                self._send_json(200, {"status": "success", "message": "Radar data received"})

            def do_GET(self):
                if self._reject_cross_origin_request():
                    return
                path = urlparse(self.path).path
                if path.startswith(("/road_info", "/cross_info")) and self._try_handle_config("GET", None):
                    return
                self._send_json(
                    200,
                    {
                        "status": "running",
                        "service": "radar_data_receiver",
                        "radar_cache_size": runtime_server.query_service.get_runtime_size(DataKind.RADAR),
                    },
                )

            def _read_json_body(self):
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length == 0:
                    self._send_json(400, {"error": "Empty request body"})
                    return None
                try:
                    return json.loads(self.rfile.read(content_length).decode("utf-8"))
                except json.JSONDecodeError as error:
                    self._send_json(400, {"error": f"Invalid JSON: {error}"})
                    return None

            def _try_handle_config(self, method, body) -> bool:
                try:
                    outcome = runtime_server.config_service.handle_request(method, urlparse(self.path).path, body)
                except Exception:
                    runtime_server._error("Error in config API handler", exc_info=True)
                    self._send_json(500, {"status": "error", "reason": "internal server error"})
                    return True
                if outcome is None:
                    return False
                status_code, payload = outcome
                self._send_json(status_code, payload)
                return True

            def _reject_cross_origin_request(self) -> bool:
                origin = self.headers.get("Origin")
                host = self.headers.get("Host")
                if not runtime_server._is_cross_origin_request(origin, host):
                    return False
                runtime_server._warning("Blocked cross-origin request: origin=%s host=%s path=%s", origin, host, self.path)
                self._send_json(403, {"error": "Cross-origin requests are not allowed"})
                return True

            def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                runtime_server._info("HTTP Radar Server: %s", format % args)

        return RuntimeRequestHandler

    @staticmethod
    def _is_cross_origin_request(origin: str | None, host: str | None) -> bool:
        if not origin:
            return False
        try:
            origin_host = (urlparse(origin).netloc or "").lower()
        except ValueError:
            return True
        return not origin_host or origin_host != (host or "").lower()

    def _info(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.info(message, *args)

    def _warning(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)

    def _error(self, message: str, *args: Any, **kwargs: Any) -> None:
        if self.logger is not None:
            self.logger.error(message, *args, **kwargs)
