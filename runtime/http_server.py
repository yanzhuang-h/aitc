"""HTTP 数据接收、配置转发、健康检查与轻量前端服务。"""

from __future__ import annotations

import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

from infra.data.classifier import DataKind


class HttpRuntimeServer:
    """管理 HTTP 数据入口，并提供单路口方案查询页面。"""

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
        signal_timing_tool: Any | None = None,
        qwen_agent: Any | None = None,
        control_process_agent: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.ingestor = ingestor
        self.config_service = config_service
        self.query_service = query_service
        self.signal_timing_tool = signal_timing_tool
        self.qwen_agent = qwen_agent
        self.control_process_agent = control_process_agent
        self.logger = logger
        self._stop_event = threading.Event()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._frontend_dir = Path(__file__).resolve().parent.parent / "web"

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
        self._info("HTTP server started on %s:%s", *self.address)

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
                path = urlparse(self.path).path
                body = self._read_json_body()
                if body is None:
                    return

                if path == "/api/signal-timing":
                    self._handle_signal_timing(body)
                    return
                if path == "/api/agent/signal-timing":
                    self._handle_qwen_signal_timing(body)
                    return
                if path == "/api/agent/control-process":
                    self._handle_control_process(body)
                    return
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
                if path in {"/", "/index.html"}:
                    self._send_html(runtime_server._read_frontend_file("index.html"))
                    return
                if path == "/health":
                    self._send_json(200, runtime_server._health_payload())
                    return
                if path == "/api/signal-timing":
                    self._send_json(405, {"error": "Use POST for signal timing requests"})
                    return
                if path == "/api/agent/signal-timing":
                    self._send_json(405, {"error": "Use POST for agent signal timing requests"})
                    return
                if path == "/api/agent/control-process":
                    self._send_json(405, {"error": "Use POST for control process requests"})
                    return
                if path.startswith(("/road_info", "/cross_info")) and self._try_handle_config("GET", None):
                    return
                self._send_json(200, runtime_server._health_payload())

            def _handle_signal_timing(self, body: Any) -> None:
                if not isinstance(body, dict):
                    self._send_json(400, {"error": "Request body must be an object"})
                    return
                try:
                    payload = runtime_server._generate_signal_timing(body)
                except ValueError as error:
                    self._send_json(400, {"error": str(error)})
                    return
                except Exception:
                    runtime_server._error("Error generating signal timing", exc_info=True)
                    self._send_json(500, {"error": "internal server error"})
                    return
                self._send_json(200, payload)

            def _handle_qwen_signal_timing(self, body: Any) -> None:
                if not isinstance(body, dict):
                    self._send_json(400, {"error": "Request body must be an object"})
                    return
                try:
                    payload = runtime_server._generate_qwen_signal_timing(body)
                except ValueError as error:
                    self._send_json(400, {"error": str(error)})
                    return
                except Exception:
                    runtime_server._error("Error generating Qwen signal timing", exc_info=True)
                    self._send_json(500, {"error": "internal server error"})
                    return
                self._send_json(200, payload)

            def _handle_control_process(self, body: Any) -> None:
                if not isinstance(body, dict):
                    self._send_json(400, {"error": "Request body must be an object"})
                    return
                try:
                    payload = runtime_server._generate_control_process(body)
                except ValueError as error:
                    self._send_json(400, {"error": str(error)})
                    return
                except Exception:
                    runtime_server._error("Error generating control process", exc_info=True)
                    self._send_json(500, {"error": "internal server error"})
                    return
                self._send_json(200, payload)

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
                runtime_server._warning(
                    "Blocked cross-origin request: origin=%s host=%s path=%s",
                    origin,
                    host,
                    self.path,
                )
                self._send_json(403, {"error": "Cross-origin requests are not allowed"})
                return True

            def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, html: str) -> None:
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                runtime_server._info("HTTP Server: %s", format % args)

        return RuntimeRequestHandler

    def _health_payload(self) -> dict[str, Any]:
        return {
            "status": "running",
            "service": "aitc_runtime_http",
            "radar_cache_size": self.query_service.get_runtime_size(DataKind.RADAR),
            "data_quality": self.query_service.get_data_quality_snapshot(),
        }

    def _read_frontend_file(self, filename: str) -> str:
        path = self._frontend_dir / filename
        if not path.exists():
            return "<html><body><h1>AITC</h1></body></html>"
        return path.read_text(encoding="utf-8")

    def _generate_signal_timing(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.signal_timing_tool is None:
            raise RuntimeError("signal timing tool is not configured")
        cross_id = body.get("cross_id")
        if not isinstance(cross_id, str) or not cross_id.strip():
            raise ValueError("cross_id must be a non-empty string")
        request_body = dict(body)
        request_body.pop("cross_id", None)
        result = self.signal_timing_tool.generate(cross_id=cross_id.strip(), **request_body)
        return {
            "status": "success",
            "cross_id": cross_id.strip(),
            "result": result,
        }

    def _generate_qwen_signal_timing(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.qwen_agent is None:
            raise RuntimeError("qwen agent is not configured")
        request_text = body.get("request_text")
        cross_id = body.get("cross_id")
        if not isinstance(request_text, str) or not request_text.strip():
            raise ValueError("request_text must be a non-empty string")
        if not isinstance(cross_id, str) or not cross_id.strip():
            raise ValueError("cross_id must be a non-empty string")
        payload = self.qwen_agent.run({"request_text": request_text.strip(), "cross_id": cross_id.strip()})
        return {"status": "success", "cross_id": cross_id.strip(), "result": payload}

    def _generate_control_process(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.control_process_agent is None:
            raise RuntimeError("control process agent is not configured")
        cross_id = body.get("cross_id")
        if not isinstance(cross_id, str) or not cross_id.strip():
            raise ValueError("cross_id must be a non-empty string")
        payload = self.control_process_agent.run({
            "cross_id": cross_id.strip(),
            "request_text": body.get("request_text"),
        })
        return {"status": "success", "cross_id": cross_id.strip(), "result": payload}

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
