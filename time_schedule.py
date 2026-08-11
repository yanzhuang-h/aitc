import json
import sys
import os
import logging
from chinese_calendar import is_workday
from datetime import date, datetime, timedelta
import importlib
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, jsonify
import threading
from urllib.parse import urlparse
from time_schedule.get_sch_for_cross import get_sch_for_cross,update_FIne_turn_for_cross
from time_schedule.updata_road import updata_road_func
# 添加项目根目录到系统路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入路径配置
from path_config import PROJECT_ROOT, get_path, LOG_DIR
from lib.road_state import get_road_state_config, validate_and_save_road_state

# 配置路径
online_file_dir = get_path('online')
flow_file_dir = get_path('flow')
stage_file_dir = get_path('stage')
radar_file_dir = get_path('radar')
inner_schedule_log_dir = get_path('inner_schedule')
outer_schedule_log_dir = get_path('outer_schedule')
fine_turn_log_dir = get_path('fine_turn')
schedule_json_dir = get_path('schedule_json')
extend_file_dir = get_path('extend')

schedule_dir=get_path('schedule')
# 更新信息文件路径
CLIENT_UPDATE_FILE = os.path.join(schedule_dir, 'client_updates.json')

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'time_schedule.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TimeSchedule')

app = Flask(__name__)

CORS_RESPONSE_HEADERS = (
    "Access-Control-Allow-Origin",
    "Access-Control-Allow-Credentials",
    "Access-Control-Allow-Methods",
    "Access-Control-Allow-Headers",
    "Access-Control-Expose-Headers",
    "Access-Control-Max-Age",
)


def is_cross_origin_request(origin, host):
    if not origin:
        return False

    try:
        parsed_origin = urlparse(origin)
    except ValueError:
        return True

    origin_host = (parsed_origin.netloc or "").lower()
    request_host = (host or "").lower()
    return not origin_host or origin_host != request_host


@app.before_request
def block_cross_origin_requests():
    origin = request.headers.get("Origin")
    if is_cross_origin_request(origin, request.host):
        logger.warning(
            "Blocked cross-origin request: origin=%s host=%s path=%s",
            origin,
            request.host,
            request.path,
        )
        return jsonify({"error": "Cross-origin requests are not allowed"}), 403


@app.after_request
def remove_cors_headers(response):
    for header in CORS_RESPONSE_HEADERS:
        response.headers.pop(header, None)
    return response

intersection_list = [
    '1100257', '1100308', '1300035', '1300037', '1300038',
    '1300039', '1300042', '1300044', '1300046', '1300047',
    '1300052', '1300053', '1300054', '1300059', '1300060',
    '1300061', '1300062', '1300063', '1300067', '1300068',
    '1300069', '1300086', '1300087', '1300090', '1300091',
    '1300092', '1300095', '1300096', '1300097', '1300099',
    '1300100', '1300101', '1300102', '1300103', '1300104',
    '1300105', '1300106', '1300107', '1300109', '1300110',
    '1300112', '1300113', '1300116', '1300117', '1300121',
    '1300142', '1300143', '1300162', '1300164', '1300166',
    '1300167', '1300168', '1300171', '1300172', '1300173',
    '1300177', '1300183', '1300184', '1300193', '1300194',
    '1300195', '1300196', '1300199', '1300200', '1300201',
    '1300203', '1300204', '1300205', '1300207', '1300208',
    '1300224', '1300225', '1300226', '1300227', '1300228',
    '1300231', '1300233', '1300235', '1300241', '1300242',
    '1300243', '1300244', '1300245', '1300246', '1300247',
    '1300248', '1300250', '1300251', '1300252', '1300253',
    '1300255', '1300264', '1300265', '1300276', '1300295',
    '1300296', '1300297', '1300302', '1300303', '1300308',
    '1300310', '1300311', '1300312', '1300313', '1300314',
    '1300318', '1300320', '1300326', '1300357', '1300358',
    '1300360', '1300361', '1300366', '1300369', '1300370',
    '1300371', '1300373', '1300386', '1300387', '1300391',
    '1300397', '1300407', '1300409', '1300451', '1300454',
    '1301046', '1301048', '1400174', '2702783', '2702784',
    '2702894', '2703062', '2703916', '2704064', '2704102',
    '2705050', '2708375', '2710422', '2712127',
'1300225',
'1300226',
'1300227',
'1300231',
'1300360',
'1300233',
'1300235',
'1300107',
'1300121',
'1300255',
'1300386',
'1300387',
'1300391',
'1300397',
'1300142',
'1300143',
'2702894',
'1300276',
'1300407',
'1301048',
'1300409',
'2702783',
'2702784',
'1300162',
'1300035',
'1300166',
'1300039',
'1300296',
'1300295',
'1300297',
'1300168',
'1300167',
'1300173',
'1300302',
'1300177',
'1300308',
'1300053',
'1300184',
'1300060',
'1300061',
'1300062',
'1300320',
'1300193',
'1300067',
'1300196',
'1300195',
'1300326',
'1300199',
'1300201',
'1300203',
'1300204',
'1300205',
'1300207',
'1300208',
'1300087'


]
                     


