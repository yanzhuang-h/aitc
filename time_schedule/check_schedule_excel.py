#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
from datetime import datetime
import os

def check_time_coverage(df, id_value):
    """
    检查某个ID的时间覆盖是否完整
    
    Returns:
        (is_complete, issues): 是否完整，问题列表
    """
    id_data = df[df['ID'] == id_value].sort_values('开始时间').reset_index(drop=True)
    issues = []
    
    if len(id_data) == 0:
        return False, ["ID不存在"]
    
    # 检查是否从0开始
    if id_data.iloc[0]['开始时间'] != 0:
        issues.append(f"未从0开始，第一个时段从 {id_data.iloc[0]['开始时间']} 开始")
    
    # 检查是否到24结束
    if id_data.iloc[-1]['结束时间'] != 24:
        issues.append(f"未到24结束，最后时段到 {id_data.iloc[-1]['结束时间']} 结束")
    
    # 检查时间连续性
    for i in range(len(id_data) - 1):
        current_end = id_data.iloc[i]['结束时间']
        next_start = id_data.iloc[i + 1]['开始时间']
        
        if current_end != next_start:
            if current_end < next_start:
                issues.append(f"时间断档: {current_end} - {next_start}")
            else:
                issues.append(f"时间重叠: 时段{i}结束于{current_end}，时段{i+1}开始于{next_start}")
    
    # 检查时间顺序
    for i in range(len(id_data)):
        if id_data.iloc[i]['开始时间'] >= id_data.iloc[i]['结束时间']:
            issues.append(f"时段{i}时间异常: {id_data.iloc[i]['开始时间']} - {id_data.iloc[i]['结束时间']}")
    
    return len(issues) == 0, issues

def analyze_schedules(weekday_file, weekend_file):
    """
    分析工作日和周末时间表的完整性
    """
    print("=" * 80)
    print("时间表完整性检查报告")
    print("=" * 80)
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"工作日文件: {weekday_file}")
    print(f"周末文件: {weekend_file}")
    print("=" * 80)
    
    # 读取两个文件
    try:
        df_weekday = pd.read_excel(weekday_file)
        print(f"\n工作日表格读取成功，共 {len(df_weekday)} 行数据")
    except FileNotFoundError:
        print(f"\n错误：找不到工作日文件 {weekday_file}")
        return None, None
    
    try:
        df_weekend = pd.read_excel(weekend_file)
        print(f"周末表格读取成功，共 {len(df_weekend)} 行数据")
    except FileNotFoundError:
        print(f"\n错误：找不到周末文件 {weekend_file}")
        return None, None
    
    # 标准化列名
    for df in [df_weekday, df_weekend]:
        if len(df.columns) >= 4:
            df.columns = ['ID', '方案号', '开始时间', '结束时间'] + [f'相位{i}' for i in range(1, len(df.columns)-3)]
        df['ID'] = df['ID'].astype(str)
        df['开始时间'] = pd.to_numeric(df['开始时间'], errors='coerce')
        df['结束时间'] = pd.to_numeric(df['结束时间'], errors='coerce')
    
    # 获取所有唯一ID
    weekday_ids = set(df_weekday['ID'].unique())
    weekend_ids = set(df_weekend['ID'].unique())
    all_ids = weekday_ids.union(weekend_ids)
    
    print(f"\n工作日表格包含 {len(weekday_ids)} 个路口")
    print(f"周末表格包含 {len(weekend_ids)} 个路口")
    print(f"总计 {len(all_ids)} 个不同路口")
    
    # 检查ID差异
    only_weekday = weekday_ids - weekend_ids
    only_weekend = weekend_ids - weekday_ids
    
    if only_weekday:
        print(f"\n仅在工作日表格中的ID ({len(only_weekday)} 个):")
        for id_val in sorted(only_weekday):
            print(f"  - {id_val}")
    
    if only_weekend:
        print(f"\n仅在周末表格中的ID ({len(only_weekend)} 个):")
        for id_val in sorted(only_weekend):
            print(f"  - {id_val}")
    
    # 检查每个表格中的时间完整性
    print("\n" + "=" * 80)
    print("工作日时间表完整性检查:")
    print("=" * 80)
    
    weekday_issues = {}
    weekday_complete_count = 0
    
    for id_val in sorted(weekday_ids):
        is_complete, issues = check_time_coverage(df_weekday, id_val)
        if is_complete:
            weekday_complete_count += 1
        else:
            weekday_issues[id_val] = issues
    
    print(f"\n完整的时间表: {weekday_complete_count}/{len(weekday_ids)}")
    
    if weekday_issues:
        print(f"\n存在问题的ID ({len(weekday_issues)} 个):")
        for id_val, issues in sorted(weekday_issues.items())[:10]:  # 只显示前10个
            print(f"\n  ID {id_val}:")
            for issue in issues:
                print(f"    - {issue}")
        
        if len(weekday_issues) > 10:
            print(f"\n  ... 还有 {len(weekday_issues) - 10} 个ID存在问题")
    
    print("\n" + "=" * 80)
    print("周末时间表完整性检查:")
    print("=" * 80)
    
    weekend_issues = {}
    weekend_complete_count = 0
    
    for id_val in sorted(weekend_ids):
        is_complete, issues = check_time_coverage(df_weekend, id_val)
        if is_complete:
            weekend_complete_count += 1
        else:
            weekend_issues[id_val] = issues
    
    print(f"\n完整的时间表: {weekend_complete_count}/{len(weekend_ids)}")
    
    if weekend_issues:
        print(f"\n存在问题的ID ({len(weekend_issues)} 个):")
        for id_val, issues in sorted(weekend_issues.items())[:10]:  # 只显示前10个
            print(f"\n  ID {id_val}:")
            for issue in issues:
                print(f"    - {issue}")
        
        if len(weekend_issues) > 10:
            print(f"\n  ... 还有 {len(weekend_issues) - 10} 个ID存在问题")
    
    return df_weekday, df_weekend

