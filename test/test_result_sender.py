"""结果发送器测试：验证帧分隔与断连处理。"""

from __future__ import annotations

import json
import unittest

from infra.data.result_sender import ResultSender


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    def sendall(self, data: bytes) -> None:
        if self.closed:
            raise OSError("socket closed")
        self.sent.append(data)


class _BrokenSocket(_FakeSocket):
    def sendall(self, data: bytes) -> None:
        raise BrokenPipeError("broken")


class _Writer:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write_send_result(self, result: dict) -> None:
        self.records.append(result)


class ResultSenderTest(unittest.TestCase):
    def test_send_batch_uses_newline_frame(self) -> None:
        sock = _FakeSocket()
        writer = _Writer()
        sender = ResultSender(writer=writer)
        results = [{"cross_id": "1300068", "action": [1, 2]}, {"cross_id": "1300069", "action": [3, 4]}]

        disconnected = sender.send_batch([sock], results)

        self.assertEqual(disconnected, [])
        joined = b"".join(sock.sent)
        self.assertTrue(joined.endswith(b"\n"))
        lines = [line for line in joined.split(b"\n") if line]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), results[0])
        self.assertEqual(json.loads(lines[1]), results[1])
        # 每条结果都记录了发送日志
        self.assertEqual(writer.records, results)

    def test_send_batch_marks_disconnected_client(self) -> None:
        sock = _BrokenSocket()
        sender = ResultSender(writer=_Writer())
        disconnected = sender.send_batch([sock], [{"cross_id": "1300068"}])
        self.assertEqual(disconnected, [sock])

    def test_send_batch_without_writer(self) -> None:
        sock = _FakeSocket()
        sender = ResultSender(writer=None)
        disconnected = sender.send_batch([sock], [{"cross_id": "1300068"}])
        self.assertEqual(disconnected, [])
        self.assertTrue(b"\n" in b"".join(sock.sent))


if __name__ == "__main__":
    unittest.main()
