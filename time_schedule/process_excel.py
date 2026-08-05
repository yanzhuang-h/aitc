import pandas as pd
import numpy as np

# 读取文件
df = pd.read_excel('schedule_55_weekend.xlsx')

# 处理每一行，移除空值并左对齐
processed_rows = []
for _, row in df.iterrows():
    # 获取非空值
    non_empty_values = [val for val in row if pd.notna(val)]
    processed_rows.append(non_empty_values)

# 创建新的DataFrame
# 找出最大列数
max_cols = max(len(row) for row in processed_rows)

# 补齐行
for row in processed_rows:
    while len(row) < max_cols:
        row.append(np.nan)

# 创建新DataFrame
new_df = pd.DataFrame(processed_rows)

# 使用原始列名（如果合适的话）
if len(df.columns) >= max_cols:
    new_df.columns = df.columns[:max_cols]
else:
    # 创建新列名
    cols = list(df.columns)
    for i in range(len(df.columns), max_cols):
        cols.append(f'列{i+1}')
    new_df.columns = cols

# 保存结果
new_df.to_excel('schedule_55_weekend_processed.xlsx', index=False)

print("处理完成！文件已保存为 schedule_55_processed.xlsx")