# 全局变量
inner_time_schedule = {}  
outer_time_schedule = {}  
client_updates = {}  # 只记录客户端更新时间 {intersection_id: "2023-08-01"}
update_lock = threading.Lock()

def load_client_updates():
    """加载客户端更新时间记录"""
    global client_updates
    try:
        if os.path.exists(CLIENT_UPDATE_FILE):
            with open(CLIENT_UPDATE_FILE, 'r') as f:
                client_updates = json.load(f)
            logger.info(f"已加载客户端更新记录: {len(client_updates)}条")
        else:
            logger.info("客户端更新记录文件不存在，将创建新文件")
            client_updates = {}
        return True
    except Exception as e:
        logger.error(f"加载客户端更新记录失败: {e}")
        client_updates = {}
        return False

def save_client_updates():
    """保存客户端更新时间记录"""
    try:
        with open(CLIENT_UPDATE_FILE, 'w') as f:
            json.dump(client_updates, f, indent=4)
        logger.debug("客户端更新记录已保存")
        return True
    except Exception as e:
        logger.error(f"保存客户端更新记录失败: {e}")
        return False

def get_inner_schedule(intersection_id):
    """获取内部时间表"""
    if is_workday(date.today()):
        schedule_name_pre = 'Time_schedule_'
    else:
        schedule_name_pre = 'Time_schedule_weekend_'
    
    schedule_json_file = os.path.join(schedule_json_dir, f'{schedule_name_pre}{intersection_id}.json')    
    try:
        with open(schedule_json_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"时间表文件不存在: {schedule_json_file}")
        return None
    except json.JSONDecodeError:
        logger.error(f"JSON解析错误: {schedule_json_file}")
        return None

def get_outer_schedule():
    """获取外部时间表，如果不存在则创建并用内表初始化"""
    global outer_time_schedule
    
    if is_workday(date.today()):
        schedule_file = os.path.join(schedule_json_dir, 'Outer_time_schedule.json')
    else:
        schedule_file = os.path.join(schedule_json_dir, 'Outer_time_schedule_weekend.json')
    
    logger.debug(f"加载外部时间表: {schedule_file}")
    
    try:
        with open(schedule_file, 'r') as f:
            outer_time_schedule = json.load(f)
            return True
    except FileNotFoundError:        
        # 外部时间表文件不存在，创建并用内表初始化
        logger.info(f"外部时间表文件不存在，创建新文件: {schedule_file}")
        if inner_time_schedule:
            try:
                with open(schedule_file, 'w') as f:
                    json.dump(inner_time_schedule, f, indent=4)
                outer_time_schedule = inner_time_schedule.copy()
                logger.info(f"已用内表初始化外部时间表: {schedule_file}")
                return True
            except Exception as e:
                logger.error(f"创建外部时间表文件失败: {e}")
                return False
        else:
            logger.error(f"无法初始化外部时间表，内表不存在")
            return False

