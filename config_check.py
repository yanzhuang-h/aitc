import json
from datetime import datetime
from collections import defaultdict

from Lambdas import *
def check_lambda_configurations():
    """
    检查Lambdas配置文件中各种数据结构的完整性并生成报告
    """
    report = {
        "检查时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "总体统计": {},
        "详细检查结果": {},
        "问题汇总": {},
        "建议": []
    }
    
    print("开始检查Lambdas配置文件...\n")
    
    # 1. 从config_lambda中提取所有路口
    all_intersections = set()
    config_stats = {}
    for key in ['flow', 'queue', 'stage', 'extend', 'online', 'radar', 'overflow_warning', 'boyan', 'huawei']:
        intersections = set(config_lambda[key])
        all_intersections.update(intersections)
        config_stats[key] = len(intersections)
    
    report["总体统计"]["config_lambda路口统计"] = config_stats
    report["总体统计"]["总路口数"] = len(all_intersections)
    
    print(f"config_lambda中共包含 {len(all_intersections)} 个唯一路口")
    
    # 2. 检查flow和queue数据结构
    print("\n" + "="*50)
    print("检查flow和queue数据结构...")
    
    location_intersections = set()
    intersection_directions = defaultdict(set)
    
    for loc_id, (intersection_id, direction) in location_to_intersection_lambda.items():
        location_intersections.add(intersection_id)
        intersection_directions[intersection_id].add(direction)
    
    report["总体统计"]["location_to_intersection路口数"] = len(location_intersections)
    
    # 检查方向完整性
    flow_queue_issues = {}
    complete_intersections = 0
    
    for intersection_id in config_lambda['flow'] + config_lambda['queue']:
        if intersection_id in intersection_directions:
            directions = intersection_directions[intersection_id]
            missing = set(['L', 'R', 'U', 'D']) - directions
            if missing:
                flow_queue_issues[intersection_id] = {
                    "类型": "缺少方向",
                    "缺少方向": list(missing),
                    "已有方向": list(directions)
                }
            else:
                complete_intersections += 1
        else:
            flow_queue_issues[intersection_id] = {
                "类型": "路口不存在于location_to_intersection_lambda"
            }
    
    report["详细检查结果"]["flow_queue检查"] = {
        "完整路口数": complete_intersections,
        "问题路口数": len(flow_queue_issues),
        "问题详情": flow_queue_issues
    }
    
    if flow_queue_issues:
        print(f"发现 {len(flow_queue_issues)} 个路口存在flow/queue配置问题")
        report["问题汇总"]["flow_queue问题"] = len(flow_queue_issues)
    else:
        print("✓ flow和queue数据结构方向配置完整")
    
    # 3. 检查online数据结构
    print("\n" + "="*50)
    print("检查online数据结构...")
    
    online_intersections = set(intersection_to_rid_lambda.keys())
    report["总体统计"]["intersection_to_rid路口数"] = len(online_intersections)
    
    online_issues = {}
    online_complete = 0
    
    for intersection_id in config_lambda['online']:
        if intersection_id in intersection_to_rid_lambda:
            rid_list = intersection_to_rid_lambda[intersection_id]
            directions_found = set()
            rid_details = []
            
            for rid_info in rid_list:
                rid_details.append({
                    "rid": rid_info[0] if len(rid_info) > 0 else None,
                    "direction": rid_info[1] if len(rid_info) > 1 else None
                })
                if len(rid_info) >= 2 and rid_info[1]:
                    directions_found.add(rid_info[1])
            
            missing = set(['L', 'R', 'U', 'D']) - directions_found
            if missing:
                online_issues[intersection_id] = {
                    "类型": "缺少方向",
                    "缺少方向": list(missing),
                    "已有方向": list(directions_found),
                    "rid配置": rid_details
                }
            else:
                online_complete += 1
        else:
            online_issues[intersection_id] = {
                "类型": "路口不存在于intersection_to_rid_lambda"
            }
    
    report["详细检查结果"]["online检查"] = {
        "完整路口数": online_complete,
        "问题路口数": len(online_issues),
        "问题详情": online_issues
    }
    
    if online_issues:
        print(f"发现 {len(online_issues)} 个路口存在online配置问题")
        report["问题汇总"]["online问题"] = len(online_issues)
    else:
        print("✓ online数据结构方向配置完整")
    
    # 4. 检查radar数据结构
    print("\n" + "="*50)
    print("检查radar数据结构...")
    
    # 合并所有设备映射
    all_device_mappings = {}
    device_sources = {}
    
    for device_id, (intersection_id, direction) in device_to_location.items():
        all_device_mappings[device_id] = (intersection_id, direction)
        device_sources[device_id] = "device_to_location"
    
    for device_id, (intersection_id, direction) in boyan_device_to_location.items():
        all_device_mappings[device_id] = (intersection_id, direction)
        device_sources[device_id] = "boyan_device_to_location"
    
    for device_id, (intersection_id, direction) in huawei_device_to_location.items():
        all_device_mappings[device_id] = (intersection_id, direction)
        device_sources[device_id] = "huawei_device_to_location"
    
    report["总体统计"]["设备映射总数"] = len(all_device_mappings)
    report["总体统计"]["设备来源统计"] = {
        "device_to_location": len(device_to_location),
        "boyan_device_to_location": len(boyan_device_to_location),
        "huawei_device_to_location": len(huawei_device_to_location)
    }
    
    # 按路口分组设备方向
    radar_intersection_directions = defaultdict(set)
    radar_device_details = defaultdict(list)
    
    for device_id, (intersection_id, direction) in all_device_mappings.items():
        radar_intersection_directions[intersection_id].add(direction)
        radar_device_details[intersection_id].append({
            "设备ID": device_id,
            "方向": direction,
            "来源": device_sources[device_id]
        })
    
    radar_issues = {}
    radar_complete = 0
    
    for intersection_id in config_lambda['radar']:
        if intersection_id in radar_intersection_directions:
            directions = radar_intersection_directions[intersection_id]
            missing = set(['L', 'R', 'U', 'D']) - directions
            if missing:
                radar_issues[intersection_id] = {
                    "类型": "缺少方向",
                    "缺少方向": list(missing),
                    "已有方向": list(directions),
                    "设备详情": radar_device_details[intersection_id]
                }
            else:
                radar_complete += 1
        else:
            radar_issues[intersection_id] = {
                "类型": "路口无设备映射"
            }
    
    report["详细检查结果"]["radar检查"] = {
        "完整路口数": radar_complete,
        "问题路口数": len(radar_issues),
        "问题详情": radar_issues
    }
    
    if radar_issues:
        print(f"发现 {len(radar_issues)} 个路口存在radar配置问题")
        report["问题汇总"]["radar问题"] = len(radar_issues)
    else:
        print("✓ radar数据结构方向配置完整")
    
    # 5. 检查其他重要数据结构
    print("\n" + "="*50)
    print("检查其他数据结构...")
    
    other_structures = {
        "map_lambda": len(map_lambda.keys()),
        "intersection_flow_lambda": len(intersection_flow_lambda.keys()),
        "result_action_lambda": len(result_action_lambda.keys()),
        "max_lengths_lambda": len(max_lengths_lambda.keys())
    }
    
    report["总体统计"]["其他数据结构"] = other_structures
    
    for name, count in other_structures.items():
        print(f"{name}包含 {count} 个路口")
    
    # 6. 交叉验证和一致性检查
    print("\n" + "="*50)
    print("进行交叉验证...")
    
    consistency_issues = {}
    
    # 检查是否有路口在config_lambda中但不在具体数据结构中
    missing_in_location = all_intersections - location_intersections
    missing_in_online = all_intersections - online_intersections
    
    if missing_in_location:
        consistency_issues["location缺失"] = {
            "数量": len(missing_in_location),
            "路口列表": list(missing_in_location)
        }
    
    if missing_in_online:
        consistency_issues["online缺失"] = {
            "数量": len(missing_in_online),
            "路口列表": list(missing_in_online)
        }
    
    report["详细检查结果"]["一致性检查"] = consistency_issues
    
    # 7. 生成建议
    suggestions = []
    
    if flow_queue_issues:
        suggestions.append("建议补充flow/queue配置中缺失的路口方向配置")
    
    if online_issues:
        suggestions.append("建议完善online配置中的RID映射关系")
    
    if radar_issues:
        suggestions.append("建议添加radar配置中缺失的设备映射")
    
    if missing_in_location:
        suggestions.append("建议在location_to_intersection_lambda中添加缺失的路口配置")
    
    if missing_in_online:
        suggestions.append("建议在intersection_to_rid_lambda中添加缺失的路口配置")
    
    if not suggestions:
        suggestions.append("配置文件检查通过，无需修改")
    
    report["建议"] = suggestions
    
    # 8. 输出汇总
    print("\n" + "="*50)
    print("配置检查汇总:")
    total_issues = sum([
        len(flow_queue_issues),
        len(online_issues), 
        len(radar_issues),
        len(missing_in_location),
        len(missing_in_online)
    ])
    
    report["问题汇总"]["总问题数"] = total_issues
    
    print(f"总问题数: {total_issues}")
    print(f"config_lambda总路口数: {len(all_intersections)}")
    print(f"完整配置路口数: flow/queue({complete_intersections}), online({online_complete}), radar({radar_complete})")
    
    # 保存报告到文件
    report_filename = f"lambda_config_check_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_filename, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n详细检查报告已保存到: {report_filename}")
    
    # 生成简化的文本报告
    text_report_filename = f"lambda_config_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    generate_text_report(report, text_report_filename)
    print(f"简化文本报告已保存到: {text_report_filename}")
    
    return report

