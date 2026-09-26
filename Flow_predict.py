from datetime import datetime, timedelta
import logging
import Lambdas
from infra.data.prediction_repository import FilePredictionRepository
from infra.data.prediction_windows import generate_target_windows, is_workday


logger = logging.getLogger(__name__)


def flow_pre_json_gen(intersection_flow_duration1, intersection_flow_duration2, end_time):
    formatted_time = datetime.fromtimestamp(int(end_time) // 1000).strftime('%Y-%m-%d-%H:%M')
    flow_pre_data = {
        'time': formatted_time,
        'flow_data': {}
    }
    for intersection_id in Lambdas.intersection_list:
        flow_data = {
            'flow_dur1': intersection_flow_duration1[intersection_id],
            'flow_dur2': intersection_flow_duration2[intersection_id]
        }
        flow_pre_data['flow_data'][intersection_id] = flow_data
    return flow_pre_data

def read_filtered_data_by_window(target_windows, repository):
    """读取窗口时间范围内的历史样本（适配特殊窗口）。"""
    return repository.read_history("flow_pre", target_windows)

def calculate_positional_averages(durations_list):
    """计算各位置平均值"""
    averages = []
    for positions in durations_list:
        avg = sum(positions) / len(positions) if positions else 0.0
        averages.append(round(avg, 2))
    return averages

def calculate_intersection_data(filtered_data, intersection_id):
    """提取并计算指定路口数据"""
    durations1 = [[] for _ in range(4)]
    durations2 = [[] for _ in range(4)]
    
    for entry in filtered_data:
        flow_data = entry.get("flow_data", {})
        intersection_data = flow_data.get(intersection_id)
        if intersection_data:
            # 处理flow_dur1
            fd1 = intersection_data.get("flow_dur1", [0]*4)
            fd1 = fd1 if len(fd1) == 4 else [0]*4
            for i in range(4):
                durations1[i].append(fd1[i])
            
            # 处理flow_dur2
            fd2 = intersection_data.get("flow_dur2", [0]*4)
            fd2 = fd2 if len(fd2) == 4 else [0]*4
            for i in range(4):
                durations2[i].append(fd2[i])
    
    return (
        calculate_positional_averages(durations1),
        calculate_positional_averages(durations2)
    )

def generate_time_windows(start_time_str, end_time_str):
    """生成当天的所有时间窗口（含23:50特殊处理）"""
    now = datetime.now()
    try:
        start_time = datetime.strptime(f"{now:%Y-%m-%d}-{start_time_str}", "%Y-%m-%d-%H:%M")
        end_time = datetime.strptime(f"{now:%Y-%m-%d}-{end_time_str}", "%Y-%m-%d-%H:%M")
    except ValueError:
        raise ValueError("时间格式应为HH:MM（24小时制）")

    windows = []
    current = start_time
    
    # 生成常规十分钟窗口
    while current <= end_time - timedelta(minutes=10):
        window_end = current + timedelta(minutes=10)
        windows.append((current, window_end))
        current = window_end
    
    # 处理23:50特殊窗口
    if end_time.strftime("%H:%M") == "23:50":
        special_window_start = end_time
        special_window_end = end_time.replace(hour=23, minute=59)
        windows.append((special_window_start, special_window_end))
    
    return windows

def get_intersection_pre_map_for_window(target_window, repository):
    """获取指定时间窗口的预测数据"""
    window_start, window_end = target_window
    target_time_str = window_start.strftime("%Y-%m-%d-%H:%M")
    
    # 判断日期类型
    is_workday_mode = is_workday(window_start)
    required_days = 10 if is_workday_mode else 3
    
    # 生成历史时间窗口
    historical_windows = generate_target_windows(target_time_str, required_days, is_workday_mode)
    
    # 读取并过滤数据
    filtered_data = read_filtered_data_by_window(historical_windows, repository)
    
    # 计算所有路口数据
    flow_pre_map = {}
    for intersection_id in Lambdas.intersection_list:
        avg_dur1, avg_dur2 = calculate_intersection_data(filtered_data, intersection_id)
        flow_pre_map[intersection_id] = {
            'avg_dur1': avg_dur1,
            'avg_dur2': avg_dur2
        }
    
    return {
        "timestamp": window_start.strftime("%Y-%m-%d-%H:%M"),
        "data": flow_pre_map
    }

def daily_prediction_job(repository, current_time=None):
    """每日预测任务入口（repository 由 PredictionStore 实现注入）。"""
    now = current_time or datetime.now()
    logger.info("开始生成流量预测文件")
    # 生成当天所有时间窗口
    time_windows = generate_time_windows("05:00", "23:50")
    # 存储所有预测结果
    daily_predictions = {}
    
    # 遍历每个时间窗口
    for window in time_windows:
        result = get_intersection_pre_map_for_window(window, repository)
        daily_predictions[result["timestamp"]] = result["data"]
    
    filepath = repository.save_daily_predictions("flow", now, daily_predictions)
    logger.info("流量预测文件已生成: %s", filepath)

def get_current_flow_prediction(repository, current_time=None):
    """
    获取当前时间对应的流量预测数据
    参数：
        current_time: datetime对象，默认使用当前系统时间
    返回：
        预测数据字典 或 None（数据不存在时）
    """
    now = current_time or datetime.now()
    return repository.get_current_prediction("flow", now)
if __name__ == "__main__":
    # 首次启动时立即执行一次（测试用；正式运行由 PredictionScheduler 定时触发）
    daily_prediction_job(FilePredictionRepository())
    
    # 正式运行使用定时任务
    # setup_scheduler()
