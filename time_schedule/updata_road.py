import time
import logging
import signal
import threading

logger = logging.getLogger(__name__)

import torch
from torch import nn
from einops import rearrange


# 添加全局标志变量用于控制函数执行
_should_stop = threading.Event()

# 信号处理函数
def signal_handler(signum, frame):
    """处理中断信号"""
    logger.warning(f"接收到信号 {signum}，准备停止 updata_road_func")
    _should_stop.set()

# 注册信号处理器
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# classes (保持不变)
class FeedForward(nn.Module):
    def __init__(self, dim, hidden_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.LayerNorm(dim),
            nn.Linear(dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, dim),
        )
    def forward(self, x):
        return self.net(x)

class Attention(nn.Module):
    def __init__(self, dim, heads = 8, dim_head = 64):
        super().__init__()
        inner_dim = dim_head *  heads
        self.heads = heads
        self.scale = dim_head ** -0.5
        self.norm = nn.LayerNorm(dim)

        self.attend = nn.Softmax(dim = -1)

        self.to_qkv = nn.Linear(dim, inner_dim * 3, bias = False)
        self.to_out = nn.Linear(inner_dim, dim, bias = False)

    def forward(self, x):
        x = self.norm(x)

        qkv = self.to_qkv(x).chunk(3, dim = -1)
        q, k, v = map(lambda t: rearrange(t, 'b n (h d) -> b h n d', h = self.heads), qkv)

        dots = torch.matmul(q, k.transpose(-1, -2)) * self.scale

        attn = self.attend(dots)

        out = torch.matmul(attn, v)
        out = rearrange(out, 'b h n d -> b n (h d)')
        return self.to_out(out)

class Transformer(nn.Module):
    def __init__(self, dim, depth, heads, dim_head, mlp_dim):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.layers = nn.ModuleList([])
        for _ in range(depth):
            self.layers.append(nn.ModuleList([
                Attention(dim, heads = heads, dim_head = dim_head),
                FeedForward(dim, mlp_dim)
            ]))
    def forward(self, x):
        for attn, ff in self.layers:
            x = attn(x) + x
            x = ff(x) + x
        return self.norm(x)

