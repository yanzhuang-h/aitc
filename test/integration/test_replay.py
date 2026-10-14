import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test.fixtures.v2_acceptance import model_endpoint, source_payloads, VIDEO_INTERSECTION
from test.fixtures.v2_baseline_controller import FIXED_TIME


class ReplayIntegrationTest(unittest.TestCase):
    def run_replay(self, root, *, model=False):
        tcp, http = root/'tcp.jsonl', root/'http.jsonl'
        payloads = source_payloads(FIXED_TIME)
        tcp.write_text(json.dumps(payloads[0][2] | {'AITC_SYS_TS': FIXED_TIME}) + '\n')
        http.write_text(json.dumps(payloads[2][2] | {'AITC_SYS_TS': FIXED_TIME}) + '\n')
        args = [sys.executable, '-m', 'runtime.replay', '--tcp', str(tcp), '--http', str(http),
                '--output', str(root/'report'), '--rounds', '2', '--interval', '601']
        if model:
            args += ['--model', '--roads', VIDEO_INTERSECTION]
        run = subprocess.run(args, text=True, capture_output=True, timeout=60,
                             cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads((root/'report/comparison.json').read_text())

    def test_real_worker_ingestion_windows_original_baseline_and_trace_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.run_replay(root)
            self.assertTrue(report['outputs_equal'])
            self.assertEqual(report['v2']['published_traces'], 372)
            self.assertEqual(report['v2']['model_metrics']['attempts'], 0)
            self.assertTrue(all(round['result_count'] == 186 for round in report['v2']['rounds']))
            self.assertTrue(all(round['window_counts']['flow'] == 0 for round in report['v2']['rounds']))
            self.assertFalse(report['v2']['servers_started'])
            self.assertEqual(report['v2']['ingested_records'], 2)

    def test_cloud_whitelist_metrics_and_candidates_over_real_http_boundary(self):
        with tempfile.TemporaryDirectory() as directory, model_endpoint() as (url, requests), patch.dict(os.environ, {
            'AITC_LLM_ENABLED': 'true', 'AITC_MODEL_PROVIDER': 'deepseek',
            'AITC_MODEL_NAME': 'acceptance-model', 'AITC_MODEL_BASE_URL': url,
            'AITC_MODEL_API_KEY': 'acceptance-test-key', 'AITC_CONTROL_AGENT_TIMEOUT_SECONDS': '2',
            'AITC_CONTROL_AGENT_MAX_MODEL_CALLS': '3',
        }):
            root = Path(directory)
            report = self.run_replay(root, model=True)
            self.assertTrue(report['outputs_equal'])
            self.assertEqual(len(requests), 4)
            self.assertEqual(report['v2']['model_metrics']['valid_action_rate'], 1)
            self.assertIsNone(report['v2']['model_metrics']['estimated_cost'])
            traces = [json.loads(line) for line in (root/'report/v2/decisions.jsonl').read_text().splitlines()]
            participating = {trace['intersection_id'] for trace in traces if trace['llm_participated']}
            self.assertEqual(participating, {VIDEO_INTERSECTION})
            self.assertEqual(len(traces), 372)
            self.assertTrue(any(trace['model_reason'] == 'not_allowlisted' for trace in traces))
            self.assertTrue(all(request['body']['thinking'] == {'type': 'disabled'} for request in requests))

    def test_persisted_capture_history_and_output_dates_use_original_receive_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_replay(root)
            expected = datetime.fromtimestamp(FIXED_TIME, timezone.utc).isoformat()
            for mode in ('baseline', 'v2'):
                for kind in ('flow', 'radar'):
                    path = root/'report'/mode/'history/runtime'/f'{kind}.jsonl'
                    stored = [json.loads(line) for line in path.read_text().splitlines()]
                    self.assertEqual(stored[0]['received_at'], expected)
                    self.assertEqual(stored[0]['payload']['AITC_SYS_TS'], FIXED_TIME)
                    self.assertTrue((root/'report'/mode/'output'/kind/f'2026-09-30_{kind}.txt').exists())


if __name__ == '__main__':
    unittest.main()
