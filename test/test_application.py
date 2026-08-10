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


class _LLMClient:
    def __init__(self, ok=True):
        self.ok = ok
        self.base_url = "http://test-llm"
        self.model = "test-model"
        self.checked = 0

    def list_models(self):
        self.checked += 1
        if not self.ok:
            raise RuntimeError("LLM unavailable")
        return {"data": []}


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

    def test_replay_mode_skips_external_background_tasks(self):
        config, http, tcp, scheduler, pipeline = _Component(), _Component(), _Component(), _Component(), _Pipeline()
        app = AITCApplication(config_sync_manager=config, http_server=http, tcp_server=tcp, decision_pipeline=pipeline, prediction_scheduler=scheduler, send_interval=0.01, enable_config_sync=False, enable_prediction_scheduler=False)
        app.start()
        time.sleep(0.03)
        app.stop()
        self.assertEqual(config.calls, [])
        self.assertEqual(scheduler.calls, [])
        self.assertIn("broadcast", tcp.calls)
        self.assertIn("stop", tcp.calls)

    def test_llm_ready_check_runs_on_start(self):
        config, http, tcp, scheduler, pipeline = _Component(), _Component(), _Component(), _Component(), _Pipeline()
        llm = _LLMClient(ok=True)
        app = AITCApplication(config_sync_manager=config, http_server=http, tcp_server=tcp, decision_pipeline=pipeline, prediction_scheduler=scheduler, send_interval=0.01, llm_client=llm, llm_required=False)
        app.start()
        self.assertEqual(llm.checked, 1)
        app.stop()

    def test_llm_unavailable_warns_but_starts(self):
        config, http, tcp, scheduler, pipeline = _Component(), _Component(), _Component(), _Component(), _Pipeline()
        llm = _LLMClient(ok=False)
        app = AITCApplication(config_sync_manager=config, http_server=http, tcp_server=tcp, decision_pipeline=pipeline, prediction_scheduler=scheduler, send_interval=0.01, llm_client=llm, llm_required=False)
        app.start()  # 不抛错，仅降级
        self.assertEqual(llm.checked, 1)
        app.stop()

    def test_llm_unavailable_required_blocks_start(self):
        config, http, tcp, scheduler, pipeline = _Component(), _Component(), _Component(), _Component(), _Pipeline()
        llm = _LLMClient(ok=False)
        app = AITCApplication(config_sync_manager=config, http_server=http, tcp_server=tcp, decision_pipeline=pipeline, prediction_scheduler=scheduler, send_interval=0.01, llm_client=llm, llm_required=True)
        with self.assertRaises(RuntimeError):
            app.start()