def init_schedule():
    """初始化时间表"""
    global inner_time_schedule, outer_time_schedule
    
    # 加载客户端更新记录
    load_client_updates()
    
    # 加载内部时间表
    for intersection_id in intersection_list:
        schedule = get_inner_schedule(intersection_id)
        if schedule:
            inner_time_schedule[intersection_id] = schedule
    
    # 加载外部时间表
    if not get_outer_schedule():
        logger.error("外部时间表加载失败，使用内表作为后备")
        outer_time_schedule = inner_time_schedule.copy()
    
    logger.info('时间表初始化完成')
    return True


def update_inner_schedule():
    target_date=date.today()-timedelta(days=1)
    logger.info(f"{target_date} :开始每日时间表更新")
    schedule_name_pre = 'Time_schedule_weekend_' if not is_workday(target_date) else 'Time_schedule_'
    fine_turn_file_name = 'FIne_turn_weekend.json' if not is_workday(target_date) else 'FIne_turn.json'
    fine_turn_file_path = os.path.join(schedule_json_dir, fine_turn_file_name)
    
    with open(fine_turn_file_path, 'r', encoding='utf-8') as f:
        complete_fine_turn_data = json.load(f)

    
    for intersection_id in intersection_list:            
        date_str = target_date.strftime('%Y-%m-%d')
        flow_file = os.path.join(flow_file_dir, f"{date_str}_flow.txt")
        stage_file = os.path.join(stage_file_dir, f"{date_str}_stage.txt")
        online_file = os.path.join(online_file_dir, f"{date_str}_online.txt")
        radar_file = os.path.join(radar_file_dir, f"{date_str}_radar.txt")
        extend_file=os.path.join(extend_file_dir,f"{date_str}_extend.txt")
        target_turn = complete_fine_turn_data.get(intersection_id, {})
        
        if not target_turn:
            logger.warning(f"路口 {intersection_id} 在FIne_turn文件中没有数据，跳过更新")
            continue
        # if not os.path.exists(flow_file):
        #     logger.warning(f"流量文件不存在: {flow_file}")
        #     continue
        # if not os.path.exists(stage_file):
        #     logger.warning(f"信号灯文件不存在: {stage_file}")
        #     continue
        # if not os.path.exists(online_file):
        #     logger.warning(f"在线数据文件不存在: {online_file}")
        #     continue
        #
        
        try:
            current_schedule = inner_time_schedule.get(intersection_id, {})
            # new_schedule = get_sch_for_cross(intersection_id, flow_file, stage_file, online_file, radar_file,current_schedule)
            # new_FIne_turn_schedule = update_FIne_turn_for_cross(intersection_id, flow_file, stage_file, online_file, radar_file, target_turn)
            new_schedule = get_sch_for_cross(intersection_id, flow_file, stage_file, online_file, radar_file,current_schedule,extend_file)
            new_FIne_turn_schedule = update_FIne_turn_for_cross(intersection_id, flow_file, stage_file, online_file, radar_file, target_turn,extend_file)

            if new_schedule:
                inner_time_schedule[intersection_id] = new_schedule
                logger.info(f'更新路口时间表: {intersection_id}')
                
                # 保存新时间表
                schedule_file = os.path.join(schedule_json_dir, f'{schedule_name_pre}{intersection_id}.json')
                with open(schedule_file, 'w') as f:
                    json.dump(new_schedule, f, indent=4)
                    logger.info(f'保存时间表到: {schedule_file}')
            
            if new_FIne_turn_schedule:
                complete_fine_turn_data[intersection_id] = new_FIne_turn_schedule
                logger.info(f'更新路口微调数据: {intersection_id}')
                
        except Exception as e:
            logger.error(f'更新路口 {intersection_id} 失败: {e}')
    
    target_date_inner_schedule_path = os.path.join(inner_schedule_log_dir, f'Inner_time_schedule_{target_date.strftime("%Y%m%d")}.json')
    target_date_fine_turn_path = os.path.join(fine_turn_log_dir, f'FIne_turn_{target_date.strftime("%Y%m%d")}.json')
    
    # 保存内部时间表到日志目录
    try:
        with open(target_date_inner_schedule_path, 'w') as f:
            json.dump(inner_time_schedule, f, indent=4)
        logger.info(f'内部时间表已保存到: {target_date_inner_schedule_path}')
    except Exception as e:
        logger.error(f'保存内部时间表失败: {e}')
    

    try:
        # 保存更新后的 fine_turn 数据到原文件和日志文件
        with open(fine_turn_file_path, 'w', encoding='utf-8') as f:
            json.dump(complete_fine_turn_data, f, indent=4, ensure_ascii=False)
        logger.info(f'已更新原 fine_turn 文件: {fine_turn_file_path}')
        with open(target_date_fine_turn_path, 'w', encoding='utf-8') as f:
            json.dump(complete_fine_turn_data, f, indent=4, ensure_ascii=False)
        logger.info(f'完整 fine_turn 数据已保存到: {target_date_fine_turn_path}')
        logger.info(f'保存了 {len(complete_fine_turn_data)} 个路口的 fine_turn 数据')
    except Exception as e:
        logger.error(f'保存 fine_turn 文件和日志失败: {e}')
    
    logger.info('内部时间表更新完成') 
    init_schedule()  # 重新初始化时间表以确保最新数据
    
    # 每月1日执行外部时间表覆盖更新检查
    if datetime.now().day == 1:
        logger.info("每月1日 - 开始检查并更新超过30天未更新的外部时间表")
        update_stale_outer_schedules()
    return True


