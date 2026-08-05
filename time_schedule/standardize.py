#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np

def standardize_schedule_with_split(input_file, output_file):
    """
    标准化时间表，确保每个ID的时间从0开始到24结束
    处理跨天时段（如22-6）并分割成两个时段
    
    Args:
        input_file: 输入的Excel文件路径
        output_file: 输出的Excel文件路径
    """
    # 读取Excel文件
    df = pd.read_excel(input_file)
    
    print("原始数据列名:", df.columns.tolist())
    print(f"原始数据行数: {len(df)}")
    
    # 标准化列名
    if len(df.columns) >= 4:
        df.columns = ['ID', '方案号', '开始时间', '结束时间'] + [f'相位{i}' for i in range(1, len(df.columns)-3)]
    
    # 删除空行
    df = df.dropna(subset=['ID'])
    
    # 转换数据类型
    df['ID'] = df['ID'].astype(str)
    df['开始时间'] = pd.to_numeric(df['开始时间'], errors='coerce')
    df['结束时间'] = pd.to_numeric(df['结束时间'], errors='coerce')
    
    # 按ID分组处理
    standardized_data = []
    
    for id_value, group in df.groupby('ID'):
        # 排序确保时间顺序正确
        group = group.sort_values('开始时间').reset_index(drop=True)
        
        print(f"\nID {id_value}:")
        print(f"  原始时段数: {len(group)}")
        
        # 创建新的时间表
        new_rows = []
        
        # 处理每个时段
        for idx, row in group.iterrows():
            start_time = row['开始时间']
            end_time = row['结束时间']
            
            # 检查是否是跨天时段（结束时间小于开始时间）
            if end_time < start_time:
                print(f"  发现跨天时段: {start_time}-{end_time}")
                
                # 分割成两个时段
                # 第一部分：从开始时间到24
                row1 = row.copy()
                row1['开始时间'] = start_time
                row1['结束时间'] = 24
                new_rows.append(row1)
                
                # 第二部分：从0到结束时间
                row2 = row.copy()
                row2['开始时间'] = 0
                row2['结束时间'] = end_time
                # 将第二部分插入到列表开头（因为是0点开始）
                new_rows.insert(0, row2)
                
                print(f"    分割为: {start_time}-24 和 0-{end_time}")
            else:
                # 正常时段，直接添加
                new_rows.append(row.copy())
        
        # 将新行列表转换为DataFrame并排序
        new_rows_df = pd.DataFrame(new_rows).sort_values('开始时间').reset_index(drop=True)
        
        # 检查并填补缺失的时段
        final_rows = []
        
        # 检查是否从0开始
        if new_rows_df.iloc[0]['开始时间'] > 0:
            # 需要补充0到第一个开始时间的时段
            # 使用第一个时段的数据
            fill_row = new_rows_df.iloc[0].copy()
            fill_row['开始时间'] = 0
            fill_row['结束时间'] = new_rows_df.iloc[0]['开始时间']
            final_rows.append(fill_row)
            print(f"  补充开始时段: 0-{new_rows_df.iloc[0]['开始时间']}")
        
        # 添加所有处理后的时段，并检查中间的连续性
        for i in range(len(new_rows_df)):
            current_row = new_rows_df.iloc[i].copy()
            
            # 如果不是第一行，检查与前一行的连续性
            if i > 0 and len(final_rows) > 0:
                last_end = final_rows[-1]['结束时间']
                current_start = current_row['开始时间']
                
                if last_end < current_start:
                    # 有时间间隙，需要填补
                    fill_row = final_rows[-1].copy()
                    fill_row['开始时间'] = last_end
                    fill_row['结束时间'] = current_start
                    final_rows.append(fill_row)
                    print(f"  补充中间时段: {last_end}-{current_start}")
            
            final_rows.append(current_row)
        
        # 检查是否到24结束
        if final_rows[-1]['结束时间'] < 24:
            # 需要补充最后时间到24的时段
            fill_row = final_rows[-1].copy()
            fill_row['开始时间'] = final_rows[-1]['结束时间']
            fill_row['结束时间'] = 24
            final_rows.append(fill_row)
            print(f"  补充结束时段: {final_rows[-2]['结束时间']}-24")
        
        # 最终验证时间连续性
        final_df = pd.DataFrame(final_rows).sort_values('开始时间').reset_index(drop=True)
        
        # 确保没有重叠
        for i in range(len(final_df) - 1):
            if final_df.iloc[i]['结束时间'] > final_df.iloc[i + 1]['开始时间']:
                print(f"  警告：时间重叠 {final_df.iloc[i]['开始时间']}-{final_df.iloc[i]['结束时间']} 与 {final_df.iloc[i + 1]['开始时间']}-{final_df.iloc[i + 1]['结束时间']}")
        
        standardized_data.extend(final_df.to_dict('records'))
        
        print(f"  标准化后时段数: {len(final_df)}")
    
    # 创建新的DataFrame
    result_df = pd.DataFrame(standardized_data)
    
    # 保存到Excel
    result_df.to_excel(output_file, index=False)
    
    print(f"\n处理完成！")
    print(f"标准化后总行数: {len(result_df)}")
    print(f"文件已保存到: {output_file}")
    
    # 验证结果
    print("\n验证结果:")
    for id_value in result_df['ID'].unique():
        id_data = result_df[result_df['ID'] == id_value]
        min_time = id_data['开始时间'].min()
        max_time = id_data['结束时间'].max()
        
        # 检查时间完整性
        time_coverage = []
        for _, row in id_data.iterrows():
            time_coverage.append((row['开始时间'], row['结束时间']))
        
        time_coverage.sort()
        print(f"  ID {id_value}: {min_time} - {max_time} (共{len(id_data)}个时段)")
        
        # 检查是否覆盖完整的0-24
        if min_time != 0 or max_time != 24:
            print(f"    警告：时间范围不完整！")
    
    return result_df

