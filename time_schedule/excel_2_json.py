#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import json
import os
from collections import defaultdict
from datetime import datetime

def update_json_from_excel(excel_file_path, json_dir, schedule_type="weekday"):
    """
    从Excel更新JSON文件，直接覆盖原文件
    
    Args:
        excel_file_path: Excel文件路径
        json_dir: JSON文件所在目录
        schedule_type: "weekday" 或 "weekend"
    """
    
    # 确定文件前缀
    if schedule_type == "weekday":
        json_prefix = "Time_schedule_"
    else:
        json_prefix = "Time_schedule_weekend_"
    
    print(f"=" * 80)
    print(f"开始更新{schedule_type}时间表")
    print(f"Excel文件: {excel_file_path}")
    print(f"JSON目录: {json_dir}")
    print(f"文件前缀: {json_prefix}")
    print(f"=" * 80)
    
    # 读取Excel文件
    try:
        df = pd.read_excel(excel_file_path)
        print(f"\n成功读取Excel文件，共{len(df)}行数据")
        
        # 处理合并单元格
        df['ID'] = df['ID'].fillna(method='ffill')
        
        # 显示列名以便调试
        print(f"Excel列名: {list(df.columns)}")
        
        # 标准化列名（如果需要）
        if '方案号' not in df.columns and len(df.columns) >= 4:
            # 假设列顺序为：ID, 方案号, 开始时间, 结束时间, 相位1-9
            df.columns = ['ID', '方案号', '开始时间', '结束时间'] + [f'相位{i}' for i in range(1, len(df.columns)-3)]
        
    except Exception as e:
        print(f"读取Excel文件失败: {e}")
        return
    
    # 获取所有唯一的路口ID
    unique_ids = df['ID'].dropna().unique()
    print(f"\n发现 {len(unique_ids)} 个路口")
    
    # 统计信息
    updated_files = 0
    created_files = 0
    error_files = 0
    
    # 按路口ID分组处理
    for intersection_id in unique_ids:
        try:
            # 获取路口ID字符串
            id_str = str(int(float(intersection_id)))
            
            # 获取该路口的所有数据
            id_data = df[df['ID'] == intersection_id].copy()
            id_data = id_data.sort_values('开始时间').reset_index(drop=True)
            
            # JSON文件路径
            json_file = os.path.join(json_dir, f"{json_prefix}{id_str}.json")
            
            # 初始化24小时数据（每小时10个元素的数组）
            hourly_data = {str(i): [0] * 10 for i in range(24)}
            
            file_exists = os.path.exists(json_file)
            if file_exists:
                print(f"\n更新路口 {id_str} (覆盖已有文件)")
            else:
                print(f"\n创建路口 {id_str} (新文件)")
                created_files += 1
            
            # 处理每个时间段
            for _, row in id_data.iterrows():
                try:
                    # 获取时间范围
                    start_time = int(row['开始时间']) if pd.notna(row['开始时间']) else 0
                    end_time = int(row['结束时间']) if pd.notna(row['结束时间']) else 0
                    
                    # 验证时间范围
                    if start_time < 0 or end_time > 24 or start_time >= end_time:
                        print(f"  警告: 时间范围异常 {start_time}-{end_time}")
                        continue
                    
                    # 获取方案号（B列）
                    plan_number = int(row['方案号']) if pd.notna(row['方案号']) else 0
                    
                    # 构建10元素数组：前9个是相位数据，第10个是方案号
                    time_array = []
                    
                    # 获取相位1-9的数据
                    for i in range(1, 10):
                        col_name = f'相位{i}'
                        if col_name in row.index and pd.notna(row[col_name]):
                            try:
                                value = int(float(row[col_name]))
                                time_array.append(value)
                            except:
                                time_array.append(0)
                        else:
                            time_array.append(0)
                    
                    # 第10位是方案号
                    time_array.append(plan_number)
                    
                    # 确保数组长度为10
                    if len(time_array) > 10:
                        time_array = time_array[:10]
                    elif len(time_array) < 10:
                        time_array.extend([0] * (10 - len(time_array)))
                    
                    # 更新对应时间段的数据
                    for hour in range(start_time, end_time):
                        if 0 <= hour <= 23:
                            hourly_data[str(hour)] = time_array.copy()
                    
                    print(f"  时段 {start_time:2d}-{end_time:2d}: 方案{plan_number}, 数据{time_array}")
                    
                except Exception as e:
                    print(f"  处理时段出错: {e}")
                    print(f"  问题行数据: {row.to_dict()}")
                    continue
            
            # 保存JSON文件（直接覆盖）
            os.makedirs(json_dir, exist_ok=True)
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(hourly_data, f, ensure_ascii=False, indent=2)
            
            updated_files += 1
            
            # 验证覆盖率
            non_zero_hours = sum(1 for h in range(24) 
                               if hourly_data[str(h)][9] != 0)  # 检查方案号是否非零
            print(f"  数据覆盖: {non_zero_hours}/24 小时")
            
        except Exception as e:
            print(f"\n处理路口 {intersection_id} 时出错: {e}")
            error_files += 1
            continue
    
    # 汇总报告
    print(f"\n" + "=" * 80)
    print(f"更新完成！")
    print(f"  更新文件: {updated_files - created_files} 个")
    print(f"  新建文件: {created_files} 个")
    print(f"  错误文件: {error_files} 个")
    print(f"  总计处理: {updated_files} 个")
    print(f"=" * 80)

