import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import config_api
from lib import cross_info_functions
from lib import online_intersection_config
from lib import road_info_functions
from lib import schedule_functions


def _road_state():
    return {
        "phase": ["LR", "LRL", "UD"],
        "max_pass_time": [116, 56, 74],
        "min_pass_time": [0, 0, 0],
        "platform_max_pass_time": [96, 36, 54],
        "platform_min_pass_time": [68, 25, 49],
        "phase_weight": [0, 0, 0],
    }


def _cross_info():
    return {
        "phase": {"104": "UD", "110": "LR"},
        "LaneNo": {"L": {"1": "1A"}, "R": {}, "U": {}, "D": {}},
        "jtll_ddbh": {"500005": "D", "500006": "R"},
        "zhouqi": [[104, 110], [110, 104]],
    }


class ConfigApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.road_path = root / "road_info.json"
        self.cross_path = root / "cross_info.json"
        self.code_path = root / "code_config.json"
        self.schedule_dir = root / "schedule_json"
        self.online_path = root / "online_intersection_config.json"

        self.patches = [
            mock.patch.object(road_info_functions, "ROAD_INFO_PATH", str(self.road_path)),
            mock.patch.object(cross_info_functions, "CROSS_INFO_PATH", str(self.cross_path)),
            mock.patch.object(cross_info_functions, "CODE_CONFIG_PATH", str(self.code_path)),
            mock.patch.object(schedule_functions, "SCHEDULE_DIR", self.schedule_dir),
            mock.patch.object(online_intersection_config, "ONLINE_CONFIG_PATH", str(self.online_path)),
        ]
        for patcher in self.patches:
            patcher.start()
        self.addCleanup(self.tmp.cleanup)
        for patcher in self.patches:
            self.addCleanup(patcher.stop)

    def _post(self, path, body):
        return config_api.handle_config_request("POST", path, body)

    def test_road_info_validate_then_update(self):
        payload = {"Cross_id": "1300229", "road_info": {"0": _road_state()}}

        status, body = self._post("/road_info/validate", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "validated")
        self.assertFalse(self.road_path.exists())

        status, body = self._post("/road_info/update", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        saved = json.loads(self.road_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["1300229"]["0"]["phase"], ["LR", "LRL", "UD"] + [0] * 7)

        status, body = config_api.handle_config_request("GET", "/road_info?full=false")
        self.assertEqual(body["items"], ["1300229"])

        status, body = config_api.handle_config_request("GET", "/road_info/1300229")
        self.assertIn("0", body)

    def test_road_info_delete_dry_run_and_real(self):
        payload = {"Cross_id": "1300229", "road_info": {"0": _road_state()}}
        self._post("/road_info/update", payload)

        status, body = config_api.handle_config_request(
            "DELETE", "/road_info/1300229?dry_run=true"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "validated")
        self.assertTrue(self.road_path.exists())

        status, body = config_api.handle_config_request(
            "DELETE", "/road_info/1300229?dry_run=false"
        )
        self.assertTrue(body["deleted"])
        self.assertEqual(json.loads(self.road_path.read_text(encoding="utf-8")), {})

    def test_cross_info_validate_update_and_code_config(self):
        payload = {
            "Cross_id": "1300229",
            "cross_info": _cross_info(),
            "code_config": {"global_group": "aibi_road", "cross_type": "Radar"},
        }

        status, body = self._post("/cross_info_config/validate", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "validated")
        self.assertFalse(self.cross_path.exists())

        status, body = self._post("/cross_info_config/update", payload)
        self.assertEqual(body["status"], "success")
        saved = json.loads(self.cross_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["1300229"]["Cycle"], [[104, 110], [110, 104]])
        self.assertEqual(
            saved["1300229"]["LaneNo"]["L"], {"1": "1A"}
        )
        code = json.loads(self.code_path.read_text(encoding="utf-8"))
        self.assertEqual(code["1300229"]["cross_type"], "Radar")

    def test_cross_info_rejects_bad_code_config(self):
        payload = {
            "Cross_id": "1300229",
            "cross_info": _cross_info(),
            "code_config": {"global_group": "unknown", "cross_type": "Radar"},
        }
        status, body = self._post("/cross_info_config/update", payload)
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], "error")
        self.assertFalse(self.cross_path.exists())

    def test_schedule_validate_update_and_query(self):
        schedule = {str(hour): [60, 30, 20] for hour in range(24)}
        payload = {"Cross_id": "1300229", "day_type": "workday", "schedule": schedule}

        status, body = self._post("/intersection_schedule/validate", payload)
        self.assertEqual(body["status"], "validated")
        self.assertFalse((self.schedule_dir / "Time_schedule_1300229.json").exists())

        status, body = self._post("/intersection_schedule/update", payload)
        self.assertEqual(body["status"], "success")
        path = self.schedule_dir / "Time_schedule_1300229.json"
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["0"], [60, 30, 20] + [0] * 7)

        status, body = config_api.handle_config_request(
            "GET", "/intersection_schedule/1300229?day_type=workday"
        )
        self.assertEqual(body["Cross_id"], "1300229")
        self.assertEqual(body["schedule"]["23"][:3], [60, 30, 20])

    def test_schedule_weekend_file_and_delete(self):
        payload = {
            "Cross_id": "1100308",
            "day_type": "weekend",
            "schedule": {"0": [10, 20]},
        }
        status, body = self._post("/intersection_schedule/update", payload)
        self.assertEqual(body["status"], "success")
        path = self.schedule_dir / "Time_schedule_weekend_1100308.json"
        self.assertTrue(path.exists())

        status, body = config_api.handle_config_request(
            "DELETE", "/intersection_schedule/1100308?day_type=weekend&dry_run=false"
        )
        self.assertTrue(body["deleted"])
        self.assertFalse(path.exists())

    def test_online_config_full_cover(self):
        payload = {
            "Cross_id": "1100308",
            "rid_list": [
                {"rid": "13GBT0C655013GB00C65400", "direction": "R"},
                {"rid": "13G9U0C652013GB00C65400", "direction": "L"},
            ],
        }
        status, body = self._post("/online_intersection_config/update", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertTrue(body["display_after_save"]["url"].endswith("1100308"))

        status, body = config_api.handle_config_request(
            "GET", "/online_intersection_config?Cross_id=1100308"
        )
        self.assertEqual(len(body["rid_list"]), 2)

        # 完整覆盖：再次提交只保留一条
        payload["rid_list"] = payload["rid_list"][:1]
        self._post("/online_intersection_config/update", payload)
        status, body = config_api.handle_config_request(
            "GET", "/online_intersection_config?Cross_id=1100308"
        )
        self.assertEqual(len(body["rid_list"]), 1)

    def test_online_config_rejects_empty_direction(self):
        payload = {"Cross_id": "1100308", "rid_list": [{"rid": "x", "direction": ""}]}
        status, body = self._post("/online_intersection_config/update", payload)
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], "error")

    def test_floating_value_routes(self):
        with mock.patch.object(config_api, "validate_and_save_floating_value") as fake:
            fake.return_value = {"status": "validated", "saved": False}
            status, body = self._post("/floating_value/validate", {"Cross_id": "1300069"})
            self.assertEqual(status, 200)
            fake.assert_called_once()
            self.assertTrue(fake.call_args.kwargs["dry_run"])

            fake.return_value = {"status": "success", "saved": True}
            status, body = self._post("/floating_value/update", {"Cross_id": "1300069"})
            self.assertEqual(body["saved"], True)
            self.assertFalse(fake.call_args.kwargs["dry_run"])

    def test_unknown_path_returns_none(self):
        self.assertIsNone(config_api.handle_config_request("GET", "/health"))
        self.assertIsNone(config_api.handle_config_request("GET", "/radar"))


if __name__ == "__main__":
    unittest.main()