def generate_text_report(report, filename):
    """生成简化的文本报告"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("Lambda配置文件检查报告\n")
        f.write("=" * 60 + "\n")
        f.write(f"检查时间: {report['检查时间']}\n\n")
        
        # 总体统计
        f.write("总体统计:\n")
        f.write("-" * 30 + "\n")
        stats = report["总体统计"]
        f.write(f"总路口数: {stats['总路口数']}\n")
        f.write(f"设备映射总数: {stats['设备映射总数']}\n\n")
        
        # 问题汇总
        f.write("问题汇总:\n")
        f.write("-" * 30 + "\n")
        issues = report["问题汇总"]
        f.write(f"总问题数: {issues.get('总问题数', 0)}\n")
        for key, value in issues.items():
            if key != '总问题数':
                f.write(f"{key}: {value}个\n")
        f.write("\n")
        
        # 建议
        f.write("改进建议:\n")
        f.write("-" * 30 + "\n")
        for i, suggestion in enumerate(report["建议"], 1):
            f.write(f"{i}. {suggestion}\n")
        
        f.write("\n" + "=" * 60 + "\n")
        f.write("详细问题请查看JSON报告文件\n")

# 运行检查
if __name__ == "__main__":
    # 需要先导入原始配置数据
    exec(open('Lambdas.py').read())
    
    report = check_lambda_configurations()
    
    # 可以进一步处理报告数据
    print(f"\n检查完成！发现总问题数: {report['问题汇总'].get('总问题数', 0)}")
