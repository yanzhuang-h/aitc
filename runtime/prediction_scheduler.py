"""预测任务的运行期调度与生命周期管理。"""

from __future__ import annotations

from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler


class PredictionScheduler:
    """统一管理流量与排队预测任务，不参与预测算法实现。"""

    def __init__(
        self,
        *,
        flow_job: Callable[[], None],
        queue_job: Callable[[], None],
        hour: int,
        minute: int,
        scheduler_factory: Callable[..., Any] = BackgroundScheduler,
        logger: Any | None = None,
    ) -> None:
        self.flow_job = flow_job
        self.queue_job = queue_job
        self.hour = hour
        self.minute = minute
        self.scheduler_factory = scheduler_factory
        self.logger = logger
        self._scheduler: Any | None = None

    def start(self) -> None:
        """创建并启动每日预测任务；重复调用不会重复注册。"""
        if self._scheduler is not None:
            return
        scheduler = self.scheduler_factory(timezone="Asia/Shanghai")
        scheduler.add_job(
            self.flow_job,
            "cron",
            hour=self.hour,
            minute=self.minute,
            misfire_grace_time=300,
            id="flow_prediction",
            replace_existing=True,
        )
        scheduler.add_job(
            self.queue_job,
            "cron",
            hour=self.hour,
            minute=self.minute,
            misfire_grace_time=300,
            id="queue_prediction",
            replace_existing=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        self._info("预测任务调度器已启动")

    def stop(self) -> None:
        """停止后台调度器，避免服务关闭后仍保留任务线程。"""
        if self._scheduler is None:
            return
        self._scheduler.shutdown(wait=False)
        self._scheduler = None
        self._info("预测任务调度器已停止")

    def _info(self, message: str) -> None:
        if self.logger is not None:
            self.logger.info(message)
