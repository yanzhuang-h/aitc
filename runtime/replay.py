"""隔离回放已有采集文件；默认禁用模型，不启动服务或发送现场配时。

Usage: python -m runtime.replay --tcp PATH --http PATH --output logs_data/replay/run
"""

from collections import Counter
from contextlib import ExitStack, redirect_stdout
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from itertools import zip_longest
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from unittest.mock import patch
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ReplayRecord:
    received_at: float
    source: str
    payload: dict
    timestamp_basis: str


class ReplayError(ValueError):
    """可直接给操作员显示的采集位置/调用预算错误，不包含原始报文或凭证。"""


def _timestamp(value):
    iso_timestamp = isinstance(value, str) and not value.replace('.', '', 1).isdigit()
    if iso_timestamp:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('ISO received_at requires a timezone')
        result = parsed.timestamp()
    else:
        if isinstance(value, bool):
            raise ValueError('invalid timestamp')
        result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError('invalid timestamp')
    return result / 1000 if not iso_timestamp and result >= 100_000_000_000 else result


def load_capture(path, source, *, limit=10000, skip_invalid=False):
    """仅解析 JSON，不执行采集字符串；原 payload 不重写、不平移时间。"""
    path = Path(path)
    records, errors = [], []
    truncated, invalid = False, 0
    with path.open(encoding='utf-8') as file:
        for number, line in enumerate(file, 1):
            if not line.strip():
                continue
            if len(records) >= limit:
                truncated = True
                break
            try:
                row = json.loads(line)
                pending = []
                for item in row if isinstance(row, list) else [row]:
                    if len(records) + len(pending) >= limit:
                        truncated = True
                        break
                    if not isinstance(item, dict):
                        raise ValueError('record must be an object')
                    wrapped = isinstance(item.get('payload'), dict) and 'received_at' in item
                    payload = item['payload'] if wrapped else item
                    actual_source = item.get('source', source) if wrapped else source
                    if actual_source not in ('tcp', 'http') or actual_source != source:
                        raise ValueError('source differs from selected input channel')
                    if wrapped:
                        stamp, basis = _timestamp(item['received_at']), 'received_at'
                    elif 'AITC_SYS_TS' in payload:
                        stamp, basis = _timestamp(payload['AITC_SYS_TS']), 'AITC_SYS_TS'
                    else:
                        key = next((key for key in ('ts', 'start_time', 'createTime', 'time') if key in payload), None)
                        if key is None:
                            raise ValueError('record has no replay timestamp')
                        stamp, basis = _timestamp(payload[key]), f'inferred:{key}'
                    pending.append(ReplayRecord(stamp, source, payload, basis))
                records.extend(pending)
            except (ValueError, TypeError, OverflowError):
                invalid += 1
                if len(errors) < 20:
                    errors.append(number)
                if not skip_invalid:
                    raise ReplayError(f'Invalid capture record at {path}:{number}') from None
    with path.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    gaps = []
    for record in records:
        key = next((key for key in ('ts', 'start_time', 'createTime', 'time') if key in record.payload), None)
        if key is not None:
            try:
                gaps.append(record.received_at - _timestamp(record.payload[key]))
            except (ValueError, TypeError, OverflowError):
                pass  # 接收时间有效的记录仍按原协议处理，不能替它修补传感器时间。
    return records, {'path': str(path.resolve()), 'sha256': digest, 'loaded_records': len(records),
                     'limit_per_file': limit, 'truncated': truncated, 'invalid_lines': invalid,
                     'invalid_line_numbers_first_20': errors,
                     'received_minus_sensor_seconds_min': min(gaps) if gaps else None,
                     'received_minus_sensor_seconds_max': max(gaps) if gaps else None,
                     'sensor_receive_gap_over_600s_records': sum(abs(gap) > 600 for gap in gaps),
                     'timestamp_bases': dict(Counter(record.timestamp_basis for record in records))}


