"""运行数据聚合的行为基线测试。"""

import unittest

import Lambdas

from infra.data import cache_processor


class CacheProcessorTest(unittest.TestCase):
    def test_flow_aggregates_direction_lane_and_timestamp(self):
        flow, flow_map = cache_processor.process_flow_data([
            {"jtll_ddbh": "1", "ycsb_cdbh": "0", "ts": 1_700_000_000_000},
        ])

        self.assertEqual(flow["1300068"], [1, 0, 0, 0])
        record = flow_map["1300068"]["1700000000"]
        self.assertEqual(record["pass"]["L"][0], 1)
        self.assertEqual(record["count"]["L"], 1)

    def test_queue_aggregates_lane_queue_and_vehicle_count(self):
        lengths, queue_map = cache_processor.process_queue_data([
            {
                "jtll_ddbh": "1",
                "start_time": 1_700_000_000_000,
                "car_nums": [{"ycsb_cdbh": "0", "queue": 12, "all": 18}],
            },
        ])

        self.assertEqual(lengths["1300068"]["L"][0], 12)
        record = queue_map["1300068"]["1700000000"]
        self.assertEqual(record["queue"]["L"][0], 12)
        self.assertEqual(record["all"]["L"][0], 18)

    def test_stage_and_extend_data_use_intersection_time_buckets(self):
        stage_map = cache_processor.process_stage_data([
            {"CrossId": "1300068", "time": 1_700_000_000_000, "curStageNo": "3", "curStageLen": "19"},
        ])
        extend_map = cache_processor.process_extend_data([
            (1_700_000_000, {"CrossId": "1300068", "curStageRemainLen": 8}),
        ])

        self.assertEqual(stage_map["1300068"][1_700_000_000]["curStageNo"], 3)
        self.assertEqual(stage_map["1300068"][1_700_000_000]["curStageLen"], 19)
        self.assertEqual(extend_map["1300068"][1_700_000_000][0]["curStageRemainLen"], 8)

    def test_online_data_uses_registered_rid(self):
        rid = next(iter(Lambdas.online_data_map_lambda))
        online_map = cache_processor.process_online_data([
            (1_700_000_000, {"rid": rid, "online": 1}),
        ])

        self.assertEqual(online_map[rid][1_700_000_000][0]["online"], 1)

    def test_radar_and_boyan_data_use_registered_devices(self):
        radar_device, (radar_intersection, _direction) = next(iter(Lambdas.device_to_location.items()))
        radar_map = cache_processor.process_radar_data([
            (1_700_000_000, {"deviceNo": radar_device, "speed": 32}),
        ])
        boyan_map = cache_processor.process_boyan_data([
            (1_700_000_000, {"deviceId": "000000000001", "value": 4}),
        ])

        self.assertEqual(radar_map[radar_intersection][1_700_000_000][0]["speed"], 32)
        self.assertEqual(boyan_map["1300644"]["U"][1_700_000_000][0]["value"], 4)


if __name__ == "__main__":
    unittest.main()
