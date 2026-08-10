#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import json
import time
import collections
import itertools
import threading
import argparse
import sys
import re
import os
from typing import Dict, List, Optional, Any, Iterator
from enum import Enum
import logging
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataType(Enum):
    """数据类型枚举"""
    FLOW = "flow"
    QUEUE = "queue"  
    STAGE = "stage"
    ONLINE = "online"
    EXTEND = "extend"
    RADAR = "radar"

class MultilineJSONParser:
    """支持跨行JSON解析的解析器"""
    
    def __init__(self, data_type: str):
        self.data_type = data_type
        self.stats = {
            'total_objects': 0,
            'valid_objects': 0,
            'invalid_objects': 0,
            'parse_errors': 0
        }
    
    def extract_json_objects(self, content: str) -> Iterator[str]:
        """
        从文件内容中提取JSON对象
        支持单行和跨行JSON
        """
        # 先尝试按行解析（兼容原有单行格式）
        lines = content.strip().split('\n')
        
        # 如果只有一行且包含多个JSON对象
        if len(lines) == 1 and self._count_json_objects(content) > 1:
            yield from self._extract_concatenated_json(content)
            return
        
        # 尝试逐行解析
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if self._is_complete_json(line):
                # 单行JSON
                yield line
            else:
                # 可能是跨行JSON的一部分，需要组合解析
                continue
        
        # 如果逐行解析失败，尝试整体解析
        if self.stats['valid_objects'] == 0:
            yield from self._extract_multiline_json(content)
    
    def _count_json_objects(self, content: str) -> int:
        """估算内容中JSON对象的数量"""
        # 简单计算顶级花括号的数量
        brace_count = 0
        object_count = 0
        in_string = False
        escaped = False
        
        for char in content:
            if escaped:
                escaped = False
                continue
                
            if char == '\\':
                escaped = True
                continue
                
            if char == '"':
                in_string = not in_string
                continue
                
            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        object_count += 1
        
        return object_count
    
    def _is_complete_json(self, text: str) -> bool:
        """检查文本是否是完整的JSON"""
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False
    
    def _extract_concatenated_json(self, content: str) -> Iterator[str]:
        """提取连续的JSON对象（无分隔符）"""
        decoder = json.JSONDecoder()
        idx = 0
        
        while idx < len(content):
            content = content[idx:].lstrip()
            if not content:
                break
                
            try:
                obj, end_idx = decoder.raw_decode(content)
                json_str = content[:end_idx]
                yield json_str
                idx += end_idx
            except json.JSONDecodeError as e:
                logger.warning(f"[{self.data_type}] 连续JSON解析错误: {e}")
                break
    
    def _extract_multiline_json(self, content: str) -> Iterator[str]:
        """提取跨行的JSON对象"""
        # 方法1: 尝试整体解析为单个JSON
        try:
            json.loads(content)
            yield content
            return
        except json.JSONDecodeError:
            pass
        
        # 方法2: 尝试解析为JSON数组
        try:
            # 如果内容不以[开头，尝试包装为数组
            if not content.strip().startswith('['):
                wrapped_content = '[' + content + ']'
                json.loads(wrapped_content)
                yield wrapped_content
                return
            else:
                json.loads(content)
                yield content
                return
        except json.JSONDecodeError:
            pass
        
        # 方法3: 使用花括号匹配提取多个JSON对象
        yield from self._extract_by_brace_matching(content)
    
    def _extract_by_brace_matching(self, content: str) -> Iterator[str]:
        """通过花括号匹配提取JSON对象"""
        brace_count = 0
        start_pos = 0
        in_string = False
        escaped = False
        
        for i, char in enumerate(content):
            if escaped:
                escaped = False
                continue
                
            if char == '\\':
                escaped = True
                continue
                
            if char == '"':
                in_string = not in_string
                continue
                
            if not in_string:
                if char == '{':
                    if brace_count == 0:
                        start_pos = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        # 找到完整的JSON对象
                        json_str = content[start_pos:i+1]
                        if self._is_complete_json(json_str):
                            yield json_str
    
    def parse_json_objects(self, content: str) -> List[Dict]:
        """解析文件内容中的所有JSON对象"""
        valid_objects = []
        
        for json_str in self.extract_json_objects(content):
            try:
                self.stats['total_objects'] += 1
                
                data = json.loads(json_str)
                
                if isinstance(data, list):
                    # JSON数组
                    for item in data:
                        if isinstance(item, dict):
                            valid_objects.append(item)
                            self.stats['valid_objects'] += 1
                elif isinstance(data, dict):
                    # 单个JSON对象
                    valid_objects.append(data)
                    self.stats['valid_objects'] += 1
                else:
                    self.stats['invalid_objects'] += 1
                    
            except json.JSONDecodeError as e:
                self.stats['parse_errors'] += 1
                logger.warning(f"[{self.data_type}] JSON解析失败: {e}")
                continue
        
        return valid_objects
    
    def print_stats(self):
        """打印解析统计"""
        logger.info(f"[{self.data_type}] JSON解析统计:")
        logger.info(f"  发现对象: {self.stats['total_objects']}")
        logger.info(f"  有效对象: {self.stats['valid_objects']}")
        logger.info(f"  无效对象: {self.stats['invalid_objects']}")
        logger.info(f"  解析错误: {self.stats['parse_errors']}")



