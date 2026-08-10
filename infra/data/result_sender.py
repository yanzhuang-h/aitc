"""结果发送器。"""

from __future__ import annotations

import json
import socket
from typing import Any


class ResultSender:
    """只负责把结果发给客户端并记录发送日志。"""

    def __init__(self, writer: Any | None = None, logger: Any | None = None) -> None:
        self.writer = writer
        self.logger = logger

    def send_batch(
        self,
        clients: list[socket.socket],
        results: list[dict[str, Any]],
    ) -> list[socket.socket]:
        disconnected: list[socket.socket] = []
        for client_socket in clients:
            try:
                for result in results:
                    # 与 TCP 接收端一致，使用 \n 作为帧分隔符
                    client_socket.sendall((json.dumps(result) + "\n").encode("utf-8"))
                    if self.writer is not None:
                        self.writer.write_send_result(result)
            except (socket.error, BrokenPipeError):
                disconnected.append(client_socket)
                if self.logger is not None:
                    self.logger.warning("客户端断开连接，已标记移除")
        return disconnected

