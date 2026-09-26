from datetime import datetime, timedelta
import logging
import Lambdas
from infra.data.prediction_repository import FilePredictionRepository
from infra.data.prediction_windows import generate_target_windows, is_workday


logger = logging.getLogger(__name__)

# 所有需要处理的路口ID列表
INTERSECTION_IDS = Lambdas.intersection_list

def queue_pre_json_gen(intersection_queue_data, end_time):
    """生成排队数据JSON结构"""
    formatted_time = datetime.fromtimestamp(int(end_time) // 1000).strftime('%Y-%m-%d-%H:%M')
    return {
        'time': formatted_time,
        'queue_data': {
            iid: {direction: values for direction, values in data.items()}
            for iid, data in intersection_queue_data.items()
        }
    }

def read_queue_data(target_windows, repository):
    """读取窗口时间范围内的排队历史样本。"""
    return repository.read_history("queue_pre", target_windows)

def calculate_direction_averages(positions_list):
    
    assert len(positions_list) == 7, f"数据维度错误: 预期7个位置，实际为{len(positions_list)}"
    return [round(sum(col)/len(col), 2) if col else 0.0 
            for col in zip(*positions_list)]

def process_intersection_queue(filtered_data, iid):
    """处理单个路口的排队数据"""
    direction_data = {
        'L': [[] for _ in range(7)],
        'R': [[] for _ in range(7)],
        'U': [[] for _ in range(7)],
        'D': [[] for _ in range(7)]
    }

    for entry in filtered_data:
        queue_data = entry.get('queue_data', {}).get(iid)
        if not queue_data:
            continue

        for direction in ['L', 'R', 'U', 'D']:
            values = queue_data.get(direction, [0]*7)
            if len(values) != 7:
                values = [0]*7

            for i in range(7):
                direction_data[direction][i].append(values[i])

    return {
        dir: calculate_direction_averages(pos_list)
        for dir, pos_list in direction_data.items()
    }

def generate_time_windows():
    """生成当天预测时间窗口"""
    now = datetime.now()
    start = now.replace(hour=5, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=50, second=0, microsecond=0)
    
    windows = []
    current = start
    while current <= end:
        windows.append((current, current + timedelta(minutes=10)))
        current += timedelta(minutes=10)
    
    # 处理23:50-23:59特殊窗口
    if windows[-1][0].minute == 50:
        windows[-1] = (windows[-1][0], windows[-1][0].replace(minute=59))
    
    return windows

def daily_queue_prediction(repository, current_time=None):
    """每日预测任务（repository 由 PredictionStore 实现注入）。"""
    now = current_time or datetime.now()
    logger.info("开始生成排队预测文件")
    
    time_windows = generate_time_windows()
    predictions = {}

    for window_start, window_end in time_windows:
        window_str = window_start.strftime("%Y-%m-%d-%H:%M")
        is_workday_mode = is_workday(window_start)
        required_days = 10 if is_workday_mode else 3
        
        # 获取历史数据
        historical_windows = generate_target_windows(window_str, required_days, is_workday_mode)
        filtered_data = read_queue_data(historical_windows, repository)
        
        # 计算所有路口数据
        result = {}
        for iid in INTERSECTION_IDS:
            result[iid] = process_intersection_queue(filtered_data, iid)
        
        predictions[window_str] = result

    filepath = repository.save_daily_predictions("queue", now, predictions)
    logger.info("排队预测文件已生成: %s", filepath)

def get_current_queue_prediction(repository, current_time=None):
    """
    获取当前时间对应的排队预测数据
    参数：
        current_time: datetime对象，默认使用当前系统时间
    返回：
        预测数据字典 或 None（数据不存在时）
    """
    now = current_time or datetime.now()
    return repository.get_current_prediction("queue", now)


if __name__ == "__main__":
    # 测试时直接运行；正式运行由 PredictionScheduler 定时触发
    daily_queue_prediction(FilePredictionRepository())
    # 正式使用
    # setup_scheduler()
