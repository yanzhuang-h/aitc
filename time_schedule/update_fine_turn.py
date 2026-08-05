import os
import json
import re
from datetime import datetime
from collections import defaultdict

class FineTurnUpdater:
    """更新fine_turn.json和fine_turn_weekend.json文件，整合所有路口的时间表数据"""
    
    def __init__(self, schedule_dir="schedule_json"):
        self.schedule_dir = schedule_dir
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
    def run(self):
        """执行主流程"""
        print("=" * 80)
        print("Fine Turn 更新工具 (从文件名提取ID整合时间表)")
        print("=" * 80)
        
        # 首先扫描所有文件，获取路口ID信息
        intersection_info = self.scan_all_intersections()
        
        # 更新普通时间表的fine_turn
        print("\n1. 更新 FIne_turn.json (工作日)")
        regular_result = self.update_fine_turn(intersection_info, is_weekend=False)
        
        # 更新周末时间表的fine_turn
        print("\n2. 更新 FIne_turn_weekend.json (周末)")
        weekend_result = self.update_fine_turn(intersection_info, is_weekend=True)
        
        # 生成更新报告
        self.generate_report(regular_result, weekend_result, intersection_info)
    
    def scan_all_intersections(self):
        """扫描所有文件，获取路口ID和对应的文件信息"""
        
        print("\n扫描所有时间表文件...")
        
        if not os.path.exists(self.schedule_dir):
            print(f"错误：目录 {self.schedule_dir} 不存在")
            return {}
        
        # 定义文件模式
        regular_pattern = re.compile(r'Time_schedule_(\d+)\.json')
        weekend_pattern = re.compile(r'Time_schedule_weekend_(\d+)\.json')
        
        intersection_info = defaultdict(lambda: {'regular_files': [], 'weekend_files': []})
        
        all_files = os.listdir(self.schedule_dir)
        regular_count = 0
        weekend_count = 0
        
        for filename in all_files:
            file_path = os.path.join(self.schedule_dir, filename)
            
            # 检查是否为工作日时间表文件
            regular_match = regular_pattern.match(filename)
            weekend_match = weekend_pattern.match(filename)
            
            if regular_match:
                intersection_id = regular_match.group(1)
                intersection_info[intersection_id]['regular_files'].append({
                    'filename': filename,
                    'file_path': file_path,
                    'intersection_id': intersection_id
                })
                regular_count += 1
                print(f"  ✓ 工作日: {filename} -> 路口ID {intersection_id}")
                
            elif weekend_match:
                intersection_id = weekend_match.group(1)
                intersection_info[intersection_id]['weekend_files'].append({
                    'filename': filename,
                    'file_path': file_path,
                    'intersection_id': intersection_id
                })
                weekend_count += 1
                print(f"  ✓ 周末: {filename} -> 路口ID {intersection_id}")
        
        # 统计信息
        total_intersections = len(intersection_info)
        regular_intersections = sum(1 for info in intersection_info.values() if info['regular_files'])
        weekend_intersections = sum(1 for info in intersection_info.values() if info['weekend_files'])
        both_intersections = sum(1 for info in intersection_info.values() if info['regular_files'] and info['weekend_files'])
        
        print(f"\n扫描完成:")
        print(f"  - 发现工作日文件: {regular_count} 个")
        print(f"  - 发现周末文件: {weekend_count} 个")
        print(f"  - 涉及路口ID总数: {total_intersections} 个")
        print(f"  - 有工作日时间表的路口: {regular_intersections} 个")
        print(f"  - 有周末时间表的路口: {weekend_intersections} 个")
        print(f"  - 同时有工作日和周末时间表的路口: {both_intersections} 个")
        
        return dict(intersection_info)
    
    def update_fine_turn(self, intersection_info, is_weekend=False):
        """更新fine_turn文件，基于路口信息智能整合"""
        
        # 确定输出文件名和文件类型
        if is_weekend:
            output_file = os.path.join(self.schedule_dir, 'FIne_turn_weekend.json')
            file_type = "周末"
            file_key = 'weekend_files'
        else:
            output_file = os.path.join(self.schedule_dir, 'FIne_turn.json')
            file_type = "工作日"
            file_key = 'regular_files'
        
        print(f"\n正在整合{file_type}时间表...")
        
        # 用于存储整合后的所有时间表数据: {id: {时间表}}
        integrated_data = {}
        
        # 统计信息
        processed_intersections = 0
        processed_files = 0
        error_count = 0
        fine_turn_count = 0
        fine_turn_ids = []
        
        # 遍历所有路口
        for intersection_id, info in intersection_info.items():
            target_files = info[file_key]
            
            if not target_files:
                continue  # 该路口没有对应类型的时间表文件
            
            # 合并该路口的所有时间表数据
            merged_schedule = {}
            intersection_has_fine_turn = False
            
            for file_info in target_files:
                try:
                    with open(file_info['file_path'], 'r', encoding='utf-8') as f:
                        schedule_data = json.load(f)
                    
                    # 文件内容直接就是时间表数据 {时间表}
                    if isinstance(schedule_data, dict):
                        # 合并时间表数据
                        merged_schedule.update(schedule_data)
                        
                        # 检查是否有fine_turn
                        if 'fine_turn' in schedule_data:
                            intersection_has_fine_turn = True
                        
                        print(f"  ✓ 路口 {intersection_id}: 从 {file_info['filename']} 合并数据")
                        processed_files += 1
                    else:
                        error_count += 1
                        print(f"  ✗ 路口 {intersection_id}: {file_info['filename']} 不是字典格式")
                    
                except json.JSONDecodeError as e:
                    error_count += 1
                    print(f"  ✗ 路口 {intersection_id}: {file_info['filename']} JSON解析错误 - {e}")
                except Exception as e:
                    error_count += 1
                    print(f"  ✗ 路口 {intersection_id}: {file_info['filename']} 读取失败 - {e}")
            
            # 将合并后的数据添加到整合数据中
            if merged_schedule:
                integrated_data[intersection_id] = merged_schedule
                processed_intersections += 1
                
                if intersection_has_fine_turn:
                    fine_turn_count += 1
                    fine_turn_ids.append(intersection_id)
                    print(f"  ✓ 路口 {intersection_id}: 整合完成 (含fine_turn)")
                else:
                    print(f"  ✓ 路口 {intersection_id}: 整合完成 (无fine_turn)")
        
        # 备份原文件（如果存在）
        if os.path.exists(output_file):
            backup_file = output_file.replace('.json', f'_backup_{self.timestamp}.json')
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, indent=4, ensure_ascii=False)
                print(f"\n已备份原文件到: {backup_file}")
            except Exception as e:
                print(f"\n警告：备份原文件失败 - {e}")
        
        # 保存整合后的数据
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(integrated_data, f, indent=4, ensure_ascii=False)
            print(f"\n成功保存到: {output_file}")
            print(f"整合了 {len(integrated_data)} 个路口的{file_type}时间表数据")
        except Exception as e:
            print(f"\n错误：保存文件失败 - {e}")
            return None
        
        # 返回处理结果
        return {
            'type': file_type,
            'output_file': output_file,
            'processed_intersections': processed_intersections,
            'processed_files': processed_files,
            'total_intersections': len(integrated_data),
            'fine_turn_count': fine_turn_count,
            'errors': error_count,
            'intersection_ids': list(integrated_data.keys()),
            'fine_turn_ids': fine_turn_ids
        }
    
    def generate_report(self, regular_result, weekend_result, intersection_info):
        """生成更新报告"""
        
        report_file = f"fine_turn_update_report_{self.timestamp}.txt"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("Fine Turn 更新报告 (从文件名提取ID整合时间表)\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"检查目录: {self.schedule_dir}\n")
            f.write("=" * 80 + "\n\n")
            
            # 路口扫描结果
            f.write("【路口扫描结果】\n")
            total_intersections = len(intersection_info)
            regular_intersections = sum(1 for info in intersection_info.values() if info['regular_files'])
            weekend_intersections = sum(1 for info in intersection_info.values() if info['weekend_files'])
            both_intersections = sum(1 for info in intersection_info.values() if info['regular_files'] and info['weekend_files'])
            
            f.write(f"发现路口总数: {total_intersections}\n")
            f.write(f"有工作日时间表的路口: {regular_intersections}\n")
            f.write(f"有周末时间表的路口: {weekend_intersections}\n")
            f.write(f"同时有工作日和周末时间表的路口: {both_intersections}\n\n")
            
            # 工作日fine_turn更新结果
            if regular_result:
                f.write("【工作日 Fine Turn 更新结果】\n")
                f.write(f"输出文件: {regular_result['output_file']}\n")
                f.write(f"处理路口数: {regular_result['processed_intersections']}\n")
                f.write(f"处理文件数: {regular_result['processed_files']}\n")
                f.write(f"整合路口总数: {regular_result['total_intersections']}\n")
                f.write(f"包含fine_turn: {regular_result['fine_turn_count']}\n")
                f.write(f"处理错误: {regular_result['errors']}\n")
                
                f.write(f"\n工作日路口ID ({len(regular_result['intersection_ids'])}个):\n")
                ids = sorted(regular_result['intersection_ids'], key=int)
                for i in range(0, len(ids), 10):
                    f.write("  " + ", ".join(ids[i:i+10]) + "\n")
                
                if regular_result['fine_turn_ids']:
                    f.write(f"\n工作日有fine_turn的路口ID ({len(regular_result['fine_turn_ids'])}个):\n")
                    fine_turn_ids = sorted(regular_result['fine_turn_ids'], key=int)
                    for i in range(0, len(fine_turn_ids), 10):
                        f.write("  " + ", ".join(fine_turn_ids[i:i+10]) + "\n")
                f.write("\n")
            
            # 周末fine_turn更新结果
            if weekend_result:
                f.write("【周末 Fine Turn 更新结果】\n")
                f.write(f"输出文件: {weekend_result['output_file']}\n")
                f.write(f"处理路口数: {weekend_result['processed_intersections']}\n")
                f.write(f"处理文件数: {weekend_result['processed_files']}\n")
                f.write(f"整合路口总数: {weekend_result['total_intersections']}\n")
                f.write(f"包含fine_turn: {weekend_result['fine_turn_count']}\n")
                f.write(f"处理错误: {weekend_result['errors']}\n")
                
                f.write(f"\n周末路口ID ({len(weekend_result['intersection_ids'])}个):\n")
                ids = sorted(weekend_result['intersection_ids'], key=int)
                for i in range(0, len(ids), 10):
                    f.write("  " + ", ".join(ids[i:i+10]) + "\n")
                
                if weekend_result['fine_turn_ids']:
                    f.write(f"\n周末有fine_turn的路口ID ({len(weekend_result['fine_turn_ids'])}个):\n")
                    fine_turn_ids = sorted(weekend_result['fine_turn_ids'], key=int)
                    for i in range(0, len(fine_turn_ids), 10):
                        f.write("  " + ", ".join(fine_turn_ids[i:i+10]) + "\n")
                f.write("\n")
            
            # 详细路口信息分析
            f.write("【详细路口信息分析】\n")
            for intersection_id in sorted(intersection_info.keys(), key=int):
                info = intersection_info[intersection_id]
                f.write(f"\n路口 {intersection_id}:\n")
                
                if info['regular_files']:
                    f.write(f"  工作日文件: {[f['filename'] for f in info['regular_files']]}\n")
                else:
                    f.write(f"  工作日文件: 无\n")
                
                if info['weekend_files']:
                    f.write(f"  周末文件: {[f['filename'] for f in info['weekend_files']]}\n")
                else:
                    f.write(f"  周末文件: 无\n")
            
            # 对比分析
            if regular_result and weekend_result:
                f.write("\n【对比分析】\n")
                regular_ids = set(regular_result['intersection_ids'])
                weekend_ids = set(weekend_result['intersection_ids'])
                regular_fine_turn_ids = set(regular_result['fine_turn_ids'])
                weekend_fine_turn_ids = set(weekend_result['fine_turn_ids'])
                
                both_schedule = regular_ids & weekend_ids
                regular_only = regular_ids - weekend_ids
                weekend_only = weekend_ids - regular_ids
                
                both_fine_turn = regular_fine_turn_ids & weekend_fine_turn_ids
                fine_turn_regular_only = regular_fine_turn_ids - weekend_fine_turn_ids
                fine_turn_weekend_only = weekend_fine_turn_ids - regular_fine_turn_ids
                
                f.write(f"同时有工作日和周末时间表的路口: {len(both_schedule)} 个\n")
                f.write(f"只有工作日时间表的路口: {len(regular_only)} 个\n")
                f.write(f"只有周末时间表的路口: {len(weekend_only)} 个\n")
                f.write(f"\n同时有工作日和周末fine_turn的路口: {len(both_fine_turn)} 个\n")
                f.write(f"只有工作日fine_turn的路口: {len(fine_turn_regular_only)} 个\n")
                f.write(f"只有周末fine_turn的路口: {len(fine_turn_weekend_only)} 个\n")
                
                if regular_only:
                    f.write(f"\n只有工作日时间表的路口:\n")
                    f.write("  " + ", ".join(sorted(regular_only, key=int)) + "\n")
                
                if weekend_only:
                    f.write(f"\n只有周末时间表的路口:\n")
                    f.write("  " + ", ".join(sorted(weekend_only, key=int)) + "\n")
                
                if fine_turn_regular_only:
                    f.write(f"\n只有工作日fine_turn的路口:\n")
                    f.write("  " + ", ".join(sorted(fine_turn_regular_only, key=int)) + "\n")
                
                if fine_turn_weekend_only:
                    f.write(f"\n只有周末fine_turn的路口:\n")
                    f.write("  " + ", ".join(sorted(fine_turn_weekend_only, key=int)) + "\n")
            
            f.write("\n" + "=" * 80 + "\n")
            f.write("报告结束\n")
        
        print(f"\n已生成更新报告: {report_file}")
        
        # 在控制台显示摘要
        print("\n" + "=" * 80)
        print("更新摘要")
        print("=" * 80)
        
        print(f"\n发现路口总数: {len(intersection_info)}")
        
        if regular_result:
            print(f"\n工作日 FIne_turn.json:")
            print(f"  - 处理了 {regular_result['processed_intersections']} 个路口")
            print(f"  - 合并了 {regular_result['processed_files']} 个文件")
            print(f"  - 整合了 {regular_result['total_intersections']} 个路口的时间表")
            print(f"  - 其中 {regular_result['fine_turn_count']} 个路口有fine_turn数据")
            print(f"  - 输出文件: {regular_result['output_file']}")
        
        if weekend_result:
            print(f"\n周末 FIne_turn_weekend.json:")
            print(f"  - 处理了 {weekend_result['processed_intersections']} 个路口")
            print(f"  - 合并了 {weekend_result['processed_files']} 个文件")
            print(f"  - 整合了 {weekend_result['total_intersections']} 个路口的时间表")
            print(f"  - 其中 {weekend_result['fine_turn_count']} 个路口有fine_turn数据")
            print(f"  - 输出文件: {weekend_result['output_file']}")


# 额外的工具函数：验证fine_turn文件的完整性
def verify_fine_turn_files(schedule_dir="schedule_json"):
    """验证fine_turn文件的完整性"""
    
    print("\n" + "=" * 80)
    print("Fine Turn 文件验证")
    print("=" * 80)
    
    files_to_check = [
        os.path.join(schedule_dir, 'FIne_turn.json'),
        os.path.join(schedule_dir, 'FIne_turn_weekend.json')
    ]
    
    for file_path in files_to_check:
        print(f"\n检查文件: {file_path}")
        
        if not os.path.exists(file_path):
            print("  ✗ 文件不存在")
            continue
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"  ✓ 文件有效")
            print(f"  - 包含 {len(data)} 个路口的时间表数据")
            
            # 统计有fine_turn的路口数量
            fine_turn_count = sum(1 for schedule_data in data.values() 
                                if isinstance(schedule_data, dict) and 'fine_turn' in schedule_data)
            print(f"  - 其中 {fine_turn_count} 个路口有fine_turn数据")
            print(f"  - fine_turn覆盖率: {fine_turn_count/len(data)*100:.1f}%")
            
            # 检查数据结构
            sample_ids = sorted(list(data.keys()), key=int)[:3]
            print(f"  - 示例路口ID: {', '.join(sample_ids)}")
            
            # 显示第一个路口的数据结构（如果有）
            if sample_ids:
                first_id = sample_ids[0]
                first_data = data[first_id]
                if isinstance(first_data, dict):
                    print(f"  - 路口 {first_id} 的数据结构:")
                    print(f"    包含字段: {list(first_data.keys())}")
                    
                    # 如果有fine_turn，显示其结构
                    if 'fine_turn' in first_data:
                        fine_turn_data = first_data['fine_turn']
                        if isinstance(fine_turn_data, dict):
                            print(f"    fine_turn包含 {len(fine_turn_data)} 个条目")
                        fine_turn_preview = json.dumps(fine_turn_data, ensure_ascii=False, indent=4)[:200]
                        print(f"    fine_turn预览: {fine_turn_preview}...")
                    else:
                        print(f"    该路口无fine_turn字段")
                else:
                    print(f"  - 路口 {first_id} 的数据不是字典格式")
                
        except json.JSONDecodeError as e:
            print(f"  ✗ JSON格式错误: {e}")
        except Exception as e:
            print(f"  ✗ 读取错误: {e}")


# 主程序
if __name__ == "__main__":
    # 创建更新器实例
    updater = FineTurnUpdater()
    
    # 执行更新
    updater.run()
    
    # 验证更新后的文件
    print("\n")
    verify_fine_turn_files()
