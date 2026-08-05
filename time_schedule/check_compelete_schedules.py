import os
import re
import json
from datetime import datetime
from collections import defaultdict

class ScheduleCompleteness:
    """检查时间表完整性并生成路口列表"""
    
    def __init__(self, schedule_dir="schedule_json"):
        self.schedule_dir = schedule_dir
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
    def run(self):
        """执行主流程"""
        print("=" * 80)
        print("时间表完整性检查工具")
        print("=" * 80)
        
        # 分析时间表文件
        analysis_result = self.analyze_schedule_files()
        
        if not analysis_result:
            print("分析失败")
            return
        
        # 生成完整时间表的路口列表
        self.generate_complete_list(analysis_result)
        
        # 生成详细报告
        self.generate_report(analysis_result)
        
    def analyze_schedule_files(self):
        """分析目录中的时间表文件"""
        
        if not os.path.exists(self.schedule_dir):
            print(f"错误：目录 {self.schedule_dir} 不存在")
            return None
        
        # 获取所有JSON文件
        json_files = [f for f in os.listdir(self.schedule_dir) if f.endswith('.json')]
        
        # 用于存储分析结果
        id_files = defaultdict(lambda: {'regular': [], 'weekend': []})
        
        # 正则表达式用于提取ID
        regular_pattern = re.compile(r'Time_schedule_(\d+)\.json')
        weekend_pattern = re.compile(r'Time_schedule_weekend_(\d+)\.json')
        
        print(f"\n正在分析 {len(json_files)} 个JSON文件...")
        
        # 分析每个文件
        for filename in json_files:
            # 检查是否是普通时间表
            regular_match = regular_pattern.match(filename)
            if regular_match:
                intersection_id = regular_match.group(1)
                id_files[intersection_id]['regular'].append(filename)
                continue
            
            # 检查是否是周末时间表
            weekend_match = weekend_pattern.match(filename)
            if weekend_match:
                intersection_id = weekend_match.group(1)
                id_files[intersection_id]['weekend'].append(filename)
                continue
        
        # 分类统计
        complete_ids = []  # 时间表齐全的路口
        regular_only = []  # 只有普通时间表
        weekend_only = []  # 只有周末时间表
        
        for intersection_id in sorted(id_files.keys()):
            files = id_files[intersection_id]
            has_regular = len(files['regular']) > 0
            has_weekend = len(files['weekend']) > 0
            
            if has_regular and has_weekend:
                complete_ids.append(intersection_id)
            elif has_regular and not has_weekend:
                regular_only.append(intersection_id)
            elif not has_regular and has_weekend:
                weekend_only.append(intersection_id)
        
        print(f"\n分析结果：")
        print(f"  - 时间表齐全的路口: {len(complete_ids)} 个")
        print(f"  - 只有普通时间表: {len(regular_only)} 个")
        print(f"  - 只有周末时间表: {len(weekend_only)} 个")
        print(f"  - 总路口数: {len(id_files)} 个")
        
        return {
            'id_files': id_files,
            'complete_ids': complete_ids,
            'regular_only': regular_only,
            'weekend_only': weekend_only
        }
    
    def generate_complete_list(self, analysis_result):
        """生成完整时间表的路口列表（Python格式）"""
        
        complete_ids = analysis_result['complete_ids']
        
        # 生成Python列表格式的文件
        list_file = f"complete_intersection_list_{self.timestamp}.py"
        
        with open(list_file, 'w', encoding='utf-8') as f:
            f.write("# 自动生成的时间表齐全的路口列表\n")
            f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# 总数: {len(complete_ids)} 个路口\n\n")
            
            f.write("intersection_list = [\n")
            
            # 每行放置5个ID，便于阅读
            for i in range(0, len(complete_ids), 5):
                line_ids = complete_ids[i:i+5]
                line = "    " + ", ".join([f"'{id}'" for id in line_ids])
                if i + 5 < len(complete_ids):
                    line += ","
                f.write(line + "\n")
            
            f.write("]\n")
            
            # 添加一些统计信息作为注释
            f.write(f"\n# 总计: {len(complete_ids)} 个路口\n")
        
        print(f"\n已生成Python列表文件: {list_file}")
        
        # 同时生成一个简单的文本列表
        txt_file = f"complete_intersection_list_{self.timestamp}.txt"
        with open(txt_file, 'w', encoding='utf-8') as f:
            for id in complete_ids:
                f.write(f"{id}\n")
        
        print(f"已生成文本列表文件: {txt_file}")
        
        # 在控制台显示列表（格式化输出）
        print("\n" + "=" * 80)
        print("时间表齐全的路口列表（Python格式）：")
        print("=" * 80)
        print("\nintersection_list = [")
        for i in range(0, len(complete_ids), 5):
            line_ids = complete_ids[i:i+5]
            line = "    " + ", ".join([f"'{id}'" for id in line_ids])
            if i + 5 < len(complete_ids):
                line += ","
            print(line)
        print("]")
        print(f"\n# 总计: {len(complete_ids)} 个路口")
    
    def generate_report(self, analysis_result):
        """生成详细报告"""
        
        report_file = f"schedule_completeness_report_{self.timestamp}.txt"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("时间表完整性检查报告\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"检查目录: {self.schedule_dir}\n")
            f.write("=" * 80 + "\n\n")
            
            # 统计摘要
            f.write("【统计摘要】\n")
            f.write(f"- 时间表齐全的路口: {len(analysis_result['complete_ids'])} 个\n")
            f.write(f"- 只有普通时间表: {len(analysis_result['regular_only'])} 个\n")
            f.write(f"- 只有周末时间表: {len(analysis_result['weekend_only'])} 个\n")
            f.write(f"- 总路口数: {len(analysis_result['id_files'])} 个\n\n")
            
            # 时间表齐全的路口
            f.write("【时间表齐全的路口】\n")
            f.write(f"共 {len(analysis_result['complete_ids'])} 个:\n")
            for i, id in enumerate(analysis_result['complete_ids'], 1):
                f.write(f"{i:3d}. {id}\n")
            f.write("\n")
            
            # 缺少周末时间表的路口
            if analysis_result['regular_only']:
                f.write("【只有普通时间表（缺少周末时间表）】\n")
                f.write(f"共 {len(analysis_result['regular_only'])} 个:\n")
                for i, id in enumerate(analysis_result['regular_only'], 1):
                    f.write(f"{i:3d}. {id}\n")
                f.write("\n")
            
            # 缺少普通时间表的路口
            if analysis_result['weekend_only']:
                f.write("【只有周末时间表（缺少普通时间表）】\n")
                f.write(f"共 {len(analysis_result['weekend_only'])} 个:\n")
                for i, id in enumerate(analysis_result['weekend_only'], 1):
                    f.write(f"{i:3d}. {id}\n")
                f.write("\n")
            
            # 详细文件列表
            f.write("【详细文件信息】\n")
            f.write("-" * 80 + "\n")
            for intersection_id in sorted(analysis_result['id_files'].keys()):
                files = analysis_result['id_files'][intersection_id]
                f.write(f"\n路口 {intersection_id}:\n")
                if files['regular']:
                    f.write(f"  普通时间表: {', '.join(files['regular'])}\n")
                else:
                    f.write("  普通时间表: 无\n")
                if files['weekend']:
                    f.write(f"  周末时间表: {', '.join(files['weekend'])}\n")
                else:
                    f.write("  周末时间表: 无\n")
            
            f.write("\n" + "=" * 80 + "\n")
            f.write("报告结束\n")
        
        print(f"\n已生成详细报告: {report_file}")


# 主程序
if __name__ == "__main__":
    checker = ScheduleCompleteness()
    checker.run()