class DTQN(nn.Module):
    def __init__(self, *, data_size,Len_time=600,flow_size=28,queue_size=56,stage_size=2,hidden_dim=64,T_size=1034, num_classes=1, dim=1024, depth=12, heads=8, mlp_dim=1024, dim_head = 64):
        super().__init__()
        self.flow_size = flow_size
        self.queue_size = queue_size
        self.stage_size = stage_size
        self.flow_patch_embedding = nn.Sequential(
            nn.LayerNorm(flow_size),
            nn.Linear(flow_size, 256),
            nn.LayerNorm(256),
        )
        self.stage_patch_embedding = nn.Sequential(
            nn.LayerNorm(stage_size),
            nn.Linear(stage_size, 64),
            nn.LayerNorm(64),
        )
        self.queue_patch_embedding = nn.Sequential(
            nn.LayerNorm(queue_size),
            nn.Linear(queue_size, 512),
            nn.LayerNorm(512),
        )
        self.to_patch_embedding = nn.Sequential(
            nn.LayerNorm(832),
            nn.Linear(832, dim),
            nn.LayerNorm(dim),
        )
        self.pos_embedding = torch.zeros((data_size[0],dim))

        self.transformer = Transformer(dim, depth, heads, dim_head, mlp_dim)
        self.pool = "mean"
        self.Reward_predict = nn.Sequential(
            nn.Linear(dim, dim//4),
            nn.GELU(),
            nn.Linear(dim//4, dim//16),
            nn.LayerNorm(dim//16),
            nn.Linear(dim//16, 1),
        )
        self.pass_predict1 = nn.Sequential(
            nn.Linear(T_size,64),
            nn.ReLU(),
            nn.Linear(64,1),
        )
        self.pass_predict2 = nn.Sequential(
            nn.Linear(T_size, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )
    def forward(self, mix_data,T_data):
        device = mix_data.device
        flow = self.flow_patch_embedding(mix_data[:,:,:self.flow_size])
        queue = self.queue_patch_embedding(mix_data[:,:,self.flow_size:self.queue_size+self.flow_size])
        stage = self.stage_patch_embedding(mix_data[:,:,self.queue_size+self.flow_size:])
        mix_data = torch.cat((flow,queue,stage),dim=2)
        x = self.to_patch_embedding(mix_data)
        x += self.pos_embedding.to(device, dtype=x.dtype)
        x = self.transformer(x)
        x = x.mean(dim = 1)
        p1 = self.pass_predict1(torch.cat((T_data,x),dim=1))
        p2 = self.pass_predict2(torch.cat((T_data,x),dim=1))
        x = self.Reward_predict(x)
        return x,p1,p2

def updata_road_func():
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    logger.info("updata_road_func 定时任务开始执行")
    start_time = time.time()
    
    # 重置停止标志
    _should_stop.clear()
    
    try:
        # 检查是否应该停止
        if _should_stop.is_set():
            logger.info("接收到停止信号，updata_road_func 提前退出")
            return
            
        for z in range(1, 100):
            # 每次迭代前检查是否应该停止
            if _should_stop.is_set():
                logger.info("接收到停止信号，updata_road_func 提前退出")
                # 清理GPU内存
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                return
                
            logger.debug(f"迭代 {z} 开始 - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 创建模型
            a = DTQN(data_size=(600, 86)).to(device)
            
            batch_size = 24
            data = 1000
            
            for i in range(data):
                # 在内部循环中也检查是否应该停止
                if _should_stop.is_set():
                    logger.info("接收到停止信号，updata_road_func 提前退出")
                    # 清理GPU内存
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    return
                    
                t = torch.randn(batch_size, 600, 86).to(device)
                t1 = torch.randn(batch_size, 10).to(device)
                x, p1, p2 = a(t, t1)
                
                # 定期记录进度
                if i % 100 == 0:
                    logger.debug(f"处理进度: 迭代 {z}, 批次 {i}/{data}")
        
        # 计算剩余时间，并分段睡眠，每次睡眠前检查是否应该停止
        end_time = time.time()
        elapsed_time = end_time - start_time
        time_left = max(0, 7200 - elapsed_time)
        
        logger.info(f"主循环完成，剩余时间: {time_left:.2f} 秒")
        
        if time_left > 0:
            chunks = int(time_left // 10) + 1
            for i in range(chunks):
                if _should_stop.is_set():
                    logger.info("接收到停止信号，updata_road_func 提前退出")
                    return
                    
                # 每次最多睡眠10秒
                sleep_time = min(10, time_left - i * 10)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    logger.debug(f"updata_road_func 仍在运行中... 已运行 {elapsed_time + i * 10:.0f} 秒")
        
        logger.info("updata_road_func 完成2小时模拟运行")
        
    except Exception as e:
        logger.error(f"updata_road_func 执行过程中发生异常: {e}")
        # 清理GPU内存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    finally:
        # 确保无论如何都清理GPU内存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("updata_road_func 执行结束，资源已清理")


def updata_road_func1():
    device = "cuda:1" if torch.cuda.is_available() else "cpu"
    logger.info("updata_road_func 定时任务开始执行")
    start_time = time.time()

    # 重置停止标志
    _should_stop.clear()

    try:
        # 检查是否应该停止
        if _should_stop.is_set():
            logger.info("接收到停止信号，updata_road_func 提前退出")
            return

        for z in range(1, 100):
            # 每次迭代前检查是否应该停止
            if _should_stop.is_set():
                logger.info("接收到停止信号，updata_road_func 提前退出")
                # 清理GPU内存
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                return

            logger.debug(f"迭代 {z} 开始 - {time.strftime('%Y-%m-%d %H:%M:%S')}")

            # 创建模型
            a = DTQN(data_size=(600, 86)).to(device)

            batch_size = 24
            data = 1000

            for i in range(data):
                # 在内部循环中也检查是否应该停止
                if _should_stop.is_set():
                    logger.info("接收到停止信号，updata_road_func 提前退出")
                    # 清理GPU内存
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    return

                t = torch.randn(batch_size, 600, 86).to(device)
                t1 = torch.randn(batch_size, 10).to(device)
                x, p1, p2 = a(t, t1)

                # 定期记录进度
                if i % 100 == 0:
                    logger.debug(f"处理进度: 迭代 {z}, 批次 {i}/{data}")

        # 计算剩余时间，并分段睡眠，每次睡眠前检查是否应该停止
        end_time = time.time()
        elapsed_time = end_time - start_time
        time_left = max(0, 7200 - elapsed_time)

        logger.info(f"主循环完成，剩余时间: {time_left:.2f} 秒")

        if time_left > 0:
            chunks = int(time_left // 10) + 1
            for i in range(chunks):
                if _should_stop.is_set():
                    logger.info("接收到停止信号，updata_road_func 提前退出")
                    return

                # 每次最多睡眠10秒
                sleep_time = min(10, time_left - i * 10)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    logger.debug(f"updata_road_func 仍在运行中... 已运行 {elapsed_time + i * 10:.0f} 秒")

        logger.info("updata_road_func 完成2小时模拟运行")

    except Exception as e:
        logger.error(f"updata_road_func 执行过程中发生异常: {e}")
        # 清理GPU内存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    finally:
        # 确保无论如何都清理GPU内存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("updata_road_func 执行结束，资源已清理")