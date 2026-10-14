import json
from pathlib import Path
import tempfile
import unittest

from runtime.replay import compare_results, load_capture, summarize_model_attempts
from runtime.safety_audit import audit_schedules


class CaptureReplayTest(unittest.TestCase):
    def load(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'capture.jsonl'
            path.write_text('\n'.join(json.dumps(row) if not isinstance(row, str) else row for row in rows))
            return load_capture(path, 'tcp', **kwargs)

    def test_receive_time_has_priority_and_sensor_timestamp_is_preserved(self):
        rows = [{'AITC_SYS_TS': 200, 'ts': 100000, 'ycsb_xsfx': 'L'},
                {'received_at': '1970-01-01T00:05:00+00:00', 'source': 'tcp', 'payload': {'ts': 100000}}]
        records, meta = self.load(rows)
        self.assertEqual([record.received_at for record in records], [200, 300])
        self.assertEqual(records[0].payload, rows[0])
        self.assertEqual(meta['timestamp_bases'], {'AITC_SYS_TS': 1, 'received_at': 1})

    def test_missing_receive_time_is_marked_inferred_and_milliseconds_converted(self):
        records, _ = self.load([{'ts': 1790208000000}])
        self.assertEqual(records[0].received_at, 1790208000)
        self.assertEqual(records[0].timestamp_basis, 'inferred:ts')
        self.assertEqual(records[0].payload['ts'], 1790208000000)

    def test_malformed_input_fails_or_is_explicitly_counted(self):
        rows = ['not-json', {'ts': True}, {'ts': 123}]
        with self.assertRaisesRegex(ValueError, 'Invalid capture record'):
            self.load(rows)
        records, meta = self.load(rows, skip_invalid=True)
        self.assertEqual(len(records), 1)
        self.assertEqual(meta['invalid_lines'], 2)
        self.assertEqual(meta['invalid_line_numbers_first_20'], [1, 2])
        records, meta = self.load([[{'ts': 100}, {'ts': True}], {'ts': 200}], skip_invalid=True)
        self.assertEqual([record.received_at for record in records], [200])
        self.assertEqual(meta['invalid_lines'], 1)

    def test_limit_and_multi_item_lines_do_not_hide_truncation(self):
        records, meta = self.load([[{'ts': 100}, {'ts': 101}, {'ts': 102}]], limit=2)
        self.assertEqual(len(records), 2)
        self.assertTrue(meta['truncated'])

    def test_channel_and_timezone_errors_are_not_silently_reinterpreted(self):
        for record in [{'source': 'http', 'payload': {}, 'received_at': 123},
                       {'payload': {}, 'received_at': '2026-01-01T00:00:00'}]:
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.load([record])

    def test_metrics_distinguish_invalid_actions_errors_missing_usage_and_prices(self):
        attempts = [{'status': 'valid_action', 'latency_ms': 100,
                     'usage': {'prompt_tokens': 100, 'completion_tokens': 10,
                               'prompt_cache_hit_tokens': 60, 'prompt_cache_miss_tokens': 40}},
                    {'status': 'invalid_action', 'latency_ms': 200, 'usage': {}},
                    {'status': 'error', 'latency_ms': 300, 'usage': {}}]
        summary = summarize_model_attempts([{'model_attempts': attempts, 'model_reason': 'model_error'}])
        self.assertEqual(summary['attempts'], 3)
        self.assertEqual(summary['valid_action_rate'], 1/3)
        self.assertEqual(summary['decision_reasons'], {'model_error': 1})
        self.assertEqual(summary['latency_p95_ms'], 300)
        self.assertIsNone(summary['estimated_cost'])
        self.assertFalse(summary['usage_complete_for_cost'])
        prices = {'cache_hit': '1', 'cache_miss': '2', 'output': '3', 'currency': 'test'}
        cost = summarize_model_attempts([{'model_attempts': attempts[:1]}], prices)
        self.assertEqual(cost['estimated_cost'], '0.00017')
        self.assertIsNone(summarize_model_attempts([])['valid_action_rate'])

    def test_compare_reports_missing_and_changed_roads(self):
        def payload(road, value):
            return {'additional': {'tlLogic': {'id': road}}, 'value': value}
        result = compare_results([[payload('1', 1), payload('2', 1)]], [[payload('1', 2)]])
        self.assertFalse(result['outputs_equal'])
        self.assertEqual([item['intersection_id'] for item in result['differences']], ['1', '2'])

    def test_schedule_inventory_records_real_gaps_without_inventing_bounds(self):
        config = {'1': {'2': {'0': [10, 30]}}}
        schedules = {('1', 'workday'): {'8': [20, 20, 0, 0, 0, 0, 0, 0, 0, 2]},
                     ('3', 'workday'): {'8': [10, 0, 0, 0, 0, 0, 0, 0, 0, 1]}}
        report = audit_schedules(config, schedules, ['1', '3'])
        self.assertEqual({item['missing_rule'] for item in report['missing_rules']},
                         {'phase_1_bounds', 'intersection_config'})
        self.assertEqual(config, {'1': {'2': {'0': [10, 30]}}})
        self.assertFalse(report['configuration_modified'])


if __name__ == '__main__':
    unittest.main()
