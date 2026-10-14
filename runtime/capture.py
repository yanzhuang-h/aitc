"""现场镜像采集入口：仅保存原报文和接收时间，不装配控制器或发送配时。"""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import socketserver
import threading


MAX_FRAME_BYTES = 4 * 1024 * 1024


class CaptureWriter:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def append(self, source, raw):
        received_at = datetime.now(timezone.utc).isoformat()
        payload = json.loads(raw)
        items = payload if isinstance(payload, list) else [payload]
        if not items or any(not isinstance(item, dict) for item in items):
            raise ValueError('Expected an object or a nonempty array of objects')
        lines = [json.dumps({'source': source, 'received_at': received_at, 'payload': item},
                            ensure_ascii=True, allow_nan=False) for item in items]
        with self.lock, (self.root/f'{source}.jsonl').open('a', encoding='utf-8') as file:
            file.write('\n'.join(lines) + '\n')
        return len(items)


def create_capture_servers(writer, host='127.0.0.1', tcp_port=65433, http_port=8089):
    class TCPHandler(socketserver.BaseRequestHandler):
        def reject(self):
            with self.server.counter_lock:
                self.server.invalid_frames += 1

        def handle(self):
            self.request.settimeout(1)
            buffer = b''
            while not self.server.stopping.is_set():
                try:
                    chunk = self.request.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    if buffer.strip():
                        self.reject()
                    return
                buffer += chunk
                while b'\n' in buffer:
                    frame, buffer = buffer.split(b'\n', 1)
                    if len(frame) > MAX_FRAME_BYTES:
                        self.reject()
                        return
                    if frame.strip():
                        try:
                            writer.append('tcp', frame)
                        except (ValueError, UnicodeError):
                            self.reject()
                if len(buffer) > MAX_FRAME_BYTES:
                    self.reject()
                    return

    class TCPServer(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    class HTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_FRAME_BYTES:
                    raise ValueError('Invalid content length')
                self.connection.settimeout(5)
                received = writer.append('http', self.rfile.read(size))
                status, body = 200, {'received': received}
            except (ValueError, UnicodeError, TimeoutError):
                status, body = 400, {'error': 'Invalid capture JSON frame'}
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    tcp = TCPServer((host, tcp_port), TCPHandler)
    tcp.stopping = threading.Event()
    tcp.counter_lock = threading.Lock()
    tcp.invalid_frames = 0
    try:
        http = ThreadingHTTPServer((host, http_port), HTTPHandler)
    except Exception:
        tcp.server_close()
        raise
    http.daemon_threads = True
    return tcp, http


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--tcp-port', type=int, default=65433)
    parser.add_argument('--http-port', type=int, default=8089)
    parser.add_argument('--output', type=Path, default=Path('logs_data/capture')/datetime.now().strftime('%Y%m%d-%H%M%S'))
    args = parser.parse_args()
    for port in (args.tcp_port, args.http_port):
        if not 1 <= port <= 65535:
            parser.error('ports must be 1..65535')
    if args.tcp_port == args.http_port:
        parser.error('TCP and HTTP ports must differ')
    writer = CaptureWriter(args.output)
    tcp, http = create_capture_servers(writer, args.host, args.tcp_port, args.http_port)
    thread = threading.Thread(target=tcp.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({'capture_only': True, 'host': args.host, 'tcp_port': args.tcp_port,
                      'http_port': args.http_port, 'output': str(args.output.resolve())}), flush=True)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tcp.stopping.set()
        tcp.shutdown()
        tcp.server_close()
        http.server_close()
        thread.join(timeout=2)
        print(json.dumps({'invalid_tcp_frames': tcp.invalid_frames}), flush=True)


if __name__ == '__main__':
    main()
