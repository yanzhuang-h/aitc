"""TCP 数据接收与结果广播服务。"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

from infra.logging import LoggingMixin


class TcpRuntimeServer(LoggingMixin):
    """管理 TCP 客户端连接、运行数据接入和结果广播。

    同一连接既上报数据、又接收结果：连接一建立就加入 ``_clients`` 名单，
    广播线程按名单全量推送最新结果快照。
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        buffer_size: int,
        ingestor: Any,
        result_warehouse: Any,
        result_sender: Any,
        send_interval: float,
        logger: Any | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.buffer_size = buffer_size
        self.ingestor = ingestor
        self.result_warehouse = result_warehouse
        self.result_sender = result_sender
        self.send_interval = send_interval
        self.logger = logger
        self._clients: list[socket.socket] = []
        self._clients_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server_socket: socket.socket | None = None

    def serve_forever(self) -> None:
        """阻塞监听 TCP 连接，直到调用 stop。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            self._server_socket = server_socket
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # 重启后端口可立即复用
            server_socket.bind((self.host, self.port))
            server_socket.listen()
            server_socket.settimeout(1.0)  # 让 accept 每秒醒来一次，以便检查停止事件
            self._info("Main server started on %s:%s", self.host, self.port)

            while not self._stop_event.is_set():
                try:
                    client_socket, address = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if not self._stop_event.is_set():
                        self._error("TCP server accept failed", exc_info=True)
                    break

                self._info("New connection from %s", address)
                # ponytail: 每连接一个线程、无上限；当前客户端为少量局域网信控平台，
                # 若接入海量终端，需改为线程池 + accept 限流。
                threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, address),
                    daemon=True,
                ).start()
        self._server_socket = None

    def start_broadcast_thread(self) -> threading.Thread:
        """启动独立的结果广播线程。"""
        thread = threading.Thread(target=self.broadcast_forever, daemon=True)
        thread.start()
        return thread

    def broadcast_forever(self) -> None:
        while not self._stop_event.is_set():
            self.broadcast_once()
            self._stop_event.wait(self.send_interval)

    def broadcast_once(self) -> None:
        """发送当前结果快照，并移除已断开的客户端。"""
        with self._clients_lock:
            clients = list(self._clients)   # 加锁快照名单，发送期间名单变化不影响本轮
        results = self.result_warehouse.snapshot()
        if not results:
            return

        # ponytail: 逐个阻塞发送，单个慢客户端会拖住整轮广播；
        # 当前客户端为少量局域网信控平台，暂不设发送超时。
        disconnected = self.result_sender.send_batch(clients, results)
        for client_socket in disconnected:
            self._remove_client(client_socket)
            client_socket.close()
        self._info("结果已发送：客户端 %d 个，断开 %d 个", len(clients), len(disconnected))

    def handle_client(self, client_socket: socket.socket, address: Any) -> None:
        self._info("Connection from %s established.", address)
        with self._clients_lock:
            # 一建立就加入名单：这条连接既是数据源，也是结果订阅者
            self._clients.append(client_socket)

        # 先按字节收齐再分帧：避免多字节字符被 TCP 切分导致整条连接断开
        buffer = b""
        try:
            while not self._stop_event.is_set():
                chunk = client_socket.recv(self.buffer_size)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._ingest_line(line.decode("utf-8", errors="replace"))
        except Exception:
            self._error("Error in handle_client", exc_info=True)
        finally:
            self._remove_client(client_socket)
            client_socket.close()
            self._info("Connection from %s closed.", address)

    def stop(self) -> None:
        """停止监听并关闭所有已连接的客户端。"""
        self._stop_event.set()
        # 关闭监听 socket：打断阻塞中的 accept
        if self._server_socket is not None:
            self._server_socket.close()
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client_socket in clients:
            client_socket.close()

    def _ingest_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            self._error("JSON Decode Error: %s, Data: %s", error, line)
            return

        if isinstance(payload, (dict, list)):
            self.ingestor.ingest_tcp(payload)
        else:
            self._warning("Unsupported data format.")

    def _remove_client(self, client_socket: socket.socket) -> None:
        with self._clients_lock:
            if client_socket in self._clients:
                self._clients.remove(client_socket)
