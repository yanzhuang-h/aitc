import unittest

from runtime.prediction_scheduler import PredictionScheduler


class _Scheduler:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.jobs = []
        self.started = False
        self.shutdown_calls = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((func, trigger, kwargs))

    def start(self):
        self.started = True

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)


class PredictionSchedulerTest(unittest.TestCase):
    def test_registers_both_daily_jobs_and_stops_scheduler(self):
        schedulers = []

        def factory(**kwargs):
            scheduler = _Scheduler(**kwargs)
            schedulers.append(scheduler)
            return scheduler

        scheduler = PredictionScheduler(
            flow_job=lambda: None,
            queue_job=lambda: None,
            hour=3,
            minute=5,
            scheduler_factory=factory,
        )
        scheduler.start()
        scheduler.start()
        scheduler.stop()

        self.assertEqual(len(schedulers), 1)
        registered = schedulers[0]
        self.assertEqual(registered.kwargs["timezone"], "Asia/Shanghai")
        self.assertTrue(registered.started)
        self.assertEqual(
            [job[2]["id"] for job in registered.jobs],
            ["flow_prediction", "queue_prediction"],
        )
        self.assertEqual(registered.shutdown_calls, [{"wait": False}])


if __name__ == "__main__":
    unittest.main()
