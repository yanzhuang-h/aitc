"""TCP 数据接收与结果广播服务。"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any


class TcpRuntimeServer:
    """管理 TCP 客户端连接、运行数据接入和结果广播。"""

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
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.port))
            server_socket.listen()
            server_socket.settimeout(1.0)
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
            clients = list(self._clients)
        results = self.result_warehouse.snapshot()
        if not results:
            return

        disconnected = self.result_sender.send_batch(clients, results)
        for client_socket in disconnected:
            self._remove_client(client_socket)
            client_socket.close()
        self._info("Send results to all Client:%s", clients)

    def handle_client(self, client_socket: socket.socket, address: Any) -> None:
        self._info("Connection from %s established.", address)
        with self._clients_lock:
            self._clients.append(client_socket)

        buffer = ""
        try:
            while not self._stop_event.is_set():
                data = client_socket.recv(self.buffer_size).decode("utf-8")
                if not data:
                    break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self._ingest_line(line)
        except Exception:
            self._error("Error in handle_client", exc_info=True)
        finally:
            self._remove_client(client_socket)
            client_socket.close()
            self._info("Connection from %s closed.", address)

    def stop(self) -> None:
        """停止监听并关闭所有已连接的客户端。"""
        self._stop_event.set()
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

    def _info(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.info(message, *args)

    def _warning(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)

    def _error(self, message: str, *args: Any, **kwargs: Any) -> None:
        if self.logger is not None:
            self.logger.error(message, *args, **kwargs)