def update_stale_outer_schedules():
    """更新超过30天未更新的外部时间表"""
    global outer_time_schedule
    
    # 计算30天前的日期
    thirty_days_ago = datetime.now() - timedelta(days=30)
    updated_intersections = []
    
    with update_lock:
        # 遍历所有路口
        for intersection_id in intersection_list:
            # 获取最后客户端更新时间
            last_update_str = client_updates.get(intersection_id)
            
            # 判断是否需要更新
            if not last_update_str:
                # 没有客户端更新记录，需要更新
                should_update = True
            else:
                try:
                    last_update = datetime.strptime(last_update_str, "%Y-%m-%d")
                    should_update = (datetime.now() - last_update) > timedelta(days=30)
                except:
                    # 日期格式错误，视为需要更新
                    should_update = True
            
            # 如果需要更新且内表中有该路口的数据
            if should_update and intersection_id in inner_time_schedule:
                # 使用内表覆盖外表
                outer_time_schedule[intersection_id] = inner_time_schedule[intersection_id].copy()
                updated_intersections.append(intersection_id)
                logger.info(f"路口 {intersection_id} 已使用内表覆盖更新")
        
        # 如果有更新，保存外部时间表
        if updated_intersections:
            # 确定外部时间表文件名
            if is_workday(date.today()):
                schedule_file = os.path.join(schedule_json_dir, 'Outer_time_schedule.json')
            else:
                schedule_file = os.path.join(schedule_json_dir, 'Outer_time_schedule_weekend.json')
            
            try:
                with open(schedule_file, 'w') as f:
                    json.dump(outer_time_schedule, f, indent=4)
                logger.info(f"已保存更新后的外部时间表: {schedule_file}")
            except Exception as e:
                logger.error(f"保存外部时间表失败: {e}")
        
        logger.info(f"每月1日更新完成: 共更新了 {len(updated_intersections)} 个路口")
        target_date_outer_schedule_path = os.path.join(outer_schedule_log_dir, f'Outer_time_schedule_{date.today().strftime("%Y%m%d")}.json')
        # 保存外部时间表到日志目录
        try:
            with open(target_date_outer_schedule_path, 'w') as f:
                json.dump(outer_time_schedule, f, indent=4)
            logger.info(f'外部时间表已保存到: {target_date_outer_schedule_path}')
        except Exception as e:
            logger.error(f'保存外部时间表失败: {e}')

