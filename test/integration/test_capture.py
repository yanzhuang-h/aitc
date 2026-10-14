import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from runtime.capture import CaptureWriter, create_capture_servers
from runtime.replay import load_capture


class CaptureIntegrationTest(unittest.TestCase):
    def test_http_body_shorter_than_content_length_is_not_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            tcp, http_server = create_capture_servers(CaptureWriter(directory), tcp_port=0, http_port=0)
            thread = threading.Thread(target=http_server.serve_forever, daemon=True)
            thread.start()
            try:
                body = b'{"deviceNo":"radar-ximenzi-333-01"}'
                headers = (f'POST / HTTP/1.0\r\nHost: localhost\r\nContent-Length: {len(body)+20}\r\n\r\n').encode()
                with socket.create_connection(http_server.server_address, timeout=3) as client:
                    client.sendall(headers+body)
                    client.shutdown(socket.SHUT_WR)
                    response = http.client.HTTPResponse(client)
                    response.begin()
                    self.assertEqual(response.status, 400)
                    response.read()
                self.assertFalse((Path(directory)/'http.jsonl').exists())
            finally:
                http_server.shutdown()
                http_server.server_close()
                tcp.server_close()
                thread.join(timeout=3)

    def test_fragmented_tcp_and_http_save_raw_payloads_without_control_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = CaptureWriter(directory)
            tcp, http_server = create_capture_servers(writer, tcp_port=0, http_port=0)
            threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (tcp, http_server)]
            for thread in threads:
                thread.start()
            try:
                original = {'ycsb_xsfx': '左', 'ts': 1790208000000, 'jtll_ddbh': '1'}
                frame = (json.dumps([original], ensure_ascii=False)+'\n').encode()
                with socket.create_connection(tcp.server_address) as client:
                    client.sendall(b'bad-json\n')
                    client.sendall(frame[:5])
                    client.sendall(frame[5:])
                    path = Path(directory)/'tcp.jsonl'
                    deadline = time.monotonic()+3
                    while not path.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(path.exists())
                    client.settimeout(.05)
                    with self.assertRaises(socket.timeout):
                        client.recv(1)
                radar = {'deviceNo': 'radar-ximenzi-333-01', 'ts': 1790208000000}
                connection = http.client.HTTPConnection(*http_server.server_address, timeout=3)
                try:
                    connection.request('POST', '/', json.dumps(radar))
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())['received'], 1)
                    connection.request('POST', '/', 'not-json')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 400)
                    response.read()
                finally:
                    connection.close()
                received, metadata = load_capture(path, 'tcp')
                self.assertEqual(received[0].payload, original)
                self.assertEqual(tcp.invalid_frames, 1)
                self.assertEqual(metadata['timestamp_bases'], {'received_at': 1})
                radar_records, _ = load_capture(Path(directory)/'http.jsonl', 'http')
                self.assertEqual(radar_records[0].payload, radar)
            finally:
                tcp.stopping.set()
                for server in (tcp, http_server):
                    server.shutdown()
                    server.server_close()
                for thread in threads:
                    thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
