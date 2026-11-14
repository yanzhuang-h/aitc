"""离线比较两个版本的回放结果；不运行服务、不修改配置，也不判定现场效果。"""

import argparse
from collections import Counter
from itertools import zip_longest
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.road_groups import road_group

GROUPS = ("historical", "19", "49")
LIMITATION = (
    "仅覆盖报告中已记录的输入、配置和回放条件；不证明未记录的环境、"
    "时刻表、外部预测数据完全相同，不自动批准发布。"
)


def _reject_constant(value):
    raise ValueError(f"不接受非有限数值 {value}")


def _json(text):
    return json.loads(text, parse_constant=_reject_constant)


def _object(path):
    value = _json(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return value


def _same(left, right):
    # JSON 数值类型变化也必须可见，例如相位时长 20 与 20.0。
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def _fingerprint(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _rounds(path):
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            batch = _json(line)
            if not isinstance(batch, list) or not batch:
                raise ValueError(f"{path.name} 第 {line_number} 行必须是非空结果列表")
            indexed = {}
            for payload in batch:
                try:
                    logic = payload["additional"]["tlLogic"]
                    road = logic["id"]
                except (KeyError, TypeError):
                    raise ValueError(f"{path.name} 第 {line_number} 行缺少路口标识") from None
                if (isinstance(road, bool) or not isinstance(road, (str, int))
                        or not str(road).isdigit()):
                    raise ValueError(f"{path.name} 第 {line_number} 行路口标识无效")
                road = str(road)
                if road in indexed:
                    raise ValueError(f"{path.name} 第 {line_number} 行重复路口 {road}")
                indexed[road] = payload
            count += 1
            yield indexed
    if not count:
        raise ValueError(f"{path.name} 没有回放结果")


def _conditions(summary):
    for key in ("seed", "round_interval_seconds", "sources",
                "configuration_files_at_start", "rounds", "model_enabled",
                "ingested_records", "records_after_last_round", "prediction_dir"):
        if key not in summary:
            raise ValueError(f"summary.json 缺少 {key}，不能核对回放条件")
    if type(summary["seed"]) is not int:
        raise ValueError("summary.json 随机种子无效")
    interval = summary["round_interval_seconds"]
    if (isinstance(interval, bool) or not isinstance(interval, (int, float))
            or not math.isfinite(interval) or interval <= 0):
        raise ValueError("summary.json 决策间隔无效")
    for key in ("ingested_records", "records_after_last_round"):
        if type(summary[key]) is not int or summary[key] < 0:
            raise ValueError(f"summary.json {key} 无效")
    if summary["model_enabled"] is not False:
        raise ValueError("版本基线比较要求两侧均关闭模型")
    if not summary["sources"] or not isinstance(summary["sources"], list):
        raise ValueError("summary.json 缺少输入来源")
    sources = []
    for source in summary["sources"]:
        if not isinstance(source, dict):
            raise ValueError("summary.json 输入来源格式无效")
        for key in ("sha256", "loaded_records", "limit_per_file", "truncated",
                    "invalid_lines", "timestamp_bases"):
            if key not in source:
                raise ValueError(f"summary.json 输入来源缺少 {key}")
        for key in ("loaded_records", "invalid_lines"):
            if type(source[key]) is not int or source[key] < 0:
                raise ValueError(f"summary.json {key} 无效")
        if type(source["limit_per_file"]) is not int or source["limit_per_file"] <= 0:
            raise ValueError("summary.json 读取上限无效")
        if type(source["truncated"]) is not bool:
            raise ValueError("summary.json 截断标记无效")
        bases = source["timestamp_bases"]
        if (not isinstance(bases, dict)
                or any(type(n) is not int or n < 0 for n in bases.values())
                or sum(bases.values()) != source["loaded_records"]):
            raise ValueError("summary.json 时间依据计数无效")
        sources.append({key: value for key, value in source.items() if key != "path"})
    loaded = sum(source["loaded_records"] for source in sources)
    if loaded <= 0 or loaded != summary["ingested_records"] + summary["records_after_last_round"]:
        raise ValueError("summary.json 输入记录数量不一致")
    config = summary["configuration_files_at_start"]
    if not isinstance(config, dict) or not config:
        raise ValueError("summary.json 缺少配置指纹")
    for digest in [source["sha256"] for source in sources] + list(config.values()):
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("summary.json 文件指纹无效")
    rounds = summary["rounds"]
    if not isinstance(rounds, list) or not rounds:
        raise ValueError("summary.json 缺少决策时间线")
    timeline = []
    previous_stamp, previous_ingested = None, 0
    for number, item in enumerate(rounds, 1):
        if (not isinstance(item, dict) or item.get("round") != number
                or type(item.get("result_count")) is not int or item["result_count"] <= 0):
            raise ValueError("summary.json 决策轮次或结果数量无效")
        stamp = item.get("decision_time")
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            raise ValueError("summary.json 决策时间无效")
        ingested = item.get("ingested_total")
        if (type(ingested) is not int or not previous_ingested <= ingested <= loaded
                or (previous_stamp is not None and stamp <= previous_stamp)):
            raise ValueError("summary.json 时间线或累计输入记录无效")
        previous_stamp, previous_ingested = stamp, ingested
        timeline.append({"round": number, "decision_time": stamp,
                         "ingested_total": item.get("ingested_total")})
    if previous_ingested != summary["ingested_records"]:
        raise ValueError("summary.json 最后一轮输入计数不一致")
    return {
        "seed": summary["seed"],
        "round_interval_seconds": summary["round_interval_seconds"],
        "sources": sources,
        "configuration_files_at_start": config,
        "timeline": timeline,
        "ingested_records": summary["ingested_records"],
        "records_after_last_round": summary["records_after_last_round"],
        "prediction_dir": summary["prediction_dir"],
        "capture_provenance": summary.get("capture_provenance", "unspecified"),
    }


def compare_replays(baseline, candidate):
    baseline, candidate = Path(baseline), Path(candidate)
    summary_paths = [root / "summary.json" for root in (baseline, candidate)]
    summary_hashes = [_fingerprint(path) for path in summary_paths]
    summaries = [_object(path) for path in summary_paths]
    conditions = [_conditions(summary) for summary in summaries]
    mismatches = [key for key in conditions[0] if conditions[0][key] != conditions[1][key]]
    # 外部预测目录仅有路径，没有内容指纹，不能据此声称输入相同。
    if any(summary["prediction_dir"] is not None for summary in summaries):
        mismatches.append("external_prediction_contents_unverified")
    paths = [root / "results.jsonl" for root in (baseline, candidate)]
    input_hashes = [_fingerprint(path) for path in paths]
    observed = {group: set() for group in GROUPS}
    changes, order_changes = [], []
    counts = Counter()
    rounds = 0
    for number, pair in enumerate(zip_longest(*map(_rounds, paths)), 1):
        left, right = pair
        if left is None or right is None:
            raise ValueError("两侧结果的决策轮数不一致")
        rounds = number
        for summary, batch in zip(summaries, pair):
            expected = summary["rounds"]
            if number > len(expected) or len(batch) != expected[number - 1]["result_count"]:
                raise ValueError(f"第 {number} 轮结果数量与 summary.json 不一致")
        for road in left.keys() | right.keys():
            group = road_group(road) or "historical"
            observed[group].add(road)
            if road not in left or road not in right:
                kind = "added" if road not in left else "missing"
            elif _same(left[road], right[road]):
                continue
            elif not _same(left[road]["additional"], right[road]["additional"]):
                kind = "control"
            else:
                kind = "payload_metadata"
            item = {"round": number, "road_id": road, "group": group, "kind": kind,
                    "assessment": ("historical_review_required" if group == "historical"
                                   else "fix_acceptance_pending")}
            if road in left and road in right:
                item["changed_top_level_fields"] = sorted(
                    key for key in left[road].keys() | right[road].keys()
                    if not _same(left[road].get(key), right[road].get(key))
                    or (key in left[road]) != (key in right[road]))
                if kind == "control":
                    item["baseline_control"] = left[road]["additional"]
                    item["candidate_control"] = right[road]["additional"]
            changes.append(item)
            counts[group] += 1
        # 新增路口单独记录；比较公共路口的相对顺序，避免把所有历史路口误报为重排。
        common = left.keys() & right.keys()
        a = [road for road in left if road in common]
        b = [road for road in right if road in common]
        if a != b:
            order_changes.append({"round": number, "baseline_order": a, "candidate_order": b})
    if any(rounds != len(summary["rounds"]) for summary in summaries):
        raise ValueError("结果轮数与 summary.json 不一致")
    if (input_hashes != [_fingerprint(path) for path in paths]
            or summary_hashes != [_fingerprint(path) for path in summary_paths]):
        raise ValueError("比较期间结果文件发生变化，请使用固定回放快照")
    comparable = not mismatches
    differences = bool(changes or order_changes)
    return {
        "schema_version": 1,
        "status": "incomparable" if not comparable else "differences" if differences else "identical_in_sample",
        "scope": LIMITATION,
        "rounds": rounds,
        "recorded_conditions_match": comparable,
        "condition_mismatches": mismatches,
        "input_files": [{"side": side, "results_sha256": digest, "summary_sha256": meta}
                        for side, digest, meta in zip(("baseline", "candidate"), input_hashes, summary_hashes)],
        "groups": {
            group: {
                "roads_observed": len(observed[group]),
                "changed_road_rounds": counts[group],
                "identical_in_sample": comparable and counts[group] == 0 and not order_changes
                                       if observed[group] else None,
                "problem_resolution_verified": False if group in {"19", "49"} else None,
            } for group in GROUPS
        },
        "changes": sorted(changes, key=lambda item: (item["round"], item["group"], item["road_id"])),
        "order_changes": order_changes,
        "field_effect_verified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="旧版本回放目录，含 results.jsonl 和 summary.json")
    parser.add_argument("--candidate", type=Path, required=True, help="候选版本回放目录，含相同格式的两个文件")
    parser.add_argument("--output", type=Path, help="仅创建新报告，不覆盖已有文件；默认只输出终端")
    args = parser.parse_args(argv)
    try:
        report = compare_replays(args.baseline, args.candidate)
        encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        print(encoded, end="")
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"无法完成版本对比：{error}", file=sys.stderr)
        return 2
    return 0 if report["status"] == "identical_in_sample" else 1


if __name__ == "__main__":
    raise SystemExit(main())
