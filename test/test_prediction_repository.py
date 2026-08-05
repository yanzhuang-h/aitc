import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from infra.data.prediction_repository import FilePredictionRepository


class PredictionRepositoryTest(unittest.TestCase):
    def test_reads_current_output_layout_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_path = root / "flow_pre" / "2026-08-04_flow_pre.txt"
            current_path.parent.mkdir()
            current_path.write_text('{"time": "2026-08-04-10:00", "flow_data": {}}\n', encoding="utf-8")
            legacy_path = root / "2026-08-03_queue_pre.txt"
            legacy_path.write_text("{'time': '2026-08-03-10:00', 'queue_data': {}}\n", encoding="utf-8")
            repository = FilePredictionRepository(root)

            flow = repository.read_history("flow_pre", [(datetime(2026, 8, 4, 10), datetime(2026, 8, 4, 10, 10))])
            queue = repository.read_history("queue_pre", [(datetime(2026, 8, 3, 10), datetime(2026, 8, 3, 10, 10))])

            self.assertEqual(flow[0]["time"], "2026-08-04-10:00")
            self.assertEqual(queue[0]["time"], "2026-08-03-10:00")

    def test_saves_and_reads_current_window_prediction(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = FilePredictionRepository(directory)
            now = datetime(2026, 8, 5, 10, 8)
            repository.save_daily_predictions("flow", now, {"2026-08-05-10:00": {"1300068": {"avg_dur1": [1, 2, 3, 4]}}})

            self.assertEqual(repository.get_current_prediction("flow", now)["1300068"]["avg_dur1"], [1, 2, 3, 4])
            self.assertIsNone(repository.get_current_prediction("flow", now + timedelta(days=1)))


if __name__ == "__main__":
    unittest.main()
