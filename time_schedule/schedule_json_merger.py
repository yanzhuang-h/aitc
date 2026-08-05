import os
import shutil
import json
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

class ScheduleJsonMerger:
    """合并和分析时间表JSON文件的工具类"""
    
    def __init__(self, fixed_dir="intersection_json_fixed", 
                 original_dir="schedule_json"):
        self.fixed_dir = fixed_dir
        self.original_dir = original_dir
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.backup_dir = f"{original_dir}_backup_{self.timestamp}"
        self.merge_report_file = f"merge_report_{self.timestamp}.txt"
        self.analysis_report_file = f"schedule_analysis_report_{self.timestamp}.txt"
        
    def run(self):
        """执行完整的合并和分析流程"""
        print("=" * 80)
        print("时间表JSON文件合并与分析工具")
        print("=" * 80)
        
        # 步骤1：合并目录
        print("\n步骤1：合并JSON目录")
        print("-" * 40)
        merge_stats = self.merge_json_directories()
        
        if not merge_stats:
            print("合并失败，程序终止")
            return
        
        # 步骤2：分析合并后的目录
        print("\n步骤2：分析合并后的目录")
        print("-" * 40)
        id_files, all_ids = self.analyze_schedule_json_files()
        
        # 步骤3：生成综合报告
        print("\n步骤3：生成综合报告")
        print("-" * 40)
        self.generate_combined_report(merge_stats, id_files, all_ids)
        
        print("\n" + "=" * 80)
        print("所有操作完成！")
        print(f"- 合并报告: {self.merge_report_file}")
        print(f"- 分析报告: {self.analysis_report_file}")
        print(f"- 备份目录: {self.backup_dir}")
        print("=" * 80)
    
    def merge_json_directories(self):
        """合并两个JSON目录，fixed目录中的文件优先"""
        
        # 检查目录是否存在
        if not os.path.exists(self.fixed_dir):
            print(f"错误：目录 {self.fixed_dir} 不存在")
            return None
        
        if not os.path.exists(self.original_dir):
            print(f"错误：目录 {self.original_dir} 不存在")
            return None
        
        # 创建备份目录
        print(f"创建备份目录: {self.backup_dir}")
        shutil.copytree(self.original_dir, self.backup_dir)
        
        # 获取两个目录中的所有JSON文件
        fixed_files = {f for f in os.listdir(self.fixed_dir) if f.endswith('.json')}
        original_files = {f for f in os.listdir(self.original_dir) if f.endswith('.json')}
        
        # 统计信息
        stats = {
            'total_fixed': len(fixed_files),
            'total_original': len(original_files),
            'replaced': [],
            'new_added': [],
            'unchanged': [],
            'file_details': []
        }
        
        # 处理fixed目录中的文件
        print("\n开始合并文件...")
        
        for filename in fixed_files:
            fixed_path = os.path.join(self.fixed_dir, filename)
            original_path = os.path.join(self.original_dir, filename)
            
            if filename in original_files:
                # 文件存在于两个目录中，比较内容
                try:
                    with open(fixed_path, 'r', encoding='utf-8') as f:
                        fixed_content = json.load(f)
                    with open(original_path, 'r', encoding='utf-8') as f:
                        original_content = json.load(f)
                    
                    if fixed_content != original_content:
                        # 内容不同，替换文件
                        shutil.copy2(fixed_path, original_path)
                        stats['replaced'].append(filename)
                        stats['file_details'].append({
                            'file': filename,
                            'action': 'replaced',
                            'reason': '内容已更新'
                        })
                        print(f"  ✓ 替换: {filename}")
                    else:
                        # 内容相同，无需操作
                        stats['unchanged'].append(filename)
                        stats['file_details'].append({
                            'file': filename,
                            'action': 'unchanged',
                            'reason': '内容相同'
                        })
                        
                except Exception as e:
                    print(f"  ✗ 错误处理 {filename}: {str(e)}")
                    stats['file_details'].append({
                        'file': filename,
                        'action': 'error',
                        'reason': str(e)
                    })
            else:
                # 文件只存在于fixed目录中，复制到original目录
                shutil.copy2(fixed_path, original_path)
                stats['new_added'].append(filename)
                stats['file_details'].append({
                    'file': filename,
                    'action': 'added',
                    'reason': '新文件'
                })
                print(f"  + 新增: {filename}")
        
        # 识别只在original目录中的文件
        only_in_original = original_files - fixed_files
        stats['only_in_original'] = list(only_in_original)
        
        # 生成合并报告
        self.generate_merge_report(stats)
        
        # 打印合并摘要
        print(f"\n合并完成！")
        print(f"  - 共处理 {stats['total_fixed']} 个fixed文件")
        print(f"  - 替换了 {len(stats['replaced'])} 个文件")
        print(f"  - 新增了 {len(stats['new_added'])} 个文件")
        print(f"  - {len(stats['unchanged'])} 个文件内容相同")
        
        return stats
    
    def generate_merge_report(self, stats):
        """生成合并报告"""
        with open(self.merge_report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"JSON目录合并报告\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            # 概览
            f.write("【合并概览】\n")
            f.write(f"- intersection_json_fixed 文件数: {stats['total_fixed']}\n")
            f.write(f"- schedule_json 原始文件数: {stats['total_original']}\n")
            f.write(f"- 替换文件数: {len(stats['replaced'])}\n")
            f.write(f"- 新增文件数: {len(stats['new_added'])}\n")
            f.write(f"- 未修改文件数: {len(stats['unchanged'])}\n")
            f.write(f"- 仅在原始目录中的文件数: {len(stats['only_in_original'])}\n")
            f.write(f"- 备份目录: {self.backup_dir}\n\n")
            
            # 替换的文件
            if stats['replaced']:
                f.write("【替换的文件】\n")
                for i, filename in enumerate(sorted(stats['replaced']), 1):
                    f.write(f"{i:3d}. {filename}\n")
                f.write("\n")
            
            # 新增的文件
            if stats['new_added']:
                f.write("【新增的文件】\n")
                for i, filename in enumerate(sorted(stats['new_added']), 1):
                    f.write(f"{i:3d}. {filename}\n")
                f.write("\n")
    
    def analyze_schedule_json_files(self):
        """分析合并后目录中的时间表JSON文件"""
        
        # 获取所有JSON文件
        json_files = [f for f in os.listdir(self.original_dir) if f.endswith('.json')]
        
        # 用于存储分析结果
        id_files = defaultdict(lambda: {'regular': [], 'weekend': []})
        all_ids = set()
        
        # 正则表达式用于提取ID
        regular_pattern = re.compile(r'Time_schedule_(\d+)\.json')
        weekend_pattern = re.compile(r'Time_schedule_weekend_(\d+)\.json')
        
        print(f"正在分析 {len(json_files)} 个JSON文件...")
        
        # 分析每个文件
        unmatched_files = []
        for filename in json_files:
            # 检查是否是普通时间表
            regular_match = regular_pattern.match(filename)
            if regular_match:
                intersection_id = regular_match.group(1)
                id_files[intersection_id]['regular'].append(filename)
                all_ids.add(intersection_id)
                continue
            
            # 检查是否是周末时间表
            weekend_match = weekend_pattern.match(filename)
            if weekend_match:
                intersection_id = weekend_match.group(1)
                id_files[intersection_id]['weekend'].append(filename)
                all_ids.add(intersection_id)
                continue
            
            # 如果文件名不匹配任何模式
            unmatched_files.append(filename)
        
        if unmatched_files:
            print(f"警告：发现 {len(unmatched_files)} 个无法识别的文件")
        
        # 生成分析报告
        self.generate_analysis_report(id_files, all_ids, unmatched_files)
        
        return id_files, all_ids
    
    def generate_analysis_report(self, id_files, all_ids, unmatched_files):
        """生成时间表分析报告"""
        
        # 统计信息
        stats = {
            'total_ids': len(all_ids),
            'complete_ids': [],
            'regular_only': [],
            'weekend_only': [],
            'duplicate_regular': [],
            'duplicate_weekend': []
        }
        
        # 分析每个ID的文件情况
        for intersection_id in sorted(all_ids):
            files = id_files[intersection_id]
            has_regular = len(files['regular']) > 0
            has_weekend = len(files['weekend']) > 0
            
            if has_regular and has_weekend:
                stats['complete_ids'].append(intersection_id)
            elif has_regular and not has_weekend:
                stats['regular_only'].append(intersection_id)
            elif not has_regular and has_weekend:
                stats['weekend_only'].append(intersection_id)
            
            if len(files['regular']) > 1:
                stats['duplicate_regular'].append(intersection_id)
            if len(files['weekend']) > 1:
                stats['duplicate_weekend'].append(intersection_id)
        
        # 写入报告
        with open(self.analysis_report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("时间表JSON文件分析报告\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"分析目录: {self.original_dir}\n")
            f.write("=" * 80 + "\n\n")
            
            # 概览统计
            f.write("【概览统计】\n")
            f.write(f"- 总路口ID数: {stats['total_ids']}\n")
            f.write(f"- 文件完整的路口数: {len(stats['complete_ids'])} "
                    f"({len(stats['complete_ids'])/stats['total_ids']*100:.1f}%)\n")
            f.write(f"- 仅有普通时间表的路口数: {len(stats['regular_only'])}\n")
            f.write(f"- 仅有周末时间表的路口数: {len(stats['weekend_only'])}\n")
            f.write(f"- 有重复普通时间表的路口数: {len(stats['duplicate_regular'])}\n")
            f.write(f"- 有重复周末时间表的路口数: {len(stats['duplicate_weekend'])}\n\n")
            
            # 所有路口ID列表
            f.write("【所有路口ID列表】\n")
            f.write(f"共 {len(all_ids)} 个路口:\n")
            sorted_ids = sorted(all_ids)
            for i in range(0, len(sorted_ids), 10):
                ids_line = sorted_ids[i:i+10]
                f.write("  " + ", ".join(ids_line) + "\n")
            f.write("\n")
            
            # 文件完整的路口
            if stats['complete_ids']:
                f.write("【文件完整的路口】（同时有普通和周末时间表）\n")
                f.write(f"共 {len(stats['complete_ids'])} 个:\n")
                for i, intersection_id in enumerate(sorted(stats['complete_ids']), 1):
                    f.write(f"{i:3d}. 路口 {intersection_id}\n")
                f.write("\n")
            
            # 仅有普通时间表的路口
            if stats['regular_only']:
                f.write("【仅有周末时间表的路口】（缺少普通时间表）\n")
                f.write(f"共 {len(stats['regular_only'])} 个:\n")
                for i, intersection_id in enumerate(sorted(stats['regular_only']), 1):
                    f.write(f"{i:3d}. 路口 {intersection_id}\n")
                f.write("\n")
            
            # 仅有周末时间表的路口
            if stats['weekend_only']:
                f.write("【仅有周末时间表的路口】（缺少普通时间表）\n")
                f.write(f"共 {len(stats['weekend_only'])} 个:\n")
                for i, intersection_id in enumerate(sorted(stats['weekend_only']), 1):
                    f.write(f"{i:3d}. 路口 {intersection_id}\n")
                f.write("\n")
            
            # 无法识别的文件
            if unmatched_files:
                f.write("【无法识别的文件】\n")
                f.write(f"共 {len(unmatched_files)} 个:\n")
                for i, filename in enumerate(sorted(unmatched_files), 1):
                    f.write(f"{i:3d}. {filename}\n")
                f.write("\n")
            
            # 详细文件列表
            f.write("【详细文件列表】\n")
            f.write("-" * 80 + "\n")
            f.write(f"{'路口ID':<15} {'普通时间表':<30} {'周末时间表':<30}\n")
            f.write("-" * 80 + "\n")
            
            for intersection_id in sorted(all_ids):
                files = id_files[intersection_id]
                regular_files = ', '.join(files['regular']) if files['regular'] else '无'
                weekend_files = ', '.join(files['weekend']) if files['weekend'] else '无'
                
                # 如果文件名太长，截断显示
                if len(regular_files) > 28:
                    regular_files = regular_files[:25] + '...'
                if len(weekend_files) > 28:
                    weekend_files = weekend_files[:25] + '...'
                
                f.write(f"{intersection_id:<15} {regular_files:<30} {weekend_files:<30}\n")
            
            f.write("\n" + "=" * 80 + "\n")
        
        # 在控制台显示摘要
        print(f"\n分析完成！")
        print(f"  - 总路口数: {stats['total_ids']}")
        print(f"  - 文件完整: {len(stats['complete_ids'])} 个路口 ({len(stats['complete_ids'])/stats['total_ids']*100:.1f}%)")
        print(f"  - 缺少周末时间表: {len(stats['regular_only'])} 个路口")
        print(f"  - 缺少普通时间表: {len(stats['weekend_only'])} 个路口")
        if unmatched_files:
            print(f"  - 无法识别的文件: {len(unmatched_files)} 个")
    
    def generate_combined_report(self, merge_stats, id_files, all_ids):
        """生成综合报告（可选）"""
        combined_report = f"combined_report_{self.timestamp}.txt"
        
        with open(combined_report, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("时间表JSON文件合并与分析综合报告\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            f.write("【操作流程】\n")
            f.write("1. 合并 intersection_json_fixed → schedule_json\n")
            f.write("2. 分析合并后的 schedule_json 目录\n")
            f.write("3. 生成分析报告\n\n")
            
            f.write("【关键结果】\n")
            f.write(f"- 原始备份: {self.backup_dir}\n")
            f.write(f"- 合并文件数: {len(merge_stats['replaced']) + len(merge_stats['new_added'])}\n")
            f.write(f"- 最终路口总数: {len(all_ids)}\n")
            f.write(f"- 详细报告: \n")
            f.write(f"  - {self.merge_report_file}\n")
            f.write(f"  - {self.analysis_report_file}\n")
            
        print(f"\n综合报告已生成: {combined_report}")


# 主程序
if __name__ == "__main__":
    merger = ScheduleJsonMerger()
    merger.run()