def visualize_schedule(result_df, id_to_show=None):
    """
    可视化某个ID的时间表
    
    Args:
        result_df: 处理后的DataFrame
        id_to_show: 要显示的ID，如果为None则显示第一个
    """
    if id_to_show is None:
        id_to_show = result_df['ID'].iloc[0]
    
    id_data = result_df[result_df['ID'] == id_to_show].sort_values('开始时间')
    
    print(f"\n{id_to_show} 的完整时间表:")
    print("-" * 80)
    print(f"{'开始':>6} {'结束':>6} {'方案号':>8} {'相位1':>8} {'相位2':>8} {'相位3':>8}")
    print("-" * 80)
    
    for _, row in id_data.iterrows():
        phase_cols = [col for col in id_data.columns if '相位' in col]
        phase_values = []
        for col in phase_cols[:3]:  # 只显示前3个相位
            if col in row and pd.notna(row[col]):
                phase_values.append(f"{row[col]:>8.0f}")
            else:
                phase_values.append(f"{'':>8}")
        
        print(f"{row['开始时间']:>6.0f} {row['结束时间']:>6.0f} {row['方案号']:>8.0f} " + " ".join(phase_values))

# 主程序
if __name__ == "__main__":
    input_file = "schedule_55_weekend_processed.xlsx"  # 使用之前处理过的文件
    output_file = "schedule_55_weekend_standardized.xlsx"
    
    try:
        print("开始标准化处理...")
        print("=" * 60)
        
        # 标准化处理
        result_df = standardize_schedule_with_split(input_file, output_file)
        
        # 显示一个示例
        print("\n" + "=" * 60)
        visualize_schedule(result_df)
        
    except FileNotFoundError:
        print(f"错误：找不到文件 '{input_file}'")
        print("请确保文件在当前目录下")
    except Exception as e:
        print(f"处理过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