def batch_update_schedules(weekday_excel, weekend_excel, json_dir):
    """
    批量更新工作日和周末时间表
    
    Args:
        weekday_excel: 工作日Excel文件路径
        weekend_excel: 周末Excel文件路径
        json_dir: JSON文件目录
    """
    print("批量更新时间表 (直接覆盖模式)")
    print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("警告: 将直接覆盖原文件，不保留备份！")
    print("-" * 80)
    
    # 更新工作日时间表
    if os.path.exists(weekday_excel):
        update_json_from_excel(weekday_excel, json_dir, schedule_type="weekday")
    else:
        print(f"\n警告: 找不到工作日文件 {weekday_excel}")
    
    print("\n" + "-" * 80 + "\n")
    
    # 更新周末时间表
    if os.path.exists(weekend_excel):
        update_json_from_excel(weekend_excel, json_dir, schedule_type="weekend")
    else:
        print(f"\n警告: 找不到周末文件 {weekend_excel}")

def verify_json_files(json_dir):
    """
    验证JSON文件的完整性和数据格式
    """
    print(f"\n验证JSON文件...")
    
    if not os.path.exists(json_dir):
        print(f"  错误: 目录 {json_dir} 不存在")
        return
    
    weekday_files = []
    weekend_files = []
    
    for file in os.listdir(json_dir):
        if file.startswith("Time_schedule_weekend_") and file.endswith(".json"):
            weekend_files.append(file)
        elif file.startswith("Time_schedule_") and not file.startswith("Time_schedule_weekend_") and file.endswith(".json"):
            weekday_files.append(file)
    
    print(f"  工作日文件: {len(weekday_files)} 个")
    print(f"  周末文件: {len(weekend_files)} 个")
    
    # 检查配对情况
    weekday_ids = set()
    weekend_ids = set()
    
    for f in weekday_files:
        id_str = f.replace("Time_schedule_", "").replace(".json", "")
        weekday_ids.add(id_str)
    
    for f in weekend_files:
        id_str = f.replace("Time_schedule_weekend_", "").replace(".json", "")
        weekend_ids.add(id_str)
    
    only_weekday = weekday_ids - weekend_ids
    only_weekend = weekend_ids - weekday_ids
    
    if only_weekday:
        print(f"\n  仅有工作日文件的ID: {', '.join(sorted(only_weekday))}")
    
    if only_weekend:
        print(f"\n  仅有周末文件的ID: {', '.join(sorted(only_weekend))}")
    
    if not only_weekday and not only_weekend:
        print("\n  ✓ 所有ID都有工作日和周末文件配对")
    
    # 验证数据格式（抽查一个文件）
    if weekday_files:
        sample_file = os.path.join(json_dir, weekday_files[0])
        try:
            with open(sample_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"\n数据格式验证 (文件: {weekday_files[0]}):")
            for hour in ['0', '12', '23']:
                if hour in data:
                    array_len = len(data[hour])
                    plan_no = data[hour][9] if len(data[hour]) >= 10 else 'N/A'
                    print(f"  时段{hour}: 数组长度={array_len}, 方案号={plan_no}")
            
        except Exception as e:
            print(f"  验证失败: {e}")

def show_sample_output(json_dir, sample_id=None):
    """
    显示示例输出，展示数据结构
    """
    print("\n" + "=" * 80)
    print("示例输出")
    print("=" * 80)
    
    if not os.path.exists(json_dir):
        print("JSON目录不存在")
        return
    
    # 找一个示例文件
    json_files = [f for f in os.listdir(json_dir) if f.endswith('.json') and f.startswith('Time_schedule_')]
    if not json_files:
        print("没有找到JSON文件")
        return
    
    # 选择示例文件
    if sample_id:
        sample_file = f"Time_schedule_{sample_id}.json"
        if sample_file not in json_files:
            sample_file = f"Time_schedule_weekend_{sample_id}.json"
    else:
        sample_file = json_files[0]
    
    sample_path = os.path.join(json_dir, sample_file)
    
    try:
        with open(sample_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"文件: {sample_file}")
        print("\n数据结构说明:")
        print("  - 每个时段是一个10元素数组")
        print("  - 前9个元素: 相位1-9的数据")
        print("  - 第10个元素: 方案号")
        
        print("\n前3个小时的数据:")
        for hour in range(3):
            hour_data = data[str(hour)]
            phases = hour_data[:9]
            plan = hour_data[9] if len(hour_data) >= 10 else 0
            print(f'  "{hour}": {hour_data},  // 相位:{phases}, 方案号:{plan}')
        
        print("  ...")
        
        print("\n最后1个小时的数据:")
        hour_data = data["23"]
        phases = hour_data[:9]
        plan = hour_data[9] if len(hour_data) >= 10 else 0
        print(f'  "23": {hour_data}  // 相位:{phases}, 方案号:{plan}')
        
    except Exception as e:
        print(f"读取示例文件失败: {e}")

# 主程序
if __name__ == "__main__":
    # 配置文件路径
    weekday_excel = "schedule_55_merged.xlsx"
    weekend_excel = "schedule_55_weekend_merged.xlsx"
    json_directory = "schedule_json"  # JSON文件目录
    
    print("JSON文件更新工具 - 直接覆盖模式")
    print("=" * 80)
    
    # 确认操作
    print("\n注意: 此操作将直接覆盖原JSON文件，不会保留备份！")
    print("数据结构: [相位1, 相位2, ..., 相位9, 方案号]")
    confirm = input("是否继续? (y/n): ")
    
    if confirm.lower() != 'y':
        print("操作已取消")
        exit(0)
    
    # 执行批量更新
    batch_update_schedules(weekday_excel, weekend_excel, json_directory)
    
    # 验证结果
    verify_json_files(json_directory)
    
    # 显示示例输出
    show_sample_output(json_directory)
    
    print("\n所有操作完成！")
