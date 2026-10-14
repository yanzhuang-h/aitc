"""只读枚举现有时刻表所需规则；不从历史配时推导安全限值。"""

from collections import Counter
import json
from pathlib import Path

from app.core.control.adapters import signal_plan_from_legacy
from app.core.control.safety_engine import ControlSafetyEngine


def audit_schedules(config, schedules, roads):
    engine = ControlSafetyEngine(config_supplier=lambda: config, phase_check=lambda value: (value, {}))
    statuses, gaps, invalid, required = Counter(), set(), [], {}
    missing_files = []
    for road in roads:
        for day in ('workday', 'weekend'):
            schedule = schedules.get((road, day))
            if schedule is None:
                missing_files.append({'intersection_id': road, 'day': day})
                continue
            for hour, raw in schedule.items():
                result = engine.check(road, raw, config=config)
                statuses[result.status] += 1
                for rule in result.missing_rules:
                    gaps.add((road, str(result.plan.program_id), rule))
                if result.status == 'invalid':
                    invalid.append({'intersection_id': road, 'day': day, 'hour': hour,
                                    'issues': result.issues})
                try:
                    plan = signal_plan_from_legacy(road, raw)
                except ValueError:
                    continue
                active = required.setdefault(road, {}).setdefault(str(plan.program_id), set())
                active.update(index for index, value in enumerate(plan.phase_times) if value > 0)
    return {'inspection': 'raw_schedules_before_existing_bounds_repair',
            'schedule_status_counts': dict(statuses), 'missing_schedule_files': missing_files,
            'missing_rules': [{'intersection_id': road, 'program_id': program, 'missing_rule': rule}
                              for road, program, rule in sorted(gaps)],
            'invalid_raw_schedules': invalid,
            'required_active_phases': {road: {program: sorted(phases) for program, phases in programs.items()}
                                      for road, programs in required.items()},
            'unconfigured_domains': ['pedestrian_min_green', 'conflict_matrix', 'yellow_all_red'],
            'configuration_modified': False,
            'notes': 'Raw out-of-bounds schedules may be repaired by the existing production phase_check. Historical timings do not establish safe bounds.'}


def main():
    import argparse
    import Lambdas
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('intersection_result_config.json'))
    parser.add_argument('--schedules', type=Path, default=Path('time_schedule/schedule_json'))
    parser.add_argument('--output', type=Path, default=Path('logs_data/replay/safety_inventory.json'))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if not isinstance(config, dict):
        parser.error('config must be a JSON object')
    schedules = {}
    for road in Lambdas.intersection_list:
        for day, prefix in [('workday', 'Time_schedule_'), ('weekend', 'Time_schedule_weekend_')]:
            path = args.schedules / f'{prefix}{road}.json'
            if path.exists():
                data = json.loads(path.read_text())
                if not isinstance(data, dict):
                    parser.error(f'schedule must be an object: {path}')
                schedules[road, day] = data
    report = audit_schedules(config, schedules, Lambdas.intersection_list)
    report['config_path'] = str(args.config.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(args.output.resolve()), 'missing_rule_entries': len(report['missing_rules']),
                      'raw_schedule_statuses': report['schedule_status_counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