import json
import os

def modify_intersection_turn(intersection_id, new_turn):
    if is_workday(date.today()):
        file_path = os.path.join(schedule_json_dir, 'FIne_turn.json')
    else:
        file_path = os.path.join(schedule_json_dir, 'FIne_turn_weekend.json')
    
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.info(f"错误: 文件 {file_path} 不存在")
            return False
        
        # 读取JSON文件
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if str(intersection_id) not in data:
            logger.info(f"警告:路口ID {intersection_id} 在文件中不存在，将创建新条目")
        
        data[str(intersection_id)] = new_turn
 
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        print(f"成功更新 {intersection_id} 的FIne_turn数据")
        return True
        
    except FileNotFoundError:
        logger.error(f"错误: 无法找到文件 {file_path}")
        return False
    except json.JSONDecodeError:
        logger.error(f"错误: JSON文件格式无效")
        return False
    except Exception as e:
        logger.error(f"错误: {str(e)}")
        return False

def schedule_daily_update():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_inner_schedule, 'cron', hour=0, minute=0)
    scheduler.add_job(updata_road_func, 'cron', hour=14, minute=00)
    scheduler.start()
    logger.info("定时任务已启动 - 每日午夜更新后重新初始化时间表")

# REST API 端点
@app.route('/road_state', methods=['GET'])
def get_road_state():
    try:
        return jsonify(get_road_state_config())
    except Exception as e:
        logger.error(f"获取 road_state 配置失败: {str(e)}")
        return jsonify({
            "status": "error",
            "saved": False,
            "reason": str(e)
        }), 500


@app.route('/road_state/validate', methods=['POST'])
def validate_road_state():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "saved": False,
            "reason": "Invalid JSON object"
        }), 400

    result = validate_and_save_road_state(payload, dry_run=True)
    return jsonify(result), 200 if result.get("status") != "error" else 400


@app.route('/road_state/update', methods=['POST'])
def update_road_state():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "saved": False,
            "reason": "Invalid JSON object"
        }), 400

    result = validate_and_save_road_state(payload, dry_run=False)
    return jsonify(result), 200 if result.get("status") != "error" else 400


@app.route('/schedule', methods=['GET'])
def get_timetable():
    """HTTP GET 返回外部时间表"""
    return jsonify(outer_time_schedule)

@app.route('/schedule/<intersection_id>', methods=['GET'])
def get_intersection_timetable(intersection_id):
    """HTTP GET 返回特定路口的外部时间表"""
    if intersection_id in outer_time_schedule:
        return jsonify({intersection_id: outer_time_schedule[intersection_id]})
    else:
        return jsonify({"error": "Intersection not found"}), 404

