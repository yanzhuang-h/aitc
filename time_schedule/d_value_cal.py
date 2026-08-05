import os
import json
import glob
from datetime import datetime

# 目录配置
SCHEDULE_DIR = 'schedule_json'
OUTPUT_DIR = 'd_value_json_2'
CONFIG_FILE = 'Config.json'

def load_json_file(file_path):
    """加载JSON文件"""
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def get_cross_ids():
    """获取所有路口ID"""
    cross_ids = set()
    
    # 查找所有时间表文件
    all_files = glob.glob(os.path.join(SCHEDULE_DIR, 'Time_schedule_*.json'))
    for file_path in all_files:
        file_name = os.path.basename(file_path)
        if file_name.startswith('Time_schedule_weekend_'):
            cross_id = file_name.replace('Time_schedule_weekend_', '').replace('.json', '')
        else:
            cross_id = file_name.replace('Time_schedule_', '').replace('.json', '')
        cross_ids.add(cross_id)
    
    return sorted(cross_ids)

def get_config_for_cross(cross_id):
    """获取路口配置"""
    config_data = load_json_file(CONFIG_FILE)
    if config_data and cross_id in config_data:
        return config_data[cross_id]
    return None

def get_schedule_for_cross(cross_id, schedule_type='weekday'):
    """获取路口时间表"""
    if schedule_type == 'weekday':
        file_path = os.path.join(SCHEDULE_DIR, f'Time_schedule_{cross_id}.json')
    else:  # weekend
        file_path = os.path.join(SCHEDULE_DIR, f'Time_schedule_weekend_{cross_id}.json')
    
    return load_json_file(file_path)

def count_non_zero_elements(lst):
    """计算列表中从头开始的连续非零元素个数"""
    count = 0
    for item in lst:
        if item != 0 and item != '0':
            count += 1
        else:
            break
    return count

def find_matching_config(config_for_cross, phase_list):
    """根据连续非零元素个数找到匹配的配置"""
    non_zero_count = count_non_zero_elements(phase_list)
    
    for config_key, config in config_for_cross.items():
        config_phase_count = count_non_zero_elements(config['phase'])
        if config_phase_count == non_zero_count:
            return config_key, config
    
    return None, None

def calculate_phase_d_value_for_cross(cross_id, schedule_type='weekday'):
    """计算路口相位差值"""
    d_value_map = {}
    negative_values = {}  # 记录负值信息
    config_for_cross = get_config_for_cross(cross_id)
    
    if config_for_cross is None:
        error_msg = f"路口 {cross_id} 的配置不存在"
        print(f"错误: {error_msg}")
        return {"status": "失败", "error": error_msg}
    
    schedule_for_cross = get_schedule_for_cross(cross_id, schedule_type)
    if schedule_for_cross is None:
        error_msg = f"路口 {cross_id} 的{schedule_type}时间表不存在"
        print(f"错误: {error_msg}")
        return {"status": "失败", "error": error_msg}
    
    try:
        # 确保输出目录存在
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        for hour, phase_list in schedule_for_cross.items():
            # 检查phase_list长度，确保有足够的元素
            if len(phase_list) < 10:
                error_msg = f"路口 {cross_id} 小时 {hour} 的相位列表长度不足"
                print(f"警告: {error_msg}")
                d_value_map[hour] = {'L': 0, 'R': 0, 'U': 0, 'D': 0}
                continue
            
            # 根据连续非零元素个数找到匹配的配置
            config_key, config = find_matching_config(config_for_cross, phase_list)
            
            if config is None:
                error_msg = f"路口 {cross_id} 小时 {hour} 的相位列表无法匹配到任何配置"
                print(f"错误: {error_msg}")
                return {"status": "失败", "error": error_msg}
            
            # 计算差值并检查负值
            d_value_map_for_hour, negative_info = calculate_phase_d_value_for_hour_with_check(config, phase_list)
            d_value_map[hour] = d_value_map_for_hour
            
            # 记录负值信息
            if negative_info:
                negative_values[hour] = negative_info
        
        # 保存结果
        if schedule_type == 'weekday':
            file_name = os.path.join(OUTPUT_DIR, f'd_value_{cross_id}.json')
        else:
            file_name = os.path.join(OUTPUT_DIR, f'd_value_{cross_id}_weekend.json')
            
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(d_value_map, f, ensure_ascii=False, indent=2)
        
        result_info = {"status": "成功", "result": d_value_map}
        if negative_values:
            result_info["negative_values"] = negative_values
        
        return result_info
    except Exception as e:
        error_msg = f"处理路口 {cross_id} 的{schedule_type}时间表时发生错误: {str(e)}"
        print(f"错误: {error_msg}")
        return {"status": "失败", "error": error_msg}

def calculate_phase_d_value_for_hour_with_check(config, phase_list):
    """
    计算各个方向上的相位差值，并检查负值
    返回差值结果和负值信息
    """
    # 计算差值
    result = calculate_phase_d_value_for_hour(config, phase_list)
    negative_info = {}
    
    # 检查负值并处理
    for direction, value in result.items():
        if value < 0:
            negative_info[direction] = value
            result[direction] = 0  # 将负值置为0
    
    return result, negative_info