class EnhancedDataSender:
    """增强的数据发送器，支持跨行JSON"""
    
    def __init__(self):
        # 配置同轻量级版本
        self.host = '127.0.0.1'
        self.port = 65432
        self.timeout = 10
        self.parallel_enabled = True
        self.max_workers = 8
        self.use_threading = True
        data1='2026-07-29'
        Send_time = 1785255292
        # 数据类型配置（真实数据位于 test/flow_data、test/extend_data、test/online_data，请在项目根目录运行）
        # 默认快速冒烟规模：只回放少量数据验证链路畅通；要全量回放可用 --duration 300 --max-preload 5000 覆盖
        sudu=0.1
        self.data_configs = {
            'flow': {
                'enabled': True,
                'file_path': "test/flow_data/" + data1 + '_flow.txt',
                'timestamp_field': 'ts',
                'send_mode': 'timed',
                'send_interval': sudu,
                'duration_sec': 60,
                'start_timestamp':  Send_time,
            },
            'queue': {
                'enabled': False,
                'file_path': 'over_flow.txt',
                'timestamp_field': 'ts',
                'send_mode': 'timed',
                'send_interval': 1,
                'duration_sec': 3600,
                'start_timestamp': 1764137866,
            },
            'stage': {
                'enabled':  False,
                'file_path': '2025-09-09_stage.txt',
                'timestamp_field': 'time',
                'send_mode': 'timed',
                'send_interval': 1,
                'duration_sec': 3600,
                'start_timestamp': Send_time,
            },
            'online': {
                'enabled':True,
                'file_path': "test/online_data/2026-05-14_online.txt",
                'id_field': 'rid',
                'send_mode': 'round_robin',
                'send_interval': sudu,
                'max_preload_records': 500,
            },
            'extend': {
                'enabled':  True,
                'file_path': "test/extend_data/" + data1 + '_extend.txt',
                'timestamp_field': 'time',
                'send_mode': 'timed',
                'send_interval': sudu,
                'duration_sec': 60,
                'start_timestamp': Send_time,
            },
            'radar': {
                'enabled': False,
                'file_path': 'over_flow.txt',
                'id_field': 'jtll_ddbh',
                'send_mode': 'round_robin',
                'send_interval': 1,
                'max_preload_records': 2000,
                'use_regex_parser': False,
            }
        }
    
    def apply_args(self, args):
        """应用命令行参数"""
        if args.host:
            self.host = args.host
        if args.port:
            self.port = args.port
        if args.timeout:
            self.timeout = args.timeout
        if args.workers:
            self.max_workers = args.workers
        if args.use_processes:
            self.use_threading = False
            
        # 启用指定的数据类型
        if args.enable_types:
            enabled_types = [t.strip() for t in args.enable_types.split(',')]
            for data_type in enabled_types:
                if data_type in self.data_configs:
                    self.data_configs[data_type]['enabled'] = True
                    logger.info(f"启用数据类型: {data_type}")
        
        # 单个数据类型配置覆盖
        if args.type and args.type in self.data_configs:
            config = self.data_configs[args.type]
            config['enabled'] = True
            
            if args.file:
                config['file_path'] = args.file
            if args.interval:
                config['send_interval'] = args.interval
            if args.duration:
                config['duration_sec'] = args.duration
            if args.start_timestamp:
                config['start_timestamp'] = args.start_timestamp
            if args.max_preload:
                config['max_preload_records'] = args.max_preload
    
    def get_enabled_types(self) -> List[str]:
        """获取启用的数据类型"""
        return [name for name, config in self.data_configs.items() if config.get('enabled', False)]

