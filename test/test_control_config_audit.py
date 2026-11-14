"""验证审计不执行生产模块、不改配置，并区分确定错误和待核对疑点。"""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

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
    return select_pilot_schedule(old)
def DQN_select_490():
    return select_pilot_schedule()
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
        self.assertEqual(self.report(group='49')['summary']['roads'], 1)

    def test_eligibility_requires_wiring_target_mode_and_enabled(self):
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
        self.assertIn('invalid_cross_field', self.codes(roads={'490'}))

    def test_overlapping_groups_and_dynamic_definitions_fail_explicitly(self):
        self.write('lib/road_groups.py', "TONGZHOU_19 = {'490'}\nTONGZHOU_49 = {'490'}")
        with self.assertRaisesRegex(ValueError, '重叠'):
            self.report()
        self.write('dynamic.py', "target = load_from_network()")
        with self.assertRaisesRegex(ValueError, '不能静态解析'):
            bindings(self.root/'dynamic.py', {'target'})

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