def calculate_phase_d_value_for_hour(config, phase_list):
    """
    计算各个方向上的相位差值，支持所有相位类型
    无论相位出现的顺序如何，计算规则都保持一致
    """
    # 初始化结果字典
    result = {'L': 0, 'R': 0, 'U': 0, 'D': 0}
    
    # 获取相位名称列表和最小通过时间列表
    phases = config['phase']
    min_pass_times = config['min_pass_time']
    
    # 第一步：处理组合方向相位（UD/LR及其变体）
    processed_directions = process_combined_phases(phases, min_pass_times, phase_list, result)
    
    # 第二步：处理单方向相位（U/D/L/R及其变体）
    process_single_phases(phases, min_pass_times, phase_list, result, processed_directions)
    
    return result

def process_combined_phases(phases, min_pass_times, phase_list, result):
    """处理组合方向相位（UD/LR及其变体），返回已处理的方向集合"""
    processed_directions = set()
    
    # 查找UD和UD2相位
    ud_indices = []
    for i, phase in enumerate(phases):
        if phase == 'UD':
            ud_indices = [i]
            break  # 找到UD后不再查找UD2
        elif phase == 'UD2':
            ud_indices.append(i)
    
    # 处理UD/UD2相位
    if ud_indices:
        if len(ud_indices) == 1:  # 单个UD相位
            diff = phase_list[ud_indices[0]] - min_pass_times[ud_indices[0]]
        else:  # 两个UD2相位
            phase_sum = sum(phase_list[i] for i in ud_indices)
            min_sum = sum(min_pass_times[i] for i in ud_indices)
            diff = phase_sum - min_sum
        
        result['U'] = diff
        result['D'] = diff
        processed_directions.update(['U', 'D'])
    
    # 查找LR和LR2相位
    lr_indices = []
    for i, phase in enumerate(phases):
        if phase == 'LR':
            lr_indices = [i]
            break  # 找到LR后不再查找LR2
        elif phase == 'LR2':
            lr_indices.append(i)
    
    # 处理LR/LR2相位
    if lr_indices:
        if len(lr_indices) == 1:  # 单个LR相位
            diff = phase_list[lr_indices[0]] - min_pass_times[lr_indices[0]]
        else:  # 两个LR2相位
            phase_sum = sum(phase_list[i] for i in lr_indices)
            min_sum = sum(min_pass_times[i] for i in lr_indices)
            diff = phase_sum - min_sum
        
        result['L'] = diff
        result['R'] = diff
        processed_directions.update(['L', 'R'])
    
    return processed_directions

def process_single_phases(phases, min_pass_times, phase_list, result, processed_directions):
    """处理单方向相位（U/D/L/R及其变体）"""
    # 为每个方向收集索引
    u_indices, d_indices, l_indices, r_indices = [], [], [], []
    
    for i, phase in enumerate(phases):
        if phase == 'U' or phase == 'U2':
            u_indices.append(i)
        elif phase == 'D' or phase == 'D2':
            d_indices.append(i)
        elif phase == 'L' or phase == 'L2':
            l_indices.append(i)
        elif phase == 'R' or phase == 'R2':
            r_indices.append(i)
    
    # 处理U/U2相位
    if u_indices:
        if 'U' in processed_directions:
            # 如果U方向已经在组合方向中处理过，则加上所有U/U2相位的相位值（如果小于15则加15）
            for idx in u_indices:
                phase_value = phase_list[idx]
                if phase_value < 15:
                    phase_value = 15
                result['U'] += phase_value
        else:
            # 否则，计算差值
            if len(u_indices) == 1:  # 单个U相位
                result['U'] = phase_list[u_indices[0]] - min_pass_times[u_indices[0]]
            else:  # 多个U2相位
                phase_sum = sum(phase_list[i] for i in u_indices)
                min_sum = sum(min_pass_times[i] for i in u_indices)
                result['U'] = phase_sum - min_sum
    
    # 处理D/D2相位
    if d_indices:
        if 'D' in processed_directions:
            for idx in d_indices:
                phase_value = phase_list[idx]
                if phase_value < 15:
                    phase_value = 15
                result['D'] += phase_value
        else:
            if len(d_indices) == 1:
                result['D'] = phase_list[d_indices[0]] - min_pass_times[d_indices[0]]
            else:
                phase_sum = sum(phase_list[i] for i in d_indices)
                min_sum = sum(min_pass_times[i] for i in d_indices)
                result['D'] = phase_sum - min_sum
    
    # 处理L/L2相位
    if l_indices:
        if 'L' in processed_directions:
            for idx in l_indices:
                phase_value = phase_list[idx]
                if phase_value < 15:
                    phase_value = 15
                result['L'] += phase_value
        else:
            if len(l_indices) == 1:
                result['L'] = phase_list[l_indices[0]] - min_pass_times[l_indices[0]]
            else:
                phase_sum = sum(phase_list[i] for i in l_indices)
                min_sum = sum(min_pass_times[i] for i in l_indices)
                result['L'] = phase_sum - min_sum
    
    # 处理R/R2相位
    if r_indices:
        if 'R' in processed_directions:
            for idx in r_indices:
                phase_value = phase_list[idx]
                if phase_value < 15:
                    phase_value = 15
                result['R'] += phase_value
        else:
            if len(r_indices) == 1:
                result['R'] = phase_list[r_indices[0]] - min_pass_times[r_indices[0]]
            else:
                phase_sum = sum(phase_list[i] for i in r_indices)
                min_sum = sum(min_pass_times[i] for i in r_indices)
                result['R'] = phase_sum - min_sum

