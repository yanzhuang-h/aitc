# 创建新的intersection_to_rid_lambda字典，从原始数据开始
intersection_to_rid_lambda_new = {}
from lib.Global_intersection_coordinate import road_map, online_map_info
intersection_to_rid_lambda={
  "1300101": [
    "13G2J0C684013G2E0C69R00",
    "13G2E0C69R013G2J0C68400",
    "13G2J0C684013G2K0C67F00"
  ],
  "1300069": [
    "13G2J0C684013G2E0C69R00",
    "13G2E0C69R013G2J0C68400",
    "13G2E0C69R013G3R0C69Q00",
    "13G3L0C69T013G2E0C69R00"
  ],
  "1300068": [
    "13G2E0C69R013G3R0C69Q00",
    "13G3L0C69T013G2E0C69R00"
  ],
  "1300097": [
    "13G2N0C67E013G2J0C68400",
    "13G2J0C684013G2K0C67F00",
    "13G2O0C66O013G2N0C67E00",
    "13G2K0C67C013G2O0C66O00"
  ],
  "1300044": [
    "13G2O0C66O013G2N0C67E00",
    "13G2K0C67C013G2O0C66O00",
    "13G480C66R013G2O0C66O00",
    "13G2O0C66O013G480C66R00"
  ],
  "1300046": [
    "13G480C66R013G2O0C66O00",
    "13G2O0C66O013G480C66R00",
    "13G530C66S013G480C66R00",
    "13G480C66R013G530C66S00"
  ],
  "1300042": [
    "13G530C66S013G480C66R00",
    "13G480C66R013G530C66S00",
    "13G650C66U013G530C66S00",
    "13G530C66S013G650C66U00"
  ],
  "1300047": [
    "13G650C66U013G530C66S00",
    "13G530C66S013G650C66U00",
    "13G6H0C65O013G650C66U00",
    "13G650C66U013G610C67800"
  ],
  "2703062": [
    "13G4V0C68F013G580C68700",
    "13G580C687013G4V0C68F00"
  ],
  "1300106": [
    "13G4V0C68F013G580C68700",
    "13G580C687013G4V0C68F00",
    "13G650C66U013G610C67800"
  ],
  "1300103": [
    "13G6H0C65O013G650C66U00",
    "13G6T0C64E013G6P0C64U00",
    "13G6O0C651013G6K0C65F00",
    "13G6K0C65F013G6H0C65O00"
  ],
  "1300092": [
    "13G6T0C64E013G6P0C64U00",
    "13G6O0C651013G6K0C65F00",
    "13G6K0C65F013G6H0C65O00"
  ],
  "1300782": [
    "13G4I0C70A013G4L0C70500",
    "13G590C6VG013G4L0C70500",
    "13G450C6VT013G4L0C70500"
  ],
  "1300451": [
    "13G1U0C6IC013G210C6HO00",
    "13G230C6HC013G210C6HO00",
    "13G390C6HP013G210C6HO00",
    "13G090C6HL013G210C6HO00"
  ],
  "1300454": [
    "13G3C0C6JK013G390C6HP00",
    "13G3E0C6H2013G390C6HP00",
    "13G3L0C6HQ013G390C6HP00",
    "13G2F0C6HO013G390C6HP00"
  ],
  "1300194": [
    "13FK10C5QR013FK10C5OP00",
    "13FK10C5OP013FK10C5QR00",
    "13FK10C5OP013FII0C5OP00",
    "13FM60C5OP013FK10C5OP00"
  ],
  "1100308": [
    "13GB00C654013G9U0C65200",
    "13GBT0C655013GB00C65400",
    "13G9U0C652013GB00C65400",
    "13GB00C654013GBT0C65500",
    "13GB60C64Q013GB00C65400"
  ],
  "1300099": [
    "13GAQ0C693013GAR0C68B00",
    "13GAR0C68B013GAT0C66S00",
    "13GAR0C68B013GAQ0C69300",
    "13GAT0C66S013GAR0C68B00"
  ],
  "1300105": [
    "13FT20C64S013FT40C65C00",
    "13FT50C63O013FT20C64S00",
    "13FT20C64S013FRV0C64P00"
  ],
  "1300110": [
    "13G0P0C5L8013G0Q0C5KT00",
    "13G0Q0C5KT013G0R0C5JR00",
    "13G0Q0C5KT013G0Q0C5L800",
    "13G0R0C5KG013G0Q0C5KT00",
    "13G0Q0C5KT013G090C5KS00",
    "13G1P0C5KT013G0Q0C5KT00"
  ],
  "1300117": [
    "13FSV0C5LS013FSV0C5KT00",
    "13FSV0C5KT013FT00C5JS00",
    "13FUC0C5KS013FSV0C5KT00"
  ],
  "1300164": [
    "13FP00C65F013FOU0C66900",
    "13FP10C653013FP00C65F00",
    "13FP00C65F013FNH0C65800",
    "13FQM0C65I013FP00C65F00"
  ],
  "1300303": [
    "13FIT0C65R013FIT0C66K00",
    "13FIU0C653013FIT0C65R00",
    "13FIT0C65R013FHR0C65N00",
    "13FK40C65Q013FIT0C65R00",
    "13FIT0C65R013FK40C65Q00"
  ],
  "1300310": [
    "13FOD0C5N2013FOD0C5L200",
    "13FOD0C5L2013FOD0C5JS00",
    "13FM70C5L2013FOD0C5L200"
  ],
  "2704102": [
    "13FK40C669013FK40C65Q00",
    "13FK40C65Q013FK40C65G00",
    "13FK40C65Q013FIT0C65R00",
    "13FIT0C65R013FK40C65Q00",
    "13FM30C65Q013FK40C65Q00"
  ],
  "1300095": [
    "13G0Q0C5KT013G090C5KS00",
    "13G090C5KS013G0A0C5KL00"
  ],
  "1300096": [
    "13G0A0C5KL013G040C5KL00",
    "13G040C5KL013FVP0C5KL00"
  ],
  "2704064": [
    "13FT50C63O013FT20C64S00",
    "13FT70C633013FT50C63O00",
    "13FT50C63O013FS90C63M00",
    "13FVB0C63V013FT50C63O00"
  ],
  "1300243": [
    "13FIT0C60R113FIC0C60P00",
    "13FJB0C60S013FIT0C60R10",
    "13FJ00C60B013FIT0C60R10"
  ],
  "1300244": [
    "13FIC0C61K013FIC0C60P00"
  ],
  "1300245": [
    "13FJB0C60S013FJ30C61O00",
    "13FK30C60U013FJB0C60S00"
  ],
  "1300246": [
    "13FK30C60A013FK40C5VK00",
    "13FK40C5VK013FK30C60A00",
    "13FK40C5VK013FJ50C5VJ00",
    "13FKK0C5VK013FK40C5VK00",
    "13FJ50C5VJ013FK40C5VK00"
  ],
  "1300248": [
    "13FL00C60A013FKU0C60A00",
    "13FMF0C60A013FL00C60A00",
    "13FL00C60A013FL00C5VK00"
  ],
  "1300370": [
    "13FJ00C60B013FIT0C60R10",
    "13FJ50C5VJ013FJ00C60B00",
    "13FJ00C60B013FIT0C5V800",
    "13FK30C60A013FJ00C60B00"
  ],
  "2710422": [],
  "1300113": [],
  "2705050": [],
  "1300271": [
    "13G8B0C6HB013G8E0C6FT00",
    "13G8E0C6FT013G8D0C6FA00",
    "13G8E0C6FT013G8D0C6HH00",
    "13G8I0C6FB013G8E0C6FT00"
  ],
  "27787827": [
    "13FDJ0C6VR013FCT0C70E00",
    "13FEI0C6UV013FDJ0C6VR00",
    "13FC20C712013FDJ0C6VR00",
    "13FDJ0C6VR013FE10C6VC00"
  ],
  "2712127": [],
  "1300046": [],
  "1300103": [],
  "1300092": [],
  "1300042": [],
  "1300782": [],
  "1300451": [],
  "1300454": [],
  "1300194": [],
  "1100308": [],
  "1300099": [],
  "1300105": [],
  "1300110": [],
  "1300117": [],
  "1300164": [],
  "1300303": [],
  "1300310": [],
  "2704102": [],
  "1300095": [],
  "1300096": [],
  "2704064": [],
  "1300243": [],
  "1300244": [],
  "1300245": [],
  "1300246": [],
  "1300248": [],
  "1300370": []}