class EnhancedSingleSender:
    """增强的单个数据发送器，支持跨行JSON"""
    
    def __init__(self, data_type: str, config: Dict, host: str, port: int, timeout: int):
        self.data_type = data_type
        self.config = config
        self.host = host
        self.port = port
        self.timeout = timeout
        
        # 数据存储
        self.time_to_data_map = collections.defaultdict(list)
        self.id_queues = collections.defaultdict(collections.deque)
        
        # 状态
        self.socket = None
        self.total_sent = 0
        
    def load_data_enhanced(self):
        """增强的数据加载，支持跨行JSON"""
        filename = self.config['file_path']
        send_mode = self.config['send_mode']
        
        logger.info(f"[{self.data_type}] 增强加载数据: {filename}")
        
        if not os.path.exists(filename):
            logger.error(f"[{self.data_type}] 文件不存在: {filename}")
            return
        
        try:
            if send_mode == 'round_robin' and self.config.get('max_preload_records'):
                # 轮询模式快速验证：只读文件头部若干行（够 preload 即可），避免解析超大文件
                max_records = self.config.get('max_preload_records', 50000)
                head_lines = max_records * 3  # 留冗余覆盖无效/跨行记录
                with open(filename, 'r', encoding='utf-8') as file:
                    content = ''.join(itertools.islice(file, head_lines))
            else:
                # 读取整个文件内容
                with open(filename, 'r', encoding='utf-8') as file:
                    content = file.read()
            
            # 使用多行JSON解析器
            parser = MultilineJSONParser(self.data_type)
            
            # 特殊处理extend数据的正则模式
            if self.config.get('use_regex_parser', False):
                self._load_extend_data_enhanced(content, parser)
            else:
                # 解析所有JSON对象
                json_objects = parser.parse_json_objects(content)
                parser.print_stats()
                
                if send_mode == 'timed':
                    self._process_timed_data(json_objects)
                else:
                    self._process_round_robin_data(json_objects)
                    
        except Exception as e:
            logger.error(f"[{self.data_type}] 加载数据失败: {e}")
            raise
    
    def _load_extend_data_enhanced(self, content: str, parser: MultilineJSONParser):
        """处理extend数据的特殊格式"""
        pattern = r'\[{[^}]*}\]'
        matches = re.findall(pattern, content)
        
        valid_objects = []
        for match in matches:
            try:
                data = json.loads(match)
                if isinstance(data, list) and data:
                    valid_objects.extend(data)
                parser.stats['valid_objects'] += len(data) if isinstance(data, list) else 1
            except json.JSONDecodeError:
                parser.stats['parse_errors'] += 1
                continue
        
        parser.print_stats()
        self._process_round_robin_data(valid_objects)
    
    def _process_timed_data(self, json_objects: List[Dict]):
        """处理时间数据"""
        timestamp_field = self.config['timestamp_field']
        duration_sec = self.config['duration_sec']
        start_timestamp = self.config['start_timestamp']
        
        count = 0
        for obj in json_objects:
            if timestamp_field in obj:
                timestamp_ms = int(obj[timestamp_field])
                timestamp_sec = timestamp_ms // 1000
                
                if (timestamp_sec - start_timestamp) > duration_sec:
                    break
                    
                if timestamp_sec >= start_timestamp:
                    self.time_to_data_map[timestamp_sec].append(obj)
                    count += 1
        
        logger.info(f"[{self.data_type}] 时间数据处理完成: {count} 条记录，{len(self.time_to_data_map)} 个时间点")
    
    def _process_round_robin_data(self, json_objects: List[Dict]):
        """处理轮询数据"""
        id_field = self.config['id_field']
        max_records = self.config.get('max_preload_records', 50000)
        
        count = 0
        for obj in json_objects:
            if count >= max_records:
                break
                
            if id_field in obj:
                item_id = str(obj[id_field])
                self.id_queues[item_id].append(obj)
                count += 1
        
        logger.info(f"[{self.data_type}] 轮询数据处理完成: {count} 条记录，{len(self.id_queues)} 个不同ID")
        
        # 显示前几个ID的统计
        for i, (item_id, queue) in enumerate(list(self.id_queues.items())[:5]):
            logger.info(f"[{self.data_type}] {id_field} {item_id}: {len(queue)} 条数据")
        if len(self.id_queues) > 5:
            logger.info(f"[{self.data_type}] ... 还有 {len(self.id_queues) - 5} 个其他{id_field}")
    
    def connect_fast(self) -> bool:
        """快速连接"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            return True
        except Exception as e:
            logger.error(f"[{self.data_type}] 连接失败: {e}")
            if self.socket:
                self.socket.close()
                self.socket = None
            return False
    
    def send_fast(self, data_batch: List) -> bool:
        """快速发送"""
        if not self.socket:
            return False
            
        try:
            payload = '\n'.join(json.dumps(data, ensure_ascii=False) for data in data_batch)
            payload += '\n'
            self.socket.sendall(payload.encode('utf-8'))
            self.total_sent += len(data_batch)
            return True
        except Exception as e:
            logger.error(f"[{self.data_type}] 发送失败: {e}")
            if self.socket:
                self.socket.close()
                self.socket = None
            return False
    
    def run_enhanced(self) -> Dict:
        """增强运行方法"""
        try:
            logger.info(f"[{self.data_type}] 开始增强发送")
            
            # 增强数据加载
            self.load_data_enhanced()
            
            # 连接服务器
            if not self.connect_fast():
                return {'status': 'error', 'message': '连接失败'}
            
            send_mode = self.config['send_mode']
            send_interval = self.config['send_interval']
            
            if send_mode == 'timed':
                self._run_timed_enhanced(send_interval)
            else:
                self._run_round_robin_enhanced(send_interval)
                
            return {'status': 'completed', 'total_sent': self.total_sent}
            
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
        finally:
            if self.socket:
                self.socket.close()
    
    def _run_timed_enhanced(self, interval):
        """增强的时间模式运行：在窗口内只发送实际存在的时间点，发完即止。"""
        if not self.time_to_data_map:
            return

        start_time = min(self.time_to_data_map.keys())
        end_time = start_time + self.config['duration_sec']

        for current_time in sorted(self.time_to_data_map.keys()):
            if current_time > end_time:
                break
            data_to_send = self.time_to_data_map.get(current_time, [])
            if not data_to_send:
                continue
            if self.send_fast(data_to_send):
                logger.info(f"[{self.data_type}] 发送 {current_time}s: {len(data_to_send)} 条")
            else:
                if self.connect_fast():
                    self.send_fast(data_to_send)
            time.sleep(interval)
    
    def _run_round_robin_enhanced(self, interval):
        """增强的轮询模式运行"""
        while True:
            batch = []
            empty_queues = []
            
            for item_id, queue in self.id_queues.items():
                if queue:
                    batch.append(queue.popleft())
                else:
                    empty_queues.append(item_id)
            
            for item_id in empty_queues:
                del self.id_queues[item_id]
            
            if not batch:
                break
                
            if self.send_fast(batch):
                logger.info(f"[{self.data_type}] 发送批次: {len(batch)} 条")
            else:
                if self.connect_fast():
                    self.send_fast(batch)
            
            time.sleep(interval)

def run_enhanced_sender(data_type: str, config: Dict, host: str, port: int, timeout: int) -> Dict:
    """运行增强的发送器"""
    sender = EnhancedSingleSender(data_type, config, host, port, timeout)
    return sender.run_enhanced()

def create_parser():
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(description='支持跨行JSON的数据发送客户端')
    
    parser.add_argument('--type', choices=['flow', 'queue', 'stage', 'online', 'extend', 'radar'],
                        help='单个数据类型')
    parser.add_argument('--enable-types', type=str,
                        help='启用的数据类型，逗号分隔')
    
    # 服务器参数
    parser.add_argument('--host', default='127.0.0.1', help='服务器地址')
    parser.add_argument('--port', type=int, default=65432, help='服务器端口')
    parser.add_argument('--timeout', type=int, default=10, help='连接超时')
    
    # 并行参数
    parser.add_argument('--workers', type=int, default=8, help='最大worker数')
    parser.add_argument('--use-processes', action='store_true', help='使用进程池')
    
    # 数据参数
    parser.add_argument('--file', help='数据文件路径')
    parser.add_argument('--interval', type=float, help='发送间隔(秒)')
    parser.add_argument('--duration', type=int, help='发送时长(秒)')
    parser.add_argument('--start-timestamp', type=int,
                        help='起始时间戳(秒)，用于定位数据回放起点')
    parser.add_argument('--max-preload', type=int, help='最大预读取数')
    
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    return parser

def main():
    """主函数"""
    parser = create_parser()
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 创建增强发送器
    sender = EnhancedDataSender()
    sender.apply_args(args)
    
    logger.info(f"服务器: {sender.host}:{sender.port}")
    logger.info("支持跨行JSON解析")
    
    try:
        if args.type:
            # 单一类型发送
            config = sender.data_configs[args.type]
            logger.info(f"发送单一数据类型: {args.type}")
            logger.info(f"文件: {config['file_path']}, 间隔: {config.get('send_interval')}s")
            
            result = run_enhanced_sender(args.type, config, sender.host, sender.port, sender.timeout)
            
            if result['status'] == 'error':
                logger.error(f"发送失败: {result.get('message')}")
                sys.exit(1)
            else:
                logger.info(f"发送完成，总计: {result.get('total_sent', 0)} 条")
        else:
            # 并行发送
            enabled_types = sender.get_enabled_types()
            if not enabled_types:
                logger.warning("没有启用的数据类型，请使用 --enable-types 参数")
                sys.exit(1)
            
            logger.info(f"并行发送数据类型: {enabled_types}")
            
            executor_class = ProcessPoolExecutor if not sender.use_threading else ThreadPoolExecutor
            
            with executor_class(max_workers=sender.max_workers) as executor:
                futures = {}
                
                for data_type in enabled_types:
                    config = sender.data_configs[data_type]
                    future = executor.submit(run_enhanced_sender, data_type, config, 
                                           sender.host, sender.port, sender.timeout)
                    futures[data_type] = future
                
                for data_type, future in futures.items():
                    try:
                        result = future.result()
                        if result['status'] == 'completed':
                            logger.info(f"[{data_type}] 完成，发送: {result.get('total_sent', 0)} 条")
                        else:
                            logger.error(f"[{data_type}] 失败: {result.get('message')}")
                    except Exception as e:
                        logger.error(f"[{data_type}] 异常: {e}")
        
    except KeyboardInterrupt:
        logger.info("程序中断")
    except Exception as e:
        logger.error(f"程序失败: {e}")

if __name__ == "__main__":
    main()