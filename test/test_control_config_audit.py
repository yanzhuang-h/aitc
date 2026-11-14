"""验证审计不执行生产模块、不改配置，并区分确定错误和待核对疑点。"""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.control_config_audit import audit, bindings, main


class ControlConfigAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write("Lambdas.py", """raise RuntimeError('审计禁止执行模块')
intersection_list = ['100', '190', '490']
location_to_intersection_lambda = {1: ('alias', 'L')}
aibi_to_xinkongji = {'alias': '490'}
flow_map_single_intersection_lambda = {'pass': {'U': [0]*7}}
""".replace("{'U': [0]*7}", repr({d: [0]*7 for d in "UDLR"})))
        self.write("lib/road_groups.py", "TONGZHOU_19 = frozenset({'190', '191'})\nTONGZHOU_49 = frozenset({'490'})")
        self.write("lib/Global_intersection_coordinate.py", "intern_road_id = {'100'}\nvideo_road = set()\nvideo_flow_road = {'190', '490'}")
        self.write("lib/data_ANS/flow_allocator_shadow.py", "DEFAULT_PILOT_MODE = 'new'\nDEFAULT_TARGET_ROAD_IDS = frozenset({'190', '490'})")
        self.write("lib/data_ANS/lane_policy.py", "LANE_TYPE_RULES = {'1A': {'capacity_eligible': True}, '1B': {'capacity_eligible': True}, '1C': {'capacity_eligible': False}}\nDEDICATED_LEFT_TURN_LANE_TYPE = '1A'")
        self.write("lib/data_ANS/cycle_quality.py", "PHASE_DIRECTION_MAP = {'LR': ('L','R'), 'UD': ('U','D')}")
        self.write("lib/control_functions/global_processors/phase_adapter.py", "PHASE_DIRECTION_MAP = {**TRAINING_PHASE_DIRECTION_MAP, 'LTL': ('LTL',)}")
        self.write("lib/DQN_Select.py", """raise RuntimeError('审计禁止执行模块')
Cross_Video = ['190', '490']
def DQN_select_190():
    old = chuli_shuju()
    return select_pilot_schedule("190", old)
def DQN_select_490():
    return select_pilot_schedule("490")
def DQN_select(cross_id):
    if cross_id == '190':
        return DQN_select_190()
    elif cross_id == '490':
        return DQN_select_490()
    return [0]
""")
        self.states = {rid: {"1": {"phase": ["LR", "UD", 0],
                                  "min_pass_time": [5, 5, 0], "platform_min_pass_time": [5, 5, 0],
                                  "max_pass_time": [60, 60, 0], "platform_max_pass_time": [60, 60, 0]}}
                       for rid in ['100', '190', '191', '490']}
        self.crosses = {rid: {"LaneNo": {"L": {"0": "1B"}}, "phase": {"1": "LR", "2": "UD"},
                              "Cycle": [[2, 1]], "jtll_ddbh": {}}
                        for rid in self.states}
        self.crosses['490']['jtll_ddbh'] = {'1': 'L'}
        self.save_configs()
        self.write("lib/road_state.json", '{}')
        self.write("lib/plan_id_overrides.json", '{}')

    def write(self, name, content):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def save_configs(self):
        self.write("lib/road_info.json", json.dumps(self.states))
        self.write("lib/cross_info.json", json.dumps(self.crosses))

    def report(self, **kwargs):
        return audit(self.root, environ={}, **kwargs)

    def codes(self, **kwargs):
        return {x['code'] for x in self.report(**kwargs)['findings']}

    def test_static_execution_and_file_preservation(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = self.report()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertNotIn('error', report['summary']['severity'])
        self.assertEqual(report['sources'][0]['sha256'], hashlib.sha256(before[self.root/'Lambdas.py']).hexdigest())

    def test_generic_candidate_is_valid_and_cohorts_are_not_routes(self):
        rows = {x['road_id']: x for x in self.report()['inventory']}
        self.assertEqual(rows['100']['selector_entry'], 'generic_zero_candidate')
        self.assertTrue(rows['190']['legacy_computation_precedes_pilot'])
        self.assertTrue(rows['190']['online_candidate_eligible'])
        self.assertFalse(rows['490']['legacy_experience_lookup'])
        self.assertFalse(rows['191']['registered'])
        self.assertEqual([x['road_id'] for x in self.report(group='49')['inventory']], ['490'])

    def test_eligibility_requires_wiring_target_mode_and_enabled(self):
        self.assertTrue(self.report(roads={'490'})['inventory'][0]['online_candidate_eligible'])
        for env in [{'AITC_FLOW_ALLOCATOR_PILOT_MODE': 'shadow'},
                    {'AITC_FLOW_ALLOCATOR_PILOT_MODE': 'typo'},
                    {'AITC_FLOW_ALLOCATOR_SHADOW_ENABLED': 'false'},
                    {'AITC_FLOW_ALLOCATOR_PILOT_ROADS': '190'}]:
            row = next(x for x in audit(self.root, roads={'490'}, environ=env)['inventory'])
            self.assertFalse(row['online_candidate_eligible'])
        report = audit(self.root, environ={'AITC_FLOW_ALLOCATOR_PILOT_MODE': 'typo'})
        self.assertTrue(report['pilot_policy']['invalid_mode_fell_back_to_legacy'])

    def test_env_whitelist_and_precedence_without_secret_leak(self):
        self.write('.env', "SECRET_TOKEN=never-show\nAITC_FLOW_ALLOCATOR_PILOT_MODE=legacy\nAITC_DATA_ROOT=/private/path")
        report = audit(self.root, environ={'AITC_FLOW_ALLOCATOR_PILOT_MODE': 'new', 'OTHER_SECRET': 'never-show'})
        self.assertEqual(report['pilot_policy']['mode'], 'new')
        self.assertEqual(report['pilot_policy']['external_data_settings_present'], ['AITC_DATA_ROOT'])
        self.assertNotIn('never-show', json.dumps(report))
        self.assertNotIn('/private/path', json.dumps(report))

    def test_alias_and_rotated_cycle_are_not_mismatches(self):
        self.assertNotIn('detector_mapping_mismatch', self.codes())
        self.assertNotIn('cycle_program_order_unmatched', self.codes())
        self.crosses['490']['Cycle'] = [[1, 99]]
        self.save_configs()
        self.assertIn('cycle_stage_missing', self.codes(roads={'490'}))

    def test_uncovered_controlled_movement_and_uncontrolled_exclusion(self):
        self.crosses['490']['LaneNo'] = {'L': {'0': '1A'}, 'R': {'0': '1C'}}
        self.save_configs()
        findings = [x for x in self.report(roads={'490'})['findings'] if x['code'] == 'uncovered_controlled_movements']
        self.assertEqual(len(findings), 1)
        self.assertIn('LTL', findings[0]['message'])
        self.assertNotIn("'R'", findings[0]['message'])

    def test_runtime_lane_limit_differs_from_experience_lane_limit(self):
        self.crosses['490']['LaneNo']['L'] = {'7': '1B', '-1': '1B'}
        self.save_configs()
        codes = self.codes(roads={'490'})
        self.assertIn('lane_outside_runtime_vector', codes)
        self.assertIn('invalid_lane_index', codes)

    def test_repeated_slots_are_preserved_and_bounds_checked(self):
        state = self.states['490']['1']
        state['phase'] = ['LR', 'LR', 0]
        state['platform_min_pass_time'][0] = 61
        self.save_configs()
        codes = self.codes(roads={'490'})
        self.assertIn('repeated_phase_label', codes)
        self.assertIn('conflicting_phase_bounds', codes)
        self.assertNotIn('phase_slots_invalid', codes)

    def test_phase_gap_and_unknown_phase_are_errors(self):
        self.states['490']['1']['phase'] = ['LR', 0, 'unknown']
        self.save_configs()
        codes = self.codes(roads={'490'})
        self.assertIn('phase_slots_invalid', codes)
        self.assertIn('unknown_phase', codes)

    def test_invalid_cross_field_is_reported(self):
        self.crosses['490']['LaneNo'] = []
        self.crosses['490']['jtll_ddbh'] = None
        self.save_configs()
        findings = [x for x in self.report(roads={'490'})['findings'] if x['code'] == 'invalid_cross_field']
        self.assertEqual(len(findings), 2)
        self.assertTrue(any('LaneNo' in x['message'] for x in findings))
        self.assertTrue(any('jtll_ddbh' in x['message'] for x in findings))

    def test_overlapping_groups_and_dynamic_definitions_fail_explicitly(self):
        self.write('lib/road_groups.py', "TONGZHOU_19 = {'490'}\nTONGZHOU_49 = {'490'}")
        with self.assertRaisesRegex(ValueError, '重叠'):
            self.report()
        self.write('dynamic.py', "target = load_from_network()")
        with self.assertRaisesRegex(ValueError, '不能静态解析'):
            bindings(self.root/'dynamic.py', {'target'})

    def test_required_fields_and_cycle_alias(self):
        for field in ['LaneNo', 'jtll_ddbh', 'phase']:
            saved = self.crosses['490'].pop(field)
            self.save_configs()
            findings = [x for x in self.report(roads={'490'})['findings'] if x['code'] == 'missing_cross_field']
            self.assertTrue(any(field in x['message'] for x in findings))
            self.crosses['490'][field] = saved
        self.crosses['490']['zhouqi'] = [[1, 99]]
        self.save_configs()
        self.assertIn('cycle_stage_missing', self.codes(roads={'490'}))

    def test_integer_bounds_and_per_program_coverage(self):
        state = self.states['490']['1']
        state['min_pass_time'][0] = 5.1
        state['max_pass_time'][0] = 5.9
        self.save_configs()
        self.assertIn('conflicting_phase_bounds', self.codes(roads={'490'}))
        self.states['490']['2'] = dict(state, phase=['UD', 0, 0])
        self.save_configs()
        findings = [x for x in self.report(roads={'490'})['findings'] if x['code'] == 'program_uncovered_controlled_movements']
        self.assertEqual([x['state'] for x in findings], ['2'])
        self.assertNotIn('uncovered_controlled_movements', self.codes(roads={'490'}))

    def test_wrong_or_dynamic_pilot_id_is_not_eligible(self):
        path = self.root/'lib/DQN_Select.py'
        original = path.read_text()
        for argument, code in [('"190"', 'pilot_road_mismatch'), ('dynamic_road', 'unresolved_pilot_road')]:
            path.write_text(original.replace('select_pilot_schedule("490")', f'select_pilot_schedule({argument})'))
            report = self.report(roads={'490'})
            self.assertFalse(report['inventory'][0]['online_candidate_eligible'])
            self.assertIn(code, {x['code'] for x in report['findings']})

    def test_dotenv_matches_runtime_comments_quotes_and_first_value(self):
        self.write('.env', "export AITC_FLOW_ALLOCATOR_PILOT_MODE=legacy\nAITC_FLOW_ALLOCATOR_PILOT_MODE='new' # keep\nAITC_FLOW_ALLOCATOR_PILOT_MODE=shadow\nAITC_FLOW_ALLOCATOR_PILOT_ROADS=490 # comment")
        report = self.report(roads={'490'})
        self.assertTrue(report['inventory'][0]['online_candidate_eligible'])
        self.assertEqual(report['pilot_policy']['target_count'], 1)

    def test_fingerprint_uses_the_exact_parsed_snapshot(self):
        original_read = Path.read_bytes
        target = self.root/'Lambdas.py'
        original = original_read(target)
        counts = {}
        def changing_read(path):
            data = original_read(path)
            counts[path] = counts.get(path, 0) + 1
            if path == target:
                path.write_text(data.decode().replace("'100', '190', '490'", "'190', '490'"))
            return data
        with patch.object(Path, 'read_bytes', changing_read):
            report = self.report()
        self.assertEqual(counts[target], 1)
        self.assertTrue(next(x for x in report['inventory'] if x['road_id'] == '100')['registered'])
        self.assertEqual(report['sources'][0]['sha256'], hashlib.sha256(original).hexdigest())

    def test_forced_state_normalization_and_disabled_rule(self):
        self.write('lib/road_state.json', json.dumps({'490': [{'state': [1]}, {'state': 1.0}, {'state': '01'}, {'state': 99, 'enabled': 'false'}]}))
        self.assertNotIn('forced_program_missing', self.codes(roads={'490'}))

    def test_failed_report_write_removes_only_the_new_destination(self):
        output = self.root/'partial.json'
        original_open = Path.open
        class FailingFile:
            def __init__(self, handle): self.handle = handle
            def __enter__(self): return self
            def __exit__(self, *args): self.handle.close()
            def write(self, text):
                self.handle.write(text[:10])
                raise OSError('模拟磁盘写入失败')
        def failing_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            return FailingFile(handle) if path == output and args == ('x',) else handle
        with patch.object(Path, 'open', failing_open), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main(['--root', str(self.root), '--output', str(output)])
        self.assertEqual(stopped.exception.code, 2)
        self.assertFalse(output.exists())

    def test_output_refuses_overwrite_and_cli_exit_status(self):
        config = self.root/'lib/road_info.json'
        before = config.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main(['--root', str(self.root), '--output', str(config)])
        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(config.read_bytes(), before)
        output = self.root/'report.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root), '--output', str(output)]), 0)
        self.assertEqual(json.loads(output.read_text())['schema_version'], 1)
        self.states['490']['1']['phase'] = [0]
        self.save_configs()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root), '--group', '49']), 1)


if __name__ == '__main__':
    unittest.main()
