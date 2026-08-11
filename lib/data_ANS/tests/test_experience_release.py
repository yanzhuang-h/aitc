import json
import tempfile
import unittest
from pathlib import Path

from lib.data_ANS import experience_release as RELEASE


def _flow(lane, value):
    result = [0] * 10
    result[lane] = value
    return result


class ExperienceReleaseTests(unittest.TestCase):
    def _cross_info(self):
        return {
            "1300069": {
                "LaneNo": {
                    "U": {"1": "1A", "2": "1B"},
                    "D": {"1": "1B"},
                }
            }
        }

    def _candidate(self):
        return {
            "1300069": {
                "U": {"30": _flow(2, 20)},
                "UTL": {"20": _flow(1, 8)},
            }
        }

    def test_release_dry_run_then_activate_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path = root / "candidate.json"
            selection_path = root / "selection.json"
            completion_path = root / "completion.json"
            runtime_path = root / "wwx.json"
            cross_info_path = root / "cross_info.json"
            versions_dir = root / "versions"
            manifest_path = versions_dir / "active_manifest.json"

            candidate_path.write_text(json.dumps(self._candidate()), encoding="utf-8")
            selection_path.write_text(json.dumps({
                "selection": "audit_gated_nearest_rank_percentile_per_lane",
                "policy": {"min_sample_count": 5, "min_date_support": 2},
                "summary": {"accepted_points": 2},
                "output_path": str(root / "selected.json"),
            }), encoding="utf-8")
            completion_path.write_text(json.dumps({
                "completion_mode": "preserve_trusted_points_interpolation",
                "summary": {
                    "source_points": 2,
                    "completed_points": 2,
                    "changed_source_points": 0,
                    "removed_source_points": 0,
                },
                "input_path": str(root / "selected.json"),
                "output_path": str(candidate_path),
            }), encoding="utf-8")
            cross_info_path.write_text(json.dumps(self._cross_info()), encoding="utf-8")
            runtime_path.write_text(json.dumps({
                "1300069": {"D": {"20": _flow(1, 9)}}
            }), encoding="utf-8")

            dry_run = RELEASE.release_experience_table(
                str(candidate_path),
                str(selection_path),
                str(completion_path),
                str(runtime_path),
                str(cross_info_path),
                str(versions_dir),
                str(manifest_path),
                activate=False,
            )
            self.assertFalse(dry_run["activated"])
            self.assertFalse(manifest_path.exists())
            self.assertEqual(
                json.loads(runtime_path.read_text(encoding="utf-8"))["1300069"],
                {"D": {"20": _flow(1, 9)}},
            )

            activated = RELEASE.release_experience_table(
                str(candidate_path),
                str(selection_path),
                str(completion_path),
                str(runtime_path),
                str(cross_info_path),
                str(versions_dir),
                str(manifest_path),
                activate=True,
            )
            self.assertTrue(activated["activated"])
            active = json.loads(runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(active["1300069"]["U"]["30"], _flow(2, 20))
            self.assertEqual(active["1300069"]["D"]["20"], _flow(1, 9))
            self.assertTrue(Path(activated["manifest"]["version_path"]).exists())
            self.assertTrue(Path(activated["manifest"]["rollback_version_path"]).exists())

            rollback = RELEASE.rollback_experience_table(
                str(runtime_path),
                str(manifest_path),
                str(cross_info_path),
            )
            self.assertTrue(rollback["validation"]["valid"])
            self.assertEqual(
                json.loads(runtime_path.read_text(encoding="utf-8"))["1300069"],
                {"D": {"20": _flow(1, 9)}},
            )

    def test_left_turn_requires_a_configured_1a_lane(self):
        table = {"1300069": {"UTL": {"20": _flow(1, 5)}}}
        cross_info = {"1300069": {"LaneNo": {"U": {"1": "1B"}}}}

        report = RELEASE.validate_experience_table(table, cross_info)

        self.assertFalse(report["valid"])
        self.assertIn("no configured 1A lane", report["errors"][0])

    def test_release_rejects_nonzero_uncontrolled_or_unverified_lanes(self):
        cross_info = {
            "1300069": {
                "LaneNo": {
                    "U": {
                        "2": "1B",
                        "3": "1C",
                        "4": "3A",
                        "5": "3B",
                    }
                }
            }
        }
        for lane in (3, 4, 5):
            with self.subTest(lane=lane):
                table = {"1300069": {"U": {"30": _flow(lane, 5)}}}

                report = RELEASE.validate_experience_table(table, cross_info)

                self.assertFalse(report["valid"])
                self.assertTrue(
                    any("nonzero flow outside configured lanes" in error
                        for error in report["errors"])
                )

    def test_runtime_compatibility_keeps_legacy_records_as_warnings(self):
        table = {
            "1300069": {
                "U": {
                    "0": _flow(1, 4),
                    "30": _flow(1, 5),
                }
            }
        }

        strict = RELEASE.validate_experience_table(table, self._cross_info())
        compatible = RELEASE.validate_experience_table(
            table,
            self._cross_info(),
            required_road_ids={"1300069"},
            allow_legacy_records=True,
        )

        self.assertFalse(strict["valid"])
        self.assertTrue(compatible["valid"])
        self.assertGreaterEqual(len(compatible["warnings"]), 2)

    def test_daily_pool_table_can_be_validated_versioned_and_activated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / "wwx.json"
            cross_info_path = root / "cross_info.json"
            versions_dir = root / "versions"
            manifest_path = versions_dir / "active_manifest.json"
            old_table = {
                "1300069": {"U": {"30": _flow(2, 20)}}
            }
            new_table = {
                "1300069": {"U": {"30": _flow(2, 24)}}
            }
            runtime_path.write_text(json.dumps(old_table), encoding="utf-8")
            cross_info_path.write_text(
                json.dumps(self._cross_info()),
                encoding="utf-8",
            )

            result = RELEASE.activate_validated_experience_table(
                table=new_table,
                runtime_path=str(runtime_path),
                cross_info_path=str(cross_info_path),
                versions_dir=str(versions_dir),
                manifest_path=str(manifest_path),
                release_kind="daily_experience_pool",
                source_metadata={"source_date": "2026-07-24"},
            )

            self.assertTrue(result["activated"])
            self.assertEqual(
                json.loads(runtime_path.read_text(encoding="utf-8")),
                new_table,
            )
            self.assertEqual(
                result["manifest"]["release_kind"],
                "daily_experience_pool",
            )
            self.assertEqual(
                result["manifest"]["source_metadata"]["source_date"],
                "2026-07-24",
            )

    def test_manual_bootstrap_release_needs_no_p80_selection_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path = root / "bootstrap.json"
            completion_path = root / "bootstrap_report.json"
            runtime_path = root / "wwx.json"
            cross_info_path = root / "cross_info.json"
            versions_dir = root / "versions"
            candidate_path.write_text(
                json.dumps(self._candidate()),
                encoding="utf-8",
            )
            completion_path.write_text(json.dumps({
                "completion_mode": "preserve_trusted_points_interpolation",
                "summary": {
                    "source_points": 1,
                    "completed_points": 2,
                    "changed_source_points": 0,
                    "removed_source_points": 0,
                },
                "output_path": str(candidate_path),
            }), encoding="utf-8")
            runtime_path.write_text("{}", encoding="utf-8")
            cross_info_path.write_text(
                json.dumps(self._cross_info()),
                encoding="utf-8",
            )

            dry_run = RELEASE.release_bootstrap_experience_table(
                candidate_path=str(candidate_path),
                completion_report_path=str(completion_path),
                runtime_path=str(runtime_path),
                cross_info_path=str(cross_info_path),
                versions_dir=str(versions_dir),
                activate=False,
            )

            self.assertFalse(dry_run["activated"])
            self.assertTrue(dry_run["validation"]["table"]["valid"])
            self.assertTrue(dry_run["validation"]["completion"]["valid"])


if __name__ == "__main__":
    unittest.main()
