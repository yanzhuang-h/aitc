import time
import unittest

from runtime.application import AITCApplication


class _Component:
    def __init__(self): self.calls = []
    def start(self): self.calls.append("start")
    def stop(self): self.calls.append("stop")
    def start_broadcast_thread(self): self.calls.append("broadcast")
    def serve_forever(self): self.calls.append("serve")


class _Pipeline:
    def __init__(self): self.calls = 0
    def run_once(self): self.calls += 1


class ApplicationTest(unittest.TestCase):
    def test_start_and_stop_manage_components(self):
        config, http, tcp, scheduler, pipeline = _Component(), _Component(), _Component(), _Component(), _Pipeline()
        app = AITCApplication(config_sync_manager=config, http_server=http, tcp_server=tcp, decision_pipeline=pipeline, prediction_scheduler=scheduler, send_interval=0.01)
        app.start()
        time.sleep(0.03)
        app.stop()
        self.assertEqual(config.calls, ["start", "stop"])
        self.assertEqual(http.calls, ["start", "stop"])
        self.assertEqual(scheduler.calls, ["start", "stop"])
        self.assertIn("broadcast", tcp.calls)
        self.assertIn("stop", tcp.calls)
        self.assertGreaterEqual(pipeline.calls, 1)
