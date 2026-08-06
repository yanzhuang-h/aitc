import http.client
import json
import unittest

from runtime import HttpRuntimeServer


class _Ingestor:
    def __init__(self):
        self.payloads = []

    def ingest_http(self, payload):
        self.payloads.append(payload)


class _ConfigService:
    def handle_request(self, _method, _path, _body):
        return None


class _QueryService:
    def get_runtime_size(self, _kind):
        return 3
    def get_data_quality_snapshot(self):
        return {"total_issues": 2, "issues_by_kind": {"radar": 2}, "recent_issues": []}


class _SignalTimingTool:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {"cross_id": kwargs["cross_id"], "signal_timing": [15, 20]}


class HttpRuntimeServerTest(unittest.TestCase):
    def setUp(self):
        self.ingestor = _Ingestor()
        self.server = HttpRuntimeServer(
            host="127.0.0.1",
            port=0,
            ingestor=self.ingestor,
            config_service=_ConfigService(),
            query_service=_QueryService(),
            signal_timing_tool=_SignalTimingTool(),
        )
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def _request(self, method, path, body=None):
        connection = http.client.HTTPConnection(*self.server.address, timeout=2)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, payload

    def test_post_ingests_radar_payload(self):
        status, payload = self._request("POST", "/radar", json.dumps({"deviceNo": "d1"}))

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(self.ingestor.payloads, [{"deviceNo": "d1"}])

    def test_get_returns_radar_health(self):
        status, payload = self._request("GET", "/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["radar_cache_size"], 3)
        self.assertEqual(payload["data_quality"]["total_issues"], 2)

    def test_get_root_returns_frontend_html(self):
        connection = http.client.HTTPConnection(*self.server.address, timeout=2)
        connection.request("GET", "/")
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        connection.close()

        self.assertEqual(response.status, 200)
        self.assertIn("AITC 路口方案查询", payload)

    def test_post_signal_timing_returns_result(self):
        status, payload = self._request("POST", "/api/signal-timing", json.dumps({"cross_id": "1300068"}))

        self.assertEqual(status, 200)
        self.assertEqual(payload["cross_id"], "1300068")
        self.assertEqual(payload["result"]["signal_timing"], [15, 20])


if __name__ == "__main__":
    unittest.main()
