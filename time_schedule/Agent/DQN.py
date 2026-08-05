
import torch
import torch.nn as nn

device = "cuda" if torch.cuda.is_available() else "cpu"

class DqnAgent(nn.Module):
    def __init__(self,input_size,output_size):
        super(DqnAgent, self).__init__()
        self.input = input_size
        self.output = output_size
        self.policy_net = nn.Sequential(
            nn.Linear(self.input,64),
            nn.LeakyReLU(),
            nn.Linear(64,1)
        )
        # self.target_net = networks.DqnNetwork(self.input,self.output).to(device)
    def forward(self,state):
        x = self.policy_net(state)
        return x


if __name__ == "__main__":
    t = torch.ones(32,15).to(device)
    a = DqnAgent(15,1).to(device)
    print(a(t).shape)