def compare_rids_detailed(intersection_to_rid_lambda_new, online_data_map_lambda):
    # 从intersection_to_rid_lambda_new中提取所有rid及其相关信息
    new_rids_info = {}  # rid -> [(intersection_id, direction), ...]
    for intersection_id, rid_list in intersection_to_rid_lambda_new.items():
        for rid_direction in rid_list:
            rid = rid_direction[0]
            direction = rid_direction[1]
            
            if rid not in new_rids_info:
                new_rids_info[rid] = []
            new_rids_info[rid].append((intersection_id, direction))
    
    # 从online_data_map_lambda中提取所有rid
    existing_rids = set(online_data_map_lambda.keys())
    
    # 找出差异
    missing_in_online_data = set(new_rids_info.keys()) - existing_rids
    
    # 统计信息
    stats = {
        "total_rids_in_new_dict": len(new_rids_info),
        "total_rids_in_online_data": len(existing_rids),
        "missing_rids_count": len(missing_in_online_data),
        "missing_rids_details": {},
        "online_data_contains_all_new_rids": len(missing_in_online_data) == 0
    }
    
    # 添加缺失rid的详细信息
    for rid in missing_in_online_data:
        stats["missing_rids_details"][rid] = new_rids_info[rid]
    
    return stats



# 首先处理原始intersection_to_rid_lambda数据
for intersection_id, rid_list in intersection_to_rid_lambda.items():
    if intersection_id not in intersection_to_rid_lambda_new:
        intersection_to_rid_lambda_new[intersection_id] = []
    
    # 将原有的rid转换为(rid, direction)格式，方向设为None
    for rid in rid_list:
        # 检查rid是否在road_map中，如果是则获取方向
        direction = None
        if rid in road_map:
            # 查找该rid对应的路口，找到匹配的方向
            info = road_map[rid]
            if intersection_id == info[0] or (len(info) > 2 and intersection_id == info[2]):
                direction = info[1] if intersection_id == info[0] else info[3]
        
        # 检查rid是否在online_map_info中，如果是则获取方向
        if rid in online_map_info and direction is None:
            cross_directions = online_map_info[rid]
            if intersection_id in cross_directions:
                direction = cross_directions[intersection_id]
        
        intersection_to_rid_lambda_new[intersection_id].append((rid, direction))