def summarize_model_attempts(traces, prices=None):
    attempts, reasons = [], Counter()
    for trace in traces:
        attempts.extend(trace.get('model_attempts', []))
        if trace.get('model_reason'):
            reasons[trace['model_reason']] += 1
    latencies = sorted(attempt['latency_ms'] for attempt in attempts)
    statuses = Counter(attempt['status'] for attempt in attempts)
    usage = Counter()
    for attempt in attempts:
        usage.update(attempt.get('usage', {}))
    complete = bool(attempts) and all(
        all(key in attempt.get('usage', {}) for key in
            ('prompt_tokens', 'completion_tokens', 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens'))
        and attempt['usage']['prompt_tokens'] == attempt['usage']['prompt_cache_hit_tokens'] + attempt['usage']['prompt_cache_miss_tokens']
        for attempt in attempts
    )
    cost = None
    if complete and prices:
        cost = str(sum(Decimal(usage.get(token, 0)) * Decimal(prices[price]) / Decimal(1_000_000)
                       for token, price in [('prompt_cache_hit_tokens', 'cache_hit'),
                                            ('prompt_cache_miss_tokens', 'cache_miss'),
                                            ('completion_tokens', 'output')]))
    return {'attempts': len(attempts), 'statuses': dict(statuses),
            'valid_action_rate': statuses['valid_action'] / len(attempts) if attempts else None,
            'latency_p50_ms': latencies[math.ceil(len(latencies)*.5)-1] if latencies else None,
            'latency_p95_ms': latencies[math.ceil(len(latencies)*.95)-1] if latencies else None,
            'usage': dict(usage), 'usage_complete_for_cost': complete,
            'estimated_cost': cost, 'prices': prices,
            'cost_unavailable_reason': None if cost is not None else 'missing_prices_or_complete_usage',
            'decision_reasons': dict(reasons)}


class _TraceSink(logging.Handler):
    def __init__(self, path):
        super().__init__()
        self.records = []
        self.file = Path(path).open('w', encoding='utf-8')

    def emit(self, record):
        message = record.getMessage()
        if message.startswith('{'):
            item = json.loads(message)
            if item.get('event') == 'aitc.decision':
                self.records.append(item)
                self.file.write(message + '\n')
                self.file.flush()

    def close(self):
        self.file.close()
        super().close()


def run_worker(options, mode):
    """每个模式独立进程、固定随机种子、虚拟接收时钟与私有输出目录。"""
    root = Path(options['output']) / mode
    root.mkdir(parents=True, exist_ok=False)
    os.environ['TZ'] = 'Asia/Shanghai'
    time.tzset()
    os.environ['AITC_FLOW_ALLOCATOR_SHADOW_LOG_DIR'] = str(root / 'shadow')
    from app.config import ControlAgentSettings, RuntimeSettings
    from runtime.application import create_application
    from datahub.classifier import DataKind

    records, sources = [], []
    for source in ('tcp', 'http'):
        for path in options[source]:
            loaded, metadata = load_capture(path, source, limit=options['limit'], skip_invalid=options['skip_invalid'])
            records.extend(loaded)
            sources.append(metadata)
    records.sort(key=lambda record: record.received_at)
    if not records:
        raise ReplayError('No usable capture records')
    now = [options['start_at'] if options['start_at'] is not None else records[0].received_at]
    initial_time = now[0]
    real_localtime = time.localtime
    zone = ZoneInfo('Asia/Shanghai')

    class ReplayDate(date):
        @classmethod
        def today(cls):
            return datetime.fromtimestamp(now[0], zone).date()

    class ReplayDatetime(datetime):
        @classmethod
        def fromtimestamp(cls, stamp, tz=None):
            value = super().fromtimestamp(stamp, tz or zone)
            return value if tz else value.replace(tzinfo=None)

        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(now[0], tz)

    settings = RuntimeSettings.from_environment().validate()
    configuration_files = {}
    for name in ('intersection_result_config.json', 'lib/wwx.json', 'lib/cross_info.json',
                 'lib/road_info.json', 'lib/road_state.json', 'lib/floating_value.json',
                 'lib/green_wave_corridors.json', 'lib/experience_pool/new_wwx.json'):
        with Path(name).open('rb') as file:
            configuration_files[name] = hashlib.file_digest(file, 'sha256').hexdigest()
    use_model = mode == 'v2' and options['model']
    roads = options['roads'] if options['roads'] is not None else ','.join(settings.control_agent.roads)
    control = ControlAgentSettings(**(settings.control_agent.model_dump() | {'enabled': use_model, 'roads': roads}))
    if use_model and (not control.roads or settings.model_settings.effective_provider not in ('qwen', 'deepseek')):
        raise ReplayError('Model replay requires an enabled real provider and nonempty --roads')
    if use_model and options['rounds'] * len(control.roads) * control.max_model_calls > options['max_cloud_calls']:
        raise ReplayError('Projected cloud call budget exceeds --max-cloud-calls')
    settings = replace(settings, llm_enabled=use_model, llm_required=False, control_agent=control,
                       runtime_data_dir=root/'history', runtime_output_dir=root/'output',
                       prediction_data_dir=Path(options['prediction_dir']) if options['prediction_dir'] else root/'prediction',
                       control_snapshot_dir=root/'snapshots', control_snapshot_enabled=False,
                       enable_config_sync=False, enable_prediction_scheduler=False, enable_experience_pool_scheduler=False)
    sink = _TraceSink(root / 'decisions.jsonl')
    logger = logging.Logger(f'replay.{mode}', level=logging.INFO)
    logger.addHandler(sink)
    random.seed(options['seed'])
    app = create_application(settings=settings, logger=logger)
    if mode == 'baseline':
        app.decision_pipeline.decision_graph = None
    app.decision_pipeline.worker_count = 1
    rounds, cursor, published, gaps = [], 0, 0, set()
    try:
        with ExitStack() as stack:
            stack.enter_context(patch('time.time', side_effect=lambda: now[0]))
            stack.enter_context(patch('time.localtime', side_effect=lambda stamp=None: real_localtime(now[0] if stamp is None else stamp)))
            for target in ('lib.AITC_tool.date', 'lib.DQN_Select.date', 'lib.floating_value.date'):
                stack.enter_context(patch(target, ReplayDate))
            for target in ('lib.Global_intersection_coordinate.datetime', 'lib.lvbotest.datetime',
                           'lib.green_wave_functions.datetime', 'lib.data_ANS.flow_allocator_shadow.datetime',
                           'Flow_predict.datetime', 'Queue_predict.datetime',
                           'datahub.schemas.datetime', 'datahub.output_store.datetime',
                           'datahub.quality.datetime'):
                stack.enter_context(patch(target, ReplayDatetime))
            for index in range(options['rounds']):
                decision_time = initial_time + (index + 1) * options['interval']
                while cursor < len(records) and records[cursor].received_at <= decision_time:
                    record = records[cursor]
                    now[0] = record.received_at
                    ingest = app.tcp_server.ingestor.ingest_tcp if record.source == 'tcp' else app.tcp_server.ingestor.ingest_http
                    ingest(record.payload)
                    cursor += 1
                now[0] = decision_time
                app.datahub.cache.clear_expired()
                result = app.decision_pipeline.run_once()
                if result != app.decision_pipeline.result_warehouse.snapshot():
                    raise ReplayError('Result warehouse differs from returned batch')
                with (root / 'results.jsonl').open('a', encoding='utf-8') as file:
                    file.write(json.dumps(result, ensure_ascii=True, allow_nan=False) + '\n')
                traced, sink.records = sink.records, []
                expected = set(app.decision_pipeline.lambdas.intersection_list)
                result_ids = [item['additional']['tlLogic']['id'] for item in result]
                trace_ids = [trace['intersection_id'] for trace in traced]
                if (len(result_ids) != len(expected) or set(result_ids) != expected
                        or len(trace_ids) != len(expected) or set(trace_ids) != expected
                        or any(trace['status'] != 'published' for trace in traced)):
                    raise ReplayError('Incomplete, duplicate, or unpublished intersection batch')
                published += sum(trace['status'] == 'published' for trace in traced)
                gaps.update((trace['intersection_id'], str(trace['final_signal_plan']['program_id']), rule)
                            for trace in traced if trace['safety_report']
                            for rule in trace['safety_report']['missing_rules'])
                rounds.append({'round': index + 1, 'decision_time': decision_time,
                               'ingested_total': cursor, 'result_count': len(result),
                               'window_counts': {kind.value: app.datahub.cache.size(kind) for kind in
                                                 (DataKind.FLOW, DataKind.QUEUE, DataKind.RADAR, DataKind.BOYAN)},
                               'routes': dict(Counter(' → '.join(trace['route']) for trace in traced)),
                               'safety': dict(Counter(trace['safety_report']['safety_status'] for trace in traced))})
                if use_model and options['pace_seconds'] and index + 1 < options['rounds']:
                    time.sleep(options['pace_seconds'])
        with (root / 'decisions.jsonl').open() as file:
            metrics = summarize_model_attempts((json.loads(line) for line in file), options.get('prices'))
        report = {'mode': mode, 'model_enabled': use_model, 'model_roads': list(control.roads) if use_model else [],
                  'seed': options['seed'], 'round_interval_seconds': options['interval'],
                  'wall_pace_seconds': options['pace_seconds'] if use_model else 0,
                  'max_cloud_calls': options['max_cloud_calls'],
                  'model_request_timeout_seconds': control.timeout_seconds,
                  'capture_provenance': 'operator_supplied_local_capture',
                  'configuration_files_at_start': configuration_files,
                  'model_provider': settings.model_settings.effective_provider,
                  'sources': sources, 'rounds': rounds, 'ingested_records': cursor,
                  'records_after_last_round': len(records) - cursor, 'prediction_dir': options['prediction_dir'],
                  'model_metrics': metrics, 'safety_gaps': [{'intersection_id': road, 'program_id': program, 'missing_rule': rule}
                                                         for road, program, rule in sorted(gaps)],
                  'servers_started': False, 'field_delivery_verified': False,
                  'required_unconfigured_domains': ['pedestrian_min_green', 'conflict_matrix', 'yellow_all_red'],
                  'published_traces': published}
        (root / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        return report
    finally:
        app.stop()
        sink.close()


def compare_results(baseline, v2):
    differences = []
    order_differences = []
    for number, (left, right) in enumerate(zip_longest(baseline, v2), 1):
        if left is None or right is None:
            raise ReplayError('Replay round counts differ')
        def keyed(batch):
            indexed = {item['additional']['tlLogic']['id']: item for item in batch}
            if len(indexed) != len(batch):
                raise ReplayError(f'Duplicate intersection IDs in round {number}')
            return indexed
        a, b = keyed(left), keyed(right)
        if list(a) != list(b):
            order_differences.append({'round': number, 'baseline_order': list(a), 'v2_order': list(b)})
        for road in sorted(a.keys() | b.keys()):
            if a.get(road) != b.get(road):
                differences.append({'round': number, 'intersection_id': road})
    return {'outputs_equal': not differences and not order_differences,
            'differences': differences, 'order_differences': order_differences}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tcp', action='append', default=[], help='JSONL TCP capture; repeatable')
    parser.add_argument('--http', action='append', default=[], help='JSONL HTTP capture; repeatable')
    parser.add_argument('--output', type=Path, default=Path('logs_data/replay') / datetime.now().strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--interval', type=float, default=120, help='historical seconds per decision round')
    parser.add_argument('--pace-seconds', type=float, default=0, help='wall-clock pause between model rounds')
    parser.add_argument('--start-at', type=float, help='decision timeline starts at epoch seconds; original records unchanged')
    parser.add_argument('--limit', type=int, default=10000, help='maximum records per input file')
    parser.add_argument('--skip-invalid', action='store_true', help='count and skip invalid lines instead of failing')
    parser.add_argument('--model', action='store_true', help='explicitly enable real model in isolated V2 worker')
    parser.add_argument('--roads', help='comma-separated model intersection allowlist; otherwise use env')
    parser.add_argument('--max-cloud-calls', type=int, default=9, help='reject runs whose worst-case calls exceed this budget')
    parser.add_argument('--prediction-dir', help='optional existing read-only historical prediction repository')
    parser.add_argument('--seed', type=int, default=37)
    parser.add_argument('--cache-hit-price', type=Decimal, help='operator-supplied price per million cached input tokens')
    parser.add_argument('--cache-miss-price', type=Decimal)
    parser.add_argument('--output-price', type=Decimal)
    parser.add_argument('--currency', default='CNY')
    parser.add_argument('--worker', choices=['baseline', 'v2'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        try:
            with redirect_stdout(io.StringIO()):
                run_worker(json.load(sys.stdin), args.worker)
        except Exception as error:
            detail = {'error_type': type(error).__name__}
            if isinstance(error, ReplayError):
                detail['message'] = str(error)
            print(json.dumps(detail), file=sys.stderr)
            return 1
        return 0
    if not (args.tcp or args.http):
        parser.error('Supply at least one --tcp or --http capture file')
    if not 1 <= args.rounds <= 1000 or args.limit <= 0 or args.max_cloud_calls <= 0:
        parser.error('rounds must be 1..1000; limit and max-cloud-calls must be positive')
    if any(not math.isfinite(value) or value < 0 for value in (args.interval, args.pace_seconds)) or args.interval == 0:
        parser.error('interval must be positive; pace-seconds must be nonnegative and finite')
    if args.start_at is not None and (not math.isfinite(args.start_at) or args.start_at < 0):
        parser.error('start-at must be nonnegative and finite')
    prices = [args.cache_hit_price, args.cache_miss_price, args.output_price]
    if any(value is not None for value in prices) and (any(value is None for value in prices) or
                                                     any(not value.is_finite() or value < 0 for value in prices)):
        parser.error('provide all three finite, nonnegative token prices')
    options = vars(args).copy()
    for source in ('tcp', 'http'):
        options[source] = [str(Path(path).resolve()) for path in options[source]]
    if args.prediction_dir:
        options['prediction_dir'] = str(Path(args.prediction_dir).resolve())
    options['output'] = str(args.output.resolve())
    options['prices'] = dict(zip(['cache_hit', 'cache_miss', 'output'], map(str, prices)), currency=args.currency) if all(value is not None for value in prices) else None
    for name in ('cache_hit_price', 'cache_miss_price', 'output_price'):
        options.pop(name)
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    for mode in ('baseline', 'v2'):
        worker = subprocess.run([sys.executable, '-m', 'runtime.replay', '--worker', mode],
                                input=json.dumps(options), text=True, capture_output=True, cwd=root)
        if worker.returncode:
            print(f'{mode} replay failed; no field service started. Inspect input format/configuration.', file=sys.stderr)
            print(worker.stderr[-1000:], file=sys.stderr)
            return 1
    with (args.output/'baseline/results.jsonl').open() as baseline, (args.output/'v2/results.jsonl').open() as v2:
        report = compare_results((json.loads(line) for line in baseline), (json.loads(line) for line in v2))
    report.update(baseline=json.loads((args.output/'baseline/summary.json').read_text()),
                  v2=json.loads((args.output/'v2/summary.json').read_text()))
    (args.output/'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'report': str((args.output/'comparison.json').resolve()),
                      'outputs_equal': report['outputs_equal'], 'rounds': args.rounds,
                      'model_attempts': report['v2']['model_metrics']['attempts']}, ensure_ascii=False))
    return 0 if report['outputs_equal'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
