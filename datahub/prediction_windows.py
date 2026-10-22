"""预测窗口工具：工作日判断与十分钟窗口生成（流量/排队预测共用）。

背景：两类预测都把一天切成 10 分钟一个窗口，对每个窗口取「历史同型日
（同为工作日或同为周末）同一窗口」的样本做按位平均。本模块收敛两份算法
文件中逐行重复的窗口工具，避免两处各自演化导致窗口边界不一致。
"""

from __future__ import annotations

from datetime import datetime, timedelta


def is_workday(day: datetime) -> bool:
    """判断日期是否为工作日（周一至周五）。

    预测按工作日/周末分型取历史：工作日回退 10 个同型日、周末回退 3 个
    （周末流量模式差异大，且回退 10 个周末约等于 70 天前的旧数据，噪声
    反而更大；调用方通过 required_days 决定回退天数）。
    """
    return day.weekday() < 5


def get_ten_minute_window(target_time: datetime) -> tuple[datetime, datetime]:
    """把目标时刻向下取整到所属十分钟窗口，返回 (窗口起点, 窗口终点)。

    例：09:37 -> (09:30, 09:40)。历史样本与每日预测均以窗口起点字符串
    "HH:MM" 作为 key，所有取数逻辑必须对齐同一规则。
    """
    minute = target_time.minute
    window_start = target_time.replace(
        minute=(minute // 10) * 10, second=0, microsecond=0
    )
    return window_start, window_start + timedelta(minutes=10)


def generate_target_windows(
    target_time_str: str, days: int, is_workday_mode: bool
) -> list[tuple[datetime, datetime]]:
    """向前收集 days 个与目标日同型日期的同一十分钟窗口。

    从目标日起逐日回退，只统计与目标日同型（同为工作日或同为周末）的
    日期，凑满 days 个即止；返回 [(窗口起点, 窗口终点), ...]。跨年/跨月
    由 datetime 运算自然处理。
    """
    target_time = datetime.strptime(target_time_str, "%Y-%m-%d-%H:%M")
    base_start, _ = get_ten_minute_window(target_time)

    windows: list[tuple[datetime, datetime]] = []
    current_date = target_time.date()
    count = 0

    while count < days:
        current_date -= timedelta(days=1)
        current_date_obj = datetime.combine(current_date, target_time.time())
        if is_workday_mode != is_workday(current_date_obj):
            continue
        window_start = datetime.combine(current_date, base_start.time())
        windows.append((window_start, window_start + timedelta(minutes=10)))
        count += 1
    return windows