@app.route('/update', methods=['POST'])
def update_outer_schedule():
    """HTTP POST 接收客户端传来的新时间表并应用到外部时间表"""
    global outer_time_schedule, client_updates
    
    try:
        # 获取客户端发送的JSON数据
        update_data = request.json
        
        # 验证数据格式
        if not isinstance(update_data, dict):
            return jsonify({"error": "Invalid data format"}), 400
        
        # 初始化更新结果
        updated_intersections = []
        errors = []
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        with update_lock:
            # 遍历更新数据中的每个路口
            for intersection_id, new_schedule in update_data.items():
                # 验证路口ID是否有效
                if intersection_id not in intersection_list:
                    errors.append(f"Invalid intersection ID: {intersection_id}")
                    continue
            
                # 验证时间表格式
                if not isinstance(new_schedule, dict):
                    errors.append(f"Invalid schedule format for intersection {intersection_id}")
                    continue
                    
                # 更新外部时间表
                if intersection_id not in outer_time_schedule:
                    outer_time_schedule[intersection_id] = {}
                    
                # 应用更新（合并新旧时间表）
                outer_time_schedule[intersection_id].update(new_schedule)
                updated_intersections.append(intersection_id)
                
                # 记录客户端更新时间
                client_updates[intersection_id] = current_date
            
            # 保存更新后的外部时间表
            if is_workday(date.today()):
                schedule_file = os.path.join(schedule_json_dir, 'Outer_time_schedule.json')
            else:
                schedule_file = os.path.join(schedule_json_dir, 'Outer_time_schedule_weekend.json')
            
            try:
                with open(schedule_file, 'w') as f:
                    json.dump(outer_time_schedule, f, indent=4)
                logger.info(f"已保存更新后的外部时间表: {schedule_file}")
            except Exception as e:
                logger.error(f"保存外部时间表失败: {e}")
            
            # 保存客户端更新记录
            save_client_updates()
        
        # 准备响应
        response = {
            "status": "partial success" if errors else "success",
            "message": f"Updated {len(updated_intersections)} intersections",
            "update_date": current_date,
            "updated_intersections": updated_intersections
        }
        
        if errors:
            response["errors"] = errors
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"更新外部时间表时出错: {str(e)}")
        return jsonify({
            "error": "Schedule server error",
            "details": str(e)
        }), 500

@app.route('/update_info', methods=['GET'])
def get_update_info():
    """返回所有路口的客户端更新时间信息"""
    return jsonify(client_updates)

@app.route('/update_info/<intersection_id>', methods=['GET'])
def get_intersection_update_info(intersection_id):
    """返回特定路口的客户端更新时间信息"""
    if intersection_id in client_updates:
        return jsonify({intersection_id: client_updates[intersection_id]})
    else:
        return jsonify({"error": "No client update record found"}), 404

# if __name__ == '__main__':
#     # 仅在主进程中初始化
#     # if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' :
#         # 打印路径信息
#     logger.info(f"项目根目录: {PROJECT_ROOT}")
#     logger.info(f"日志目录: {LOG_DIR}")
#     logger.info(f"流量数据目录: {flow_file_dir}")
#     logger.info(f"信号灯数据目录: {stage_file_dir}")
#     logger.info(f"时间表日志目录: {schedule_file_dir}")
#     logger.info(f"客户端更新记录文件: {CLIENT_UPDATE_FILE}")
    
#     # 初始化并启动定时任务
#     init_schedule()
#     schedule_daily_update()
    
#     app.run(host='172.17.0.10', port=6006, debug=True)

if __name__ == '__main__':
    # 打印路径信息
    logger.info(f"项目根目录: {PROJECT_ROOT}")
    logger.info(f"日志目录: {LOG_DIR}")
    logger.info(f"流量数据目录: {flow_file_dir}")
    logger.info(f"信号灯数据目录: {stage_file_dir}")
    logger.info(f"时间表日志目录: {schedule_json_dir}")
    logger.info(f"客户端更新记录文件: {CLIENT_UPDATE_FILE}")
    
    # 初始化并启动定时任务
    if init_schedule():
        logger.info("时间表初始化成功")
    else:
        logger.error("时间表初始化失败")
    update_inner_schedule()  # 启动时先更新一次
    schedule_daily_update()
    
    # 阻塞主线程保持程序运行
    try:
        logger.info("后台定时任务已启动，主线程进入阻塞状态...")
        logger.info("按 Ctrl+C 可退出程序")
        
        # 使用Event对象实现阻塞
        shutdown_event = threading.Event()
        
        # 注册信号处理
        import signal
        def handle_signal(signum, frame):
            logger.info("接收到终止信号，准备退出...")
            shutdown_event.set()
            
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
        
        # 主线程阻塞等待
        while not shutdown_event.is_set():
            shutdown_event.wait(1)
            
        logger.info("程序正常退出")
        
    except Exception as e:
        logger.error(f"主线程异常: {e}")
