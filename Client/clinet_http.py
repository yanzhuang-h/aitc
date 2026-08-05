import json
import time
import requests
from collections import defaultdict, deque
from threading import Thread, Lock
import logging

# ==================== 配置参数 ====================
# 在这里修改您的配置
CONFIG = {
    'file_path': '2025-09-08_radar.txt',                          # 日志文件路径
    'server_url': 'http://127.0.0.1:8088',    # 目标服务器URL
    'max_lines': 50000,                                  # 最大读取行数，None表示读取全部
    'send_interval': 1.0,                               # 发送间隔（秒）
    'request_timeout': 5,                               # HTTP请求超时时间（秒）
    'test_mode': False,                                 # 测试模式，True时只读取不发送
}
# ================================================

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LogProcessor:
    def __init__(self, config):
        """
        初始化日志处理器
        
        Args:
            config: 配置字典
        """
        self.file_path = config['file_path']
        self.server_url = config['server_url']
        self.max_lines = config['max_lines']
        self.send_interval = config['send_interval']
        self.request_timeout = config['request_timeout']
        self.test_mode = config['test_mode']
        
        self.device_queues = defaultdict(deque)
        self.lock = Lock()
        self.running = False
        
        # 打印配置信息
        logger.info("=" * 50)
        logger.info("日志处理器配置:")
        logger.info(f"  文件路径: {self.file_path}")
        logger.info(f"  服务器URL: {self.server_url}")
        logger.info(f"  最大读取行数: {self.max_lines if self.max_lines else '全部'}")
        logger.info(f"  发送间隔: {self.send_interval}秒")
        logger.info(f"  请求超时: {self.request_timeout}秒")
        logger.info(f"  测试模式: {'是' if self.test_mode else '否'}")
        logger.info("=" * 50)
        
    def read_and_parse_file(self):
        """读取文件并解析JSON数据"""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                line_count = 0
                error_count = 0
                
                for line_num, line in enumerate(f, 1):
                    if self.max_lines and line_count >= self.max_lines:
                        logger.info(f"已达到最大读取行数限制: {self.max_lines}")
                        break
                    
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        # 解析JSON数据
                        data = json.loads(line)
                        device_id = data.get('deviceNo')
                        
                        if device_id:
                            with self.lock:
                                self.device_queues[device_id].append(data)
                            line_count += 1
                            
                            # 每100条打印一次进度
                            if line_count % 100 == 0:
                                logger.info(f"已读取 {line_count} 条数据...")
                        else:
                            logger.warning(f"第 {line_num} 行缺少deviceId字段")
                            error_count += 1
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"第 {line_num} 行JSON解析错误: {e}")
                        error_count += 1
                        continue
                
                # 打印读取统计
                logger.info(f"\n文件读取完成!")
                logger.info(f"  总行数: {line_num}")
                logger.info(f"  有效数据: {line_count} 条")
                logger.info(f"  错误数据: {error_count} 条")
                logger.info(f"\n设备分组情况:")
                for device_id, queue in sorted(self.device_queues.items()):
                    logger.info(f"  设备 {device_id}: {len(queue)} 条数据")
                
        except FileNotFoundError:
            logger.error(f"文件未找到: {self.file_path}")
            raise
        except Exception as e:
            logger.error(f"读取文件时发生错误: {e}")
            raise
    
    def send_data(self, data):
        """发送数据到服务器"""
        device_id = data.get('deviceId')
        
        if self.test_mode:
            logger.info(f"[测试模式] 模拟发送数据 - 设备ID: {device_id}")
            return
        
        try:
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'LogProcessor/1.0'
            }
            
            response = requests.post(
                self.server_url,
                json=data,
                headers=headers,
                timeout=self.request_timeout
            )
            
            if response.status_code == 200:
                logger.info(f"✓ 成功发送 - 设备: {device_id}, 响应: {response.status_code}")
            else:
                logger.warning(f"✗ 发送失败 - 设备: {device_id}, "
                             f"响应: {response.status_code}, {response.text[:100]}")
                
        except requests.exceptions.Timeout:
            logger.error(f"✗ 发送超时 - 设备: {device_id}")
        except requests.exceptions.ConnectionError:
            logger.error(f"✗ 连接错误 - 设备: {device_id}, 服务器可能未启动")
        except requests.exceptions.RequestException as e:
            logger.error(f"✗ 发送异常 - 设备: {device_id}, 错误: {e}")
    
    def process_queues(self):
        """处理队列，定时发送各组第一条数据"""
        self.running = True
        round_num = 0
        
        logger.info(f"\n开始处理数据队列，每 {self.send_interval} 秒发送一轮...")
        
        while self.running:
            round_num += 1
            start_time = time.time()
            
            with self.lock:
                # 获取所有非空队列的设备ID
                active_devices = [device_id for device_id, queue in self.device_queues.items() 
                                if len(queue) > 0]
            
            if not active_devices:
                logger.info("\n所有队列已处理完毕!")
                break
            
            logger.info(f"\n第 {round_num} 轮发送开始...")
            
            # 为每个设备创建发送线程
            threads = []
            for device_id in active_devices:
                with self.lock:
                    if self.device_queues[device_id]:
                        data = self.device_queues[device_id].popleft()
                        thread = Thread(target=self.send_data, args=(data,))
                        threads.append(thread)
                        thread.start()
            
            # 等待所有线程完成
            for thread in threads:
                thread.join()
            
            # 计算剩余数据量
            with self.lock:
                remaining_by_device = {device_id: len(queue) 
                                     for device_id, queue in self.device_queues.items() 
                                     if len(queue) > 0}
                total_remaining = sum(remaining_by_device.values())
            
            if remaining_by_device:
                logger.info(f"第 {round_num} 轮完成，剩余数据: {total_remaining} 条")
                for device_id, count in sorted(remaining_by_device.items()):
                    logger.info(f"  设备 {device_id}: {count} 条")
            
            # 确保每轮间隔指定时间
            elapsed = time.time() - start_time
            if elapsed < self.send_interval:
                time.sleep(self.send_interval - elapsed)
    
    def stop(self):
        """停止处理"""
        self.running = False
    
    def run(self):
        """运行处理器"""
        try:
            logger.info("\n开始读取文件...")
            self.read_and_parse_file()
            
            if not self.device_queues:
                logger.warning("未找到任何有效数据，程序退出")
                return
            
            logger.info("\n开始处理数据队列...")
            self.process_queues()
            
            logger.info("\n处理完成!")
            
        except KeyboardInterrupt:
            logger.info("\n收到中断信号，正在停止...")
            self.stop()
        except Exception as e:
            logger.error(f"\n程序异常: {e}")
            raise


def test_server():
    """测试服务器连接"""
    try:
        response = requests.get(CONFIG['server_url'], timeout=2)
        logger.info(f"服务器连接测试成功: {response.status_code}")
        return True
    except:
        logger.warning(f"无法连接到服务器: {CONFIG['server_url']}")
        return False


def main():
    """主函数"""
    print("\n日志文件处理器 v1.0")
    print("=" * 50)
    
    # 创建并运行处理器
    processor = LogProcessor(CONFIG)
    
    # 如果不是测试模式，先测试服务器连接
    if not CONFIG['test_mode']:
        logger.info(f"\n测试服务器连接: {CONFIG['server_url']}")
        if not test_server():
            user_input = input("\n服务器无法连接，是否继续？(y/n): ")
            if user_input.lower() != 'y':
                logger.info("用户取消操作")
                return
    
    # 运行处理器
    processor.run()


if __name__ == '__main__':
    main()