def merge_schedules(weekday_file, weekend_file, output_weekday, output_weekend):
    """
    合并工作日和周末时间表，确保两个表都包含所有ID
    """
    print("\n" + "=" * 80)
    print("开始合并时间表...")
    print("=" * 80)
    
    # 读取数据
    df_weekday, df_weekend = analyze_schedules(weekday_file, weekend_file)
    
    if df_weekday is None or df_weekend is None:
        return
    
    # 获取ID集合
    weekday_ids = set(df_weekday['ID'].unique())
    weekend_ids = set(df_weekend['ID'].unique())
    only_weekday = weekday_ids - weekend_ids
    only_weekend = weekend_ids - weekday_ids
    
    # 补充缺失的ID
    if only_weekday:
        print(f"\n将 {len(only_weekday)} 个工作日独有的ID数据复制到周末表")
        for id_val in only_weekday:
            id_data = df_weekday[df_weekday['ID'] == id_val].copy()
            df_weekend = pd.concat([df_weekend, id_data], ignore_index=True)
    
    if only_weekend:
        print(f"\n将 {len(only_weekend)} 个周末独有的ID数据复制到工作日表")
        for id_val in only_weekend:
            id_data = df_weekend[df_weekend['ID'] == id_val].copy()
            df_weekday = pd.concat([df_weekday, id_data], ignore_index=True)
    
    # 排序
    df_weekday = df_weekday.sort_values(['ID', '开始时间']).reset_index(drop=True)
    df_weekend = df_weekend.sort_values(['ID', '开始时间']).reset_index(drop=True)
    
    # 保存结果
    df_weekday.to_excel(output_weekday, index=False)
    df_weekend.to_excel(output_weekend, index=False)
    
    print(f"\n合并完成！")
    print(f"工作日表格保存到: {output_weekday} (共{len(df_weekday)}行)")
    print(f"周末表格保存到: {output_weekend} (共{len(df_weekend)}行)")
    
    # 验证结果
    final_weekday_ids = set(df_weekday['ID'].unique())
    final_weekend_ids = set(df_weekend['ID'].unique())
    
    if final_weekday_ids == final_weekend_ids:
        print(f"\n验证成功：两个表格现在都包含 {len(final_weekday_ids)} 个相同的ID")
    else:
        print("\n警告：合并后两个表格的ID仍不一致！")

def generate_summary_report(weekday_file, weekend_file, report_file="schedule_check_report.txt"):
    """
    生成详细的检查报告
    """
    with open(report_file, 'w', encoding='utf-8') as f:
        # 重定向print输出到文件
        import sys
        original_stdout = sys.stdout
        sys.stdout = f
        
        # 执行分析
        analyze_schedules(weekday_file, weekend_file)
        
        # 恢复标准输出
        sys.stdout = original_stdout
    
    print(f"\n详细报告已保存到: {report_file}")

# 主程序
if __name__ == "__main__":
    # 文件名配置
    weekday_input = "schedule_55_standardized.xlsx"  # 标准化后的工作日文件
    weekend_input = "schedule_55_weekend_standardized.xlsx"  # 标准化后的周末文件
    
    weekday_output = "schedule_55_merged.xlsx"
    weekend_output = "schedule_55_weekend_merged.xlsx"
    
    # 检查文件是否存在
    files_exist = True
    for file in [weekday_input, weekend_input]:
        if not os.path.exists(file):
            print(f"错误：找不到文件 {file}")
            files_exist = False
    
    if not files_exist:
        print("\n请确保已经运行了标准化脚本，生成了标准化的文件")
        exit(1)
    
    # 执行合并
    merge_schedules(weekday_input, weekend_input, weekday_output, weekend_output)
    
    # 生成详细报告
    generate_summary_report(weekday_output, weekend_output)
    
    print("\n" + "=" * 80)
    print("所有处理完成！")
    print("=" * 80)
