import time

import torch
from torch import nn
from einops import rearrange
device = "cuda" if torch.cuda.is_available() else "cpu"

# classes

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

if __name__ == "__main__":
    #print(time.localtime(time.time()))
    for z in range(1,100):
        print(time.localtime(time.time()))
        a = DTQN(data_size=(600, 86)).to(device)
        batch_size = 24
        data =1000
        for i in range(data):
            t = torch.randn(batch_size,600, 86).to(device)
            t1 = torch.randn(batch_size, 10).to(device)
            x, p1, p2 = a(t, t1)
    print(time.localtime(time.time()))