def generate_report(results):
    """生成工作报告"""
    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 计算成功和失败的数量
    success_count = sum(1 for r in results.values() if r.get('status') == '成功')
    failure_count = len(results) - success_count
    
    # 收集失败的详细信息和负值信息
    failure_details = {}
    negative_values_details = {}
    
    for cross_id, result in results.items():
        if result.get('status') == '失败':
            failure_details[cross_id] = result.get('error', '未知错误')
        elif result.get('status') == '成功' and 'negative_values' in result:
            negative_values_details[cross_id] = result['negative_values']
    
    report = {
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "处理文件总数": len(results),
        "成功处理数": success_count,
        "失败处理数": failure_count,
        "失败详情": failure_details,
        "负值详情": negative_values_details,
        "详细结果": results
    }
    
    # 保存报告
    report_file = os.path.join(OUTPUT_DIR, 'processing_report.json')
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    return report

def process_all_crosses():
    """处理所有路口"""
    cross_ids = get_cross_ids()
    results = {}
    
    print(f"开始处理 {len(cross_ids)} 个路口...")
    
    for cross_id in cross_ids:
        print(f"正在处理路口 {cross_id}...")
        
        # 处理工作日时间表
        result_weekday = calculate_phase_d_value_for_cross(cross_id, 'weekday')
        results[f"{cross_id}_weekday"] = result_weekday
        
        # 处理周末时间表
        result_weekend = calculate_phase_d_value_for_cross(cross_id, 'weekend')
        results[f"{cross_id}_weekend"] = result_weekend
    
    # 生成报告
    report = generate_report(results)
    
    print(f"处理完成! 成功: {report['成功处理数']}, 失败: {report['失败处理数']}")
    if report['负值详情']:
        print(f"注意: 有 {len(report['负值详情'])} 个文件存在负值，已置为0并在报告中标记")
    print(f"详细报告已保存至: {os.path.join(OUTPUT_DIR, 'processing_report.json')}")
    
    return report

def test_single_cross(cross_id, schedule_type='weekday', hour=None):
    """测试单个路口的差值计算"""
    print(f"测试路口 {cross_id} 的{schedule_type}时间表差值计算...")
    
    # 获取配置和时间表
    config_for_cross = get_config_for_cross(cross_id)
    schedule = get_schedule_for_cross(cross_id, schedule_type)
    
    if config_for_cross is None:
        error_msg = f"路口 {cross_id} 的配置不存在"
        print(f"错误: {error_msg}")
        return {"status": "失败", "error": error_msg}
    
    if schedule is None:
        error_msg = f"路口 {cross_id} 的{schedule_type}时间表不存在"
        print(f"错误: {error_msg}")
        return {"status": "失败", "error": error_msg}
    
    # 如果未指定小时，选择第一个小时
    if hour is None:
        hour = list(schedule.keys())[0]
    
    if hour not in schedule:
        error_msg = f"路口 {cross_id} 的小时 {hour} 不存在"
        print(f"错误: {error_msg}")
        return {"status": "失败", "error": error_msg}
    
    phase_list = schedule[hour]
    
    print(f"测试小时: {hour}")
    print(f"相位列表: {phase_list}")
    
    # 根据连续非零元素个数找到匹配的配置
    config_key, config = find_matching_config(config_for_cross, phase_list)
    
    if config is None:
        error_msg = f"路口 {cross_id} 小时 {hour} 的相位列表无法匹配到任何配置"
        print(f"错误: {error_msg}")
        return {"status": "失败", "error": error_msg}
    
    print(f"匹配的配置键: {config_key}")
    print(f"使用的配置: {json.dumps(config, indent=2)}")
    
    # 计算差值并检查负值
    result, negative_info = calculate_phase_d_value_for_hour_with_check(config, phase_list)
    print(f"计算结果: {result}")
    
    if negative_info:
        print(f"负值信息: {negative_info}")
    
    result_info = {"status": "成功", "result": result}
    if negative_info:
        result_info["negative_values"] = {hour: negative_info}
    
    return result_info

# 使用示例
if __name__ == "__main__":
    # 处理所有路口
    process_all_crosses()
    
    # 测试单个路口的工作日时间表
    # test_result = test_single_cross("2702784", "weekday")  # 替换为您想测试的路口ID
    # print(f"测试结果: {test_result}")
    
    # 测试单个路口的周末时间表
    # test_result = test_single_cross("2702784", "weekend")  # 替换为您想测试的路口ID
    # print(f"测试结果: {test_result}")