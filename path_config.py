# path_config.py
import os
import sys

# 获取项目根目录
def get_project_root():
    if getattr(sys, 'frozen', False):
        # 打包后的执行路径
        return os.path.dirname(sys.executable)
    else:
        # 正常开发路径
        return os.path.dirname(os.path.abspath(__file__))

# 项目根目录
PROJECT_ROOT = get_project_root()

# 日志目录
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs_data')

# 子目录配置
DIRECTORIES = {
    'flow': os.path.join(LOG_DIR, 'flow'), # 流量数据目录
    'stage': os.path.join(LOG_DIR, 'stage'), # 信号灯阶段数据目录
    'online':os.path.join(LOG_DIR, 'online'), # 在线数据目录
    'radar': os.path.join(LOG_DIR, 'radar'), # 雷达数据目录
    'extend': os.path.join(LOG_DIR, 'extend'), # 扩展数据目录
    'inner_schedule': os.path.join(LOG_DIR, 'inner_schedule'), # 内部时间表记录数据目录
    'outer_schedule': os.path.join(LOG_DIR, 'outer_schedule'), # 外部时间表记录数据目录
    'schedule': os.path.join(PROJECT_ROOT, 'time_schedule'), # 时间表目录
    'schedule_json': os.path.join(PROJECT_ROOT, 'time_schedule','schedule_json'), # 时间表模块目录
    'get_time_module': os.path.join(PROJECT_ROOT, 'time_schedule', 'get_time_module'), # 获取时间模块目录
    'fine_turn': os.path.join(LOG_DIR, 'fine_turn'), # 微调日志目录
}

# 确保所有目录存在
def create_directories():
    for name, path in DIRECTORIES.items():
        os.makedirs(path, exist_ok=True)
        print(f"Created directory: {name} -> {path}")

# 获取路径
def get_path(name):
    return DIRECTORIES.get(name, None)

# 初始化时创建目录
create_directories()

if __name__ == "__main__":
    # 测试路径配置
    print("Project Root:", PROJECT_ROOT)
    for name, path in DIRECTORIES.items():
        print(f"{name.capitalize()} Directory: {path}")
    
    # 测试获取路径
    print("Flow Path:", get_path('flow'))
    print("Stage Path:", get_path('stage'))
    print("Schedule Path:", get_path('schedule'))
    print("Schedule Modules Path:", get_path('schedule_modules'))