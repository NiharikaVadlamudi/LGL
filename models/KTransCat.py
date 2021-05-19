import torch
import numpy as np
import torch.nn as nn
from models.layer import FeatBrd1d, FeatTrans1d, FeatTransKhop, FeatTransKCat, FeatTransKhop


class KTransCAT(nn.Module):
    '''
    Using a logit like ResNet and DenseNet to encode the neighbor in different level
    '''
    def __init__(self, feat_len, num_class, k=1):
        super(KTransCAT, self).__init__()
        self.k = k
        c = [1, 4, 32]
        f = [feat_len, 16, 1]
        self.feat1 = FeatTransKCat(in_channels=c[0], in_features=f[0], out_channels=c[1], out_features=f[1], khop = k)
        self.acvt1 = nn.Sequential(nn.BatchNorm1d(c[1]), nn.Softsign())
        self.feat2 = FeatTransKCat(in_channels=c[1], in_features=f[1], out_channels=c[2], out_features=f[2], khop = k)
        self.acvt2 = nn.Sequential(nn.BatchNorm1d(c[2]), nn.Softsign())
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(p=0.1), nn.Linear(c[2]*f[2], num_class))


    def forward(self, x, neighbor):
        neighbor1 = [i[0] for i in neighbor]
        ## Temp setup the level we chose is also depends on the layer we have 
        if self.k == 1:
            neighbor2 = neighbor1
        else:
            neighbor2 = [i[1] for i in neighbor]

        x, adj = self.feat1(x, neighbor1)
        neighbor2 = [self.feat1.transform(neighbor2[i], adj[i:i+1]) for i in range(x.size(0))]
        x, neighbor2 = self.acvt1(x), [self.acvt1(n) for n in neighbor2]

        x, adj = self.feat2(x, neighbor2)
        x = self.acvt2(x)
        return self.classifier(x)
    
    
class LifelongKTransCAT(KTransCAT):
    def __init__(self, args, feat_len, num_class, k=1):
        super(LifelongKTransCAT, self).__init__(feat_len, num_class, k)
        self.args = args
        self.register_buffer('adj', torch.zeros(1, feat_len, feat_len))
        self.register_buffer('inputs', torch.Tensor(0, 1, feat_len))
        self.register_buffer('targets', torch.LongTensor(0))
        self.neighbor = []
        self.sample_viewed = 0
        self.memory_order = torch.LongTensor()
        self.memory_size = self.args.memory_size
        self.criterion = nn.CrossEntropyLoss()
        exec('self.optimizer = torch.optim.%s(self.parameters(), lr=%f)'%(args.optm, args.lr))

    def observe(self, inputs, targets, neighbor, reply=True):
        self.train()
        for i in range(self.args.iteration):
            self.optimizer.zero_grad()
            outputs = self.forward(inputs, neighbor)
            loss = self.criterion(outputs, targets)
            loss.backward()
            self.optimizer.step()

        self.sample(inputs, targets, neighbor)
        if reply:
            L = torch.randperm(self.inputs.size(0))
            minibatches = [L[n:n+self.args.batch_size] for n in range(0, len(L), self.args.batch_size)]
            for index in minibatches:
                self.optimizer.zero_grad()
                inputs, targets, neighbor = self.inputs[index], self.targets[index], [self.neighbor[i] for i in index.tolist()]
                outputs = self.forward(inputs, neighbor)
                loss = self.criterion(outputs, targets)
                loss.backward()
                self.optimizer.step()

    @torch.no_grad()
    def uniform_sample(self, inputs, targets, neighbor):
        self.inputs = torch.cat((self.inputs, inputs), dim=0)
        self.targets = torch.cat((self.targets, targets), dim=0)
        self.neighbor += neighbor

        if self.inputs.size(0) > self.args.memory_size:
            idx = torch.randperm(self.inputs.size(0))[:self.args.memory_size]
            self.inputs, self.targets = self.inputs[idx], self.targets[idx]
            self.neighbor = [self.neighbor[i] for i in idx.tolist()]

    @torch.no_grad()
    def sample(self, inputs, targets, neighbor):
        self.sample_viewed += inputs.size(0)
        self.memory_order += inputs.size(0)# increase the order 

        self.targets = torch.cat((self.targets, targets), dim=0)
        self.inputs = torch.cat((self.inputs,inputs), dim = 0)
        self.memory_order = torch.cat((self.memory_order, torch.LongTensor(list(range(inputs.size()[0]-1,-1,-1)))), dim = 0)# for debug
        self.neighbor += neighbor

        node_len = int(self.inputs.size(0))
        ext_memory = node_len - self.memory_size
        if ext_memory > 0:
            mask = torch.zeros(node_len,dtype = bool) # mask inputs order targets and neighbor
            reserve = self.memory_size # reserved memrory to be stored
            seg = np.append(np.arange(0,self.sample_viewed,self.sample_viewed/ext_memory),self.sample_viewed)
            for i in range(len(seg)-2,-1,-1):
                left = self.memory_order.ge(np.ceil(seg[i]))*self.memory_order.lt(np.floor(seg[i+1]))
                leftindex = left.nonzero()
                if leftindex.size()[0] > reserve/(i+1): # the quote is not enough, need to be reduced
                    leftindex = leftindex[torch.randperm(leftindex.size()[0])[:int(reserve/(i+1))]] # reserve the quote
                    mask[leftindex] = True
                else:
                    mask[leftindex] = True # the quote is enough
                reserve -= leftindex.size()[0] # deducte the quote
            self.inputs = self.inputs[mask]
            self.targets = self.targets[mask]
            self.memory_order = self.memory_order[mask]
            self.neighbor = [self.neighbor[i] for i in mask.nonzero()]