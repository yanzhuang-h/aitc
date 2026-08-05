import json
import unittest

from runtime import TcpRuntimeServer


class _Ingestor:
    def __init__(self):
        self.payloads = []

    def ingest_tcp(self, payload):
        self.payloads.append(payload)


class _Warehouse:
    def snapshot(self):
        return [{"id": "100"}]


class _Sender:
    def __init__(self):
        self.calls = []

    def send_batch(self, clients, results):
        self.calls.append((clients, results))
        return []


class _Socket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def recv(self, _size):
        return self.chunks.pop(0)

    def close(self):
        self.closed = True


class TcpRuntimeServerTest(unittest.TestCase):
    def _build_server(self, ingestor=None, sender=None):
        return TcpRuntimeServer(
            host="127.0.0.1",
            port=65432,
            buffer_size=1024,
            ingestor=ingestor or _Ingestor(),
            result_warehouse=_Warehouse(),
            result_sender=sender or _Sender(),
            send_interval=1,
        )

    def test_handle_client_parses_newline_delimited_json(self):
        ingestor = _Ingestor()
        server = self._build_server(ingestor=ingestor)
        client_socket = _Socket([
            (json.dumps({"id": 1}) + "\n").encode("utf-8"),
            b"",
        ])

        server.handle_client(client_socket, ("127.0.0.1", 1))

        self.assertEqual(ingestor.payloads, [{"id": 1}])
        self.assertTrue(client_socket.closed)

    def test_broadcast_once_uses_result_sender(self):
        sender = _Sender()
        server = self._build_server(sender=sender)
        client_socket = _Socket([])
        server._clients.append(client_socket)

        server.broadcast_once()

        self.assertEqual(sender.calls, [([client_socket], [{"id": "100"}])])


if __name__ == "__main__":
    unittest.main()
