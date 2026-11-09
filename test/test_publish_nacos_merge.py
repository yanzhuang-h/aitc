import json
import unittest

from time_schedule.publish_nacos_schedules import build_merged_manifest


def _manifest(version, items):
    return {"schema_version": 1, "version": version, "items": items}


def _config(cross_id, value=1):
    return {
        "schema_version": 1,
        "cross_id": cross_id,
        "workday": {"0": [value] * 10},
        "weekend": None,
    }


class _FakePublisher:
    def __init__(self, store):
        self.store = store

    def fetch_config(self, data_id):
        return self.store.get(data_id)


class MergeManifestTest(unittest.TestCase):
    def test_keeps_remote_extra_cross_and_bumps_changed_local(self):
        local = _manifest(2, {
            "1300069": {"data_id": "time_schedule_1300069.json", "version": 2},
        })
        configs = {"time_schedule_1300069.json": _config("1300069", 1)}
        remote = _manifest(5, {
            "1300069": {"data_id": "time_schedule_1300069.json", "version": 4},
            "999999": {"data_id": "time_schedule_999999.json", "version": 1},
        })
        store = {
            "time_schedule_manifest.json": json.dumps(remote),
            "time_schedule_1300069.json": json.dumps(_config("1300069", 2)),
        }

        merged, changed = build_merged_manifest(
            _FakePublisher(store), local, configs, {"1300069"}
        )

        self.assertIn("999999", merged["items"])
        self.assertEqual(merged["items"]["999999"]["version"], 1)
        self.assertEqual(changed, ["1300069"])
        self.assertEqual(merged["items"]["1300069"]["version"], 5)
        self.assertEqual(merged["version"], 6)

    def test_identical_content_does_not_bump(self):
        local = _manifest(2, {
            "1300069": {"data_id": "time_schedule_1300069.json", "version": 2},
        })
        configs = {"time_schedule_1300069.json": _config("1300069", 1)}
        remote = _manifest(5, {
            "1300069": {"data_id": "time_schedule_1300069.json", "version": 2},
        })
        store = {
            "time_schedule_manifest.json": json.dumps(remote),
            "time_schedule_1300069.json": json.dumps(configs["time_schedule_1300069.json"]),
        }

        merged, changed = build_merged_manifest(
            _FakePublisher(store), local, configs, {"1300069"}
        )

        self.assertEqual(changed, [])
        self.assertEqual(merged["version"], 5)
        self.assertEqual(merged["items"]["1300069"]["version"], 2)

    def test_missing_remote_manifest_falls_back_to_local(self):
        local = _manifest(3, {
            "1300069": {"data_id": "time_schedule_1300069.json", "version": 3},
        })
        configs = {"time_schedule_1300069.json": _config("1300069", 1)}

        merged, changed = build_merged_manifest(
            _FakePublisher({}), local, configs, {"1300069"}
        )

        self.assertEqual(changed, ["1300069"])
        self.assertEqual(merged["version"], 4)
        self.assertEqual(merged["items"]["1300069"]["version"], 4)

    def test_only_selected_cross_is_bumped_others_kept(self):
        local = _manifest(2, {
            "1300069": {"data_id": "time_schedule_1300069.json", "version": 2},
            "1100308": {"data_id": "time_schedule_1100308.json", "version": 2},
        })
        configs = {
            "time_schedule_1300069.json": _config("1300069", 1),
            "time_schedule_1100308.json": _config("1100308", 9),
        }
        store = {
            "time_schedule_manifest.json": json.dumps(_manifest(2, {
                "1300069": {"data_id": "time_schedule_1300069.json", "version": 2},
                "1100308": {"data_id": "time_schedule_1100308.json", "version": 2},
            })),
            "time_schedule_1300069.json": json.dumps(_config("1300069", 2)),
        }

        merged, changed = build_merged_manifest(
            _FakePublisher(store), local, configs, {"1300069"}
        )

        self.assertEqual(changed, ["1300069"])
        self.assertEqual(merged["items"]["1300069"]["version"], 3)
        self.assertEqual(merged["items"]["1100308"]["version"], 2)


if __name__ == "__main__":
    unittest.main()
