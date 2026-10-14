"""最终验收的真实报文格式及本地传输测试设施，不访问远端模型或生产端口。"""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
from unittest.mock import Mock, patch

from app.config import ControlAgentSettings, RuntimeSettings, TrafficMemorySettings
from infra.data.classifier import DataKind, DataSource
from runtime.application import create_application


VIDEO_INTERSECTION = "1300068"
RADAR_INTERSECTION = "1300271"
RADAR_DEVICE = "radar-ximenzi-333-01"


def source_payloads(now):
    """报文字段与生产映射一致；沿用 Phase 4 既有测试输入。"""
    return (
        (DataKind.FLOW, DataSource.TCP, {
            "ycsb_xsfx": "L", "jtll_ddbh": "1", "ycsb_cdbh": "0", "ts": now * 1000,
        }),
        (DataKind.QUEUE, DataSource.TCP, {
            "jtll_ddbh": "1", "start_time": now * 1000,
            "car_nums": [{"ycsb_cdbh": "0", "queue": 12, "all": 18}],
        }),
        (DataKind.RADAR, DataSource.HTTP, {"deviceNo": RADAR_DEVICE, "speed": 32}),
    )


@contextmanager
def acceptance_application(*, provider="disabled", base_url="", timeout=1.0):
    with tempfile.TemporaryDirectory(prefix="aitc-acceptance-") as directory:
        root = Path(directory)
        logger = Mock()
        app = create_application(logger=logger, settings=RuntimeSettings(
            llm_enabled=provider != "disabled", model_provider=provider,
            llm_model="acceptance-model", llm_base_url=base_url, llm_api_key="acceptance-test-key",
            runtime_data_dir=root / "history", runtime_output_dir=root / "output",
            prediction_data_dir=root / "prediction", control_snapshot_dir=root / "snapshot",
            enable_config_sync=False, enable_prediction_scheduler=False, enable_experience_pool_scheduler=False,
            traffic_memory=TrafficMemorySettings(memory_window=2),
            control_agent=ControlAgentSettings(enabled=provider != "disabled", timeout_seconds=timeout),
        ))
        app.decision_pipeline.worker_count = 1
        try:
            yield app, logger
        finally:
            app.stop()


@contextmanager
def model_endpoint(mode="review"):
    """真实本地 HTTP 边界；回复脚本只用于验收，不属于生产 provider。"""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.reply(200, {"data": [{"id": "acceptance-model"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "body": body, "authorization": self.headers.get("Authorization")})
            if mode == "unavailable":
                self.reply(503, {"error": "acceptance service unavailable"})
                return
            if mode == "timeout":
                threading.Event().wait(0.2)
            context = json.loads(body["messages"][-1]["content"])
            if mode == "invalid_action":
                action = {"tool": "set_phase_time", "arguments": {"seconds": 37}}
            elif context["phase"] == "planner":
                action = {"tool": "run_control_policy", "arguments": {}}
            else:
                action = {"tool": "review_signal_plan", "arguments": {"decision": "ACCEPT", "reason": "Keep original policy"}}
            self.reply(200, {"choices": [{"message": {"role": "assistant", "content": json.dumps(action)}}]})

        def reply(self, status, body):
            encoded = json.dumps(body).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 超时用例的客户端已经关闭连接。

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with patch.dict("os.environ", {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}):
            yield f"http://127.0.0.1:{server.server_address[1]}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def tcp_channel(app):
    """真实 socket 字节流，进入原 handle_client；使用同一连接订阅结果。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)
        client = socket.create_connection(listener.getsockname(), timeout=3)
        accepted, address = listener.accept()
    client.settimeout(5)
    thread = threading.Thread(target=app.tcp_server.handle_client, args=(accepted, address), daemon=True)
    thread.start()
    try:
        yield client
    finally:
        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        client.close()
        thread.join(timeout=3)
        accepted.close()
        if thread.is_alive():
            raise AssertionError("acceptance TCP worker did not stop")


def send_tcp_inputs(app, client, payloads):
    received = threading.Event()
    original = app.tcp_server.ingestor.ingest_tcp

    def ingest(payload):
        result = original(payload)
        received.set()
        return result

    with patch.object(app.tcp_server.ingestor, "ingest_tcp", side_effect=ingest):
        wire = (json.dumps(payloads, ensure_ascii=False) + "\n").encode("utf-8")
        client.sendall(wire[:5])
        client.sendall(wire[5:])
        if not received.wait(3):
            raise AssertionError("acceptance TCP input was not ingested")


def send_radar_http(app, payload):
    app.http_server.port = 0
    app.http_server.start()
    connection = http.client.HTTPConnection(*app.http_server.address, timeout=3)
    try:
        connection.request("POST", "/", body=json.dumps(payload), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        result = json.loads(response.read())
        if response.status != 200:
            raise AssertionError(f"acceptance radar input failed: {result}")
    finally:
        connection.close()


def broadcast_results(app, client, count):
    def receive():
        with client.makefile("rb") as stream:
            return [stream.readline() for _ in range(count)]

    # 真实客户端边发送边读取，不能先塞满 socket 缓冲区再开始读取。
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(receive)
        app.tcp_server.broadcast_once()
        frames = pending.result(timeout=6)
    if any(not frame.endswith(b"\n") for frame in frames):
        raise AssertionError("acceptance TCP output has an incomplete frame")
    return frames, [json.loads(frame) for frame in frames]
