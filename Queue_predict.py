import json
from datetime import datetime, timedelta
import os
import ast
import Lambdas

LOG_DIR = 'logs_data'
PREDICTION_DIR = os.path.join(LOG_DIR, 'queue_predictions')

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

def is_workday(date):
    """判断日期是否为工作日（周一至周五）"""
    return date.weekday() < 5

def get_ten_minute_window(target_time):
    """获取十分钟时间窗口"""
    minute = target_time.minute
    window_start = target_time.replace(minute=(minute // 10)*10, second=0, microsecond=0)
    return window_start, window_start + timedelta(minutes=10)

def generate_target_windows(target_time_str, days, is_workday_mode):
    """生成历史时间窗口"""
    target_time = datetime.strptime(target_time_str, "%Y-%m-%d-%H:%M")
    base_start, base_end = get_ten_minute_window(target_time)
    
    windows = []
    current_date = target_time.date()
    delta = timedelta(days=1)
    count = 0

    while count < days:
        current_date -= delta
        current_date_obj = datetime.combine(current_date, target_time.time())
        if is_workday_mode == is_workday(current_date_obj):
            window_start = datetime.combine(current_date, base_start.time())
            windows.append((window_start, window_start + timedelta(minutes=10)))
            count += 1
    return windows

def read_queue_data(target_windows):
    """读取并过滤排队数据"""
    filtered_data = []
    for window_start, window_end in target_windows:
        date_str = window_start.strftime("%Y-%m-%d")
        file_path = os.path.join(LOG_DIR, f"{date_str}_queue_pre.txt")
        
        try:
            with open(file_path, "r") as f:
                for line in f:
                    data = ast.literal_eval(line.strip())
                    data_time = datetime.strptime(data['time'], "%Y-%m-%d-%H:%M")
                    if window_start <= data_time < window_end:
                        filtered_data.append(data)
        except FileNotFoundError:
            print(f"Warning: 排队数据文件 {file_path} 不存在")
        except SyntaxError:
            print(f"Error: 文件 {file_path} 解析失败")
    return filtered_data

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

def daily_queue_prediction():
    """每日预测任务"""
    print("############## 开始排队数据预测任务 ##############")
    os.makedirs(PREDICTION_DIR, exist_ok=True)
    
    time_windows = generate_time_windows()
    predictions = {}

    for window_start, window_end in time_windows:
        window_str = window_start.strftime("%Y-%m-%d-%H:%M")
        is_workday_mode = is_workday(window_start)
        required_days = 10 if is_workday_mode else 3
        
        # 获取历史数据
        historical_windows = generate_target_windows(window_str, required_days, is_workday_mode)
        filtered_data = read_queue_data(historical_windows)
        
        # 计算所有路口数据
        result = {}
        for iid in INTERSECTION_IDS:
            result[iid] = process_intersection_queue(filtered_data, iid)
        
        predictions[window_str] = result

    # 保存结果
    filename = f"queue_predictions_{datetime.now().strftime('%Y-%m-%d')}.json"
    filepath = os.path.join(PREDICTION_DIR, filename)
    
    with open(filepath, 'w') as f:
        json.dump(predictions, f, indent=2, ensure_ascii=False)
    
    print(f"排队预测文件已生成：{filepath}")

def get_current_queue_prediction(current_time=None):
    """
    获取当前时间对应的排队预测数据
    参数：
        current_time: datetime对象，默认使用当前系统时间
    返回：
        预测数据字典 或 None（数据不存在时）
    """
    # 确定时间窗口
    now = current_time or datetime.now()
    window_start = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
    
    # 处理23:50-23:59特殊窗口
    if window_start.minute == 50:
        window_end = window_start.replace(minute=59)
    else:
        window_end = window_start + timedelta(minutes=10)
    
    # 构建文件路径
    prediction_dir = os.path.join(LOG_DIR, 'queue_predictions')
    filename = f"queue_predictions_{now.strftime('%Y-%m-%d')}.json"
    filepath = os.path.join(prediction_dir, filename)
    
    # 读取并解析数据
    if not os.path.exists(filepath):
        print(f"警告：当日预测文件 {filename} 不存在")
        return None
    
    try:
        with open(filepath, 'r') as f:
            predictions = json.load(f)
    except Exception as e:
        print(f"文件解析失败：{str(e)}")
        return None
    
    # 查找对应时间窗口
    target_key = window_start.strftime("%Y-%m-%d-%H:%M")
    return predictions.get(target_key)


if __name__ == "__main__":
    # 测试时直接运行
    daily_queue_prediction()
    # 正式使用
    # setup_scheduler()