# 处理road_map中的rid
for rid, info in road_map.items():
    if len(info) >= 2:  # 确保有足够的信息
        # 第一个路口ID和方向
        intersection_id1 = info[0]
        direction1 = info[1]
        
        # 添加到第一个路口
        if intersection_id1 not in intersection_to_rid_lambda_new:
            intersection_to_rid_lambda_new[intersection_id1] = []
        
        # 检查是否已存在，避免重复
        exists = False
        for existing_rid, _ in intersection_to_rid_lambda_new[intersection_id1]:
            if existing_rid == rid:
                exists = True
                break
        
        if not exists:
            intersection_to_rid_lambda_new[intersection_id1].append((rid, direction1))
        
        # 如果有第二个路口ID，也添加
        if len(info) >= 4 and info[2] != "0":
            intersection_id2 = info[2]
            direction2 = info[3]
            
            if intersection_id2 not in intersection_to_rid_lambda_new:
                intersection_to_rid_lambda_new[intersection_id2] = []
            
            # 检查是否已存在，避免重复
            exists = False
            for existing_rid, _ in intersection_to_rid_lambda_new[intersection_id2]:
                if existing_rid == rid:
                    exists = True
                    break
            
            if not exists:
                intersection_to_rid_lambda_new[intersection_id2].append((rid, direction2))

# 处理online_map_info中的rid
for rid, cross_directions in online_map_info.items():
    for intersection_id, direction in cross_directions.items():
        # 添加到对应的路口
        if intersection_id not in intersection_to_rid_lambda_new:
            intersection_to_rid_lambda_new[intersection_id] = []
        
        # 检查是否已存在，避免重复
        exists = False
        for existing_rid, _ in intersection_to_rid_lambda_new[intersection_id]:
            if existing_rid == rid:
                exists = True
                break
        
        if not exists:
            intersection_to_rid_lambda_new[intersection_id].append((rid, direction))

# 保存结果到py文件
with open("intersection_to_rid_lambda.py", "w") as f:
    f.write("intersection_to_rid_lambda = {\n")
    for intersection_id, rid_list in intersection_to_rid_lambda_new.items():
        f.write(f'  "{intersection_id}": [\n')
        for rid, direction in rid_list:
            if direction is not None:
                f.write(f'    ("{rid}", "{direction}"),\n')
            else:
                f.write(f'    ("{rid}", None),\n')
        f.write("  ],\n")
    f.write("}\n")

from Lambdas import online_data_map_lambda 
# 创建新的online_data_map_lambda，从原有的开始
new_online_data_map_lambda = online_data_map_lambda.copy()

# 从intersection_to_rid_lambda_new中提取所有rid并添加到新字典
for intersection_id, rid_list in intersection_to_rid_lambda_new.items():
    for rid_direction in rid_list:
        rid = rid_direction[0]  # 提取rid部分
        
        # 如果rid不在原有的online_data_map_lambda中，则添加
        if rid not in new_online_data_map_lambda:
            new_online_data_map_lambda[rid] = {}
            
# 打印统计信息
original_count = len(online_data_map_lambda)
new_count = len(new_online_data_map_lambda)
added_count = new_count - original_count

print(f"原有的online_data_map_lambda包含 {original_count} 个rid")
print(f"新的online_data_map_lambda包含 {new_count} 个rid")
print(f"添加了 {added_count} 个新的rid")

# 将新的online_data_map_lambda保存到文件
with open("new_online_data_map_lambda.py", "w", encoding="utf-8") as f:
    f.write("online_data_map_lambda = {\n")
    
    # 按字母顺序排序rid
    sorted_rids = sorted(new_online_data_map_lambda.keys())
    
    for i, rid in enumerate(sorted_rids):
        f.write(f'    "{rid}": {{}}' + (",\n" if i < len(sorted_rids) - 1 else "\n"))
    
    f.write("}.copy()")
    
print("新的online_data_map_lambda已保存到文件: new_online_data_map_lambda.py")