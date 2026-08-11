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
        agent_harness: Any | None = None,
        signal_timing_tool: Any | None = None,
        qwen_agent: Any | None = None,
        control_process_agent: Any | None = None,
        green_wave_service: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.ingestor = ingestor
        self.config_service = config_service
        self.query_service = query_service
        self.green_wave_service = green_wave_service
        self.logger = logger
        if agent_harness is None:
            # 兼容旧调用：未显式提供 harness 时，用旧参数自动装配统一门面
            from agent.harness import AgentHarness

            agent_harness = AgentHarness(
                signal_timing_tool=signal_timing_tool,
                qwen_agent=qwen_agent,
                control_process_agent=control_process_agent,
                logger=logger,
            )
        self.agent_harness = agent_harness
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
                if path == "/green_wave/validate":
                    self._handle_green_wave_post("validate", body)
                    return
                if path == "/green_wave/update":
                    self._handle_green_wave_post("update", body)
                    return
                if path == "/green_wave/delete":
                    self._handle_green_wave_post("delete", body)
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

            def do_PATCH(self):
                if self._reject_cross_origin_request():
                    return
                path = urlparse(self.path).path
                body = self._read_json_body()
                if body is None:
                    return
                if path.startswith("/green_wave/") and path.endswith("/enabled"):
                    segment = path[len("/green_wave/"):-len("/enabled")]
                    self._handle_green_wave_patch(segment, body)
                    return
                self._send_json(404, {"error": "not found"})

            def do_DELETE(self):
                if self._reject_cross_origin_request():
                    return
                path = urlparse(self.path).path
                if path.startswith("/green_wave/"):
                    segment = path[len("/green_wave/"):]
                    if segment in ("validate", "update", "delete"):
                        self._send_json(405, {"error": f"Method DELETE not allowed for /green_wave/{segment}"})
                        return
                    self._send_json(501, {"error": "彻底删除暂未实现：请改用 POST /green_wave/delete 停用，或由 lib 新增删除函数"})
                    return
                self._send_json(404, {"error": "not found"})

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
                if path == "/api/green-wave/status":
                    self._send_json(200, runtime_server._green_wave_status())
                    return
                if path == "/api/green-wave/config":
                    self._send_json(200, runtime_server._green_wave_config())
                    return
                if path == "/api/green-wave/plan":
                    self._send_json(200, runtime_server._green_wave_plan())
                    return
                if path.startswith("/api/green-wave/config/"):
                    self._send_json(200, runtime_server._green_wave_config(path.rsplit("/", 1)[-1]))
                    return
                if path == "/green_wave":
                    parsed = urlparse(self.path)
                    full = bool(parsed.query) and "false" not in parsed.query.lower()
                    self._send_json(200, runtime_server._green_wave_list(full=full))
                    return
                if path.startswith("/green_wave/"):
                    segment = path[len("/green_wave/"):]
                    if segment in ("validate", "update", "delete"):
                        self._send_json(405, {"error": f"Use POST for /green_wave/{segment}"})
                        return
                    self._send_json(200, runtime_server._green_wave_get(segment))
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

            def _handle_green_wave_post(self, action: str, body: Any) -> None:
                if not isinstance(body, dict):
                    self._send_json(400, {"error": "Request body must be an object"})
                    return
                try:
                    if action == "validate":
                        payload = runtime_server._green_wave_validate(body)
                    elif action == "update":
                        payload = runtime_server._green_wave_update(body)
                    else:
                        payload = runtime_server._green_wave_delete(body)
                except ValueError as error:
                    self._send_json(400, {"error": str(error)})
                    return
                except Exception:
                    runtime_server._error("Error handling green wave " + action, exc_info=True)
                    self._send_json(500, {"error": "internal server error"})
                    return
                self._send_json(200, payload)

            def _handle_green_wave_patch(self, segment: str, body: Any) -> None:
                if not isinstance(body, dict):
                    self._send_json(400, {"error": "Request body must be an object"})
                    return
                try:
                    payload = runtime_server._green_wave_set_enabled(segment, body)
                except ValueError as error:
                    self._send_json(400, {"error": str(error)})
                    return
                except Exception:
                    runtime_server._error("Error handling green wave patch", exc_info=True)
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
        return self.agent_harness.handle("signal_timing", body)

    def _generate_qwen_signal_timing(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.agent_harness.handle("agent.signal_timing", body)

    def _generate_control_process(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.agent_harness.handle("control_process", body)

    def _green_wave_status(self) -> dict[str, Any]:
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.status()

    def _green_wave_config(self, corridor_id: str | None = None) -> dict[str, Any]:
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.config(corridor_id)

    def _green_wave_plan(self) -> dict[str, Any]:
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.plan()

    def _green_wave_list(self, full: bool = False) -> dict[str, Any]:
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.list_corridors(full=full)

    def _green_wave_get(self, segment_id: str) -> dict[str, Any]:
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.get_corridor(segment_id)

    def _green_wave_validate(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ValueError("Request body must be an object")
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.validate_corridor(body)

    def _green_wave_update(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ValueError("Request body must be an object")
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.update_corridor(body)

    def _green_wave_delete(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or "corridor_id" not in body:
            raise ValueError("Request body must contain corridor_id")
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.delete_corridor(str(body["corridor_id"]))

    def _green_wave_set_enabled(self, segment_id: str, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or "enabled" not in body or not isinstance(body["enabled"], bool):
            raise ValueError("Request body must contain boolean enabled")
        if self.green_wave_service is None:
            raise RuntimeError("green wave service is not configured")
        return self.green_wave_service.set_corridor_enabled(segment_id, body["enabled"])

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
