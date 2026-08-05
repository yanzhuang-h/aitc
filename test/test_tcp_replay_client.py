import argparse
import importlib.util
import pathlib
import unittest
from unittest.mock import patch


CLIENT_PATH = pathlib.Path(__file__).with_name("client_tcp.py")
FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "flow_replay.jsonl"
SPEC = importlib.util.spec_from_file_location("client_tcp", CLIENT_PATH)
client_tcp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client_tcp)


class TcpReplayClientTests(unittest.TestCase):
    def test_loads_timed_fixture_at_expected_second(self):
        config = {
            "file_path": str(FIXTURE_PATH),
            "send_mode": "timed",
            "timestamp_field": "ts",
            "start_timestamp": 1770627600,
            "duration_sec": 1,
        }
        sender = client_tcp.EnhancedSingleSender("flow", config, "127.0.0.1", 65432, 1)

        sender.load_data_enhanced()

        self.assertEqual(list(sender.time_to_data_map), [1770627600])
        self.assertEqual(sender.time_to_data_map[1770627600][0]["jtll_ddbh"], "1")

    def test_timed_replay_stops_after_last_record(self):
        config = {"duration_sec": 3600}
        sender = client_tcp.EnhancedSingleSender("flow", config, "127.0.0.1", 65432, 1)
        sender.time_to_data_map[100] = [{"id": 1}]
        sent = []
        sender.send_fast = lambda batch: sent.append(batch) or True

        with patch.object(client_tcp.time, "sleep") as sleep:
            sender._run_timed_enhanced(0.1)

        self.assertEqual(sent, [[{"id": 1}]])
        self.assertEqual(sleep.call_count, 1)

    def test_start_timestamp_argument_overrides_timed_config(self):
        sender = client_tcp.EnhancedDataSender()
        args = argparse.Namespace(
            host=None, port=None, timeout=None, workers=None, use_processes=False,
            enable_types=None, type="flow", file=None, interval=None, duration=None,
            start_timestamp=123, max_preload=None,
        )

        sender.apply_args(args)

        self.assertEqual(sender.data_configs["flow"]["start_timestamp"], 123)


if __name__ == "__main__":
    unittest.main()
