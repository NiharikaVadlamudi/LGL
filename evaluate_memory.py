# Copyright <2020> <Chen Wang <https://chenwang.site>, Carnegie Mellon University>

# Redistribution and use in source and binary forms, with or without modification, are 
# permitted provided that the following conditions are met:

# 1. Redistributions of source code must retain the above copyright notice, this list of 
# conditions and the following disclaimer.

# 2. Redistributions in binary form must reproduce the above copyright notice, this list 
# of conditions and the following disclaimer in the documentation and/or other materials 
# provided with the distribution.

# 3. Neither the name of the copyright holder nor the names of its contributors may be 
# used to endorse or promote products derived from this software without specific prior 
# written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY 
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES 
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT 
# SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, 
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED 
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; 
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN 
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN 
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH 
# DAMAGE.

import os
import tqdm
import copy
import torch
import os.path
import argparse
import pickle
import time
import numpy as np
import torch.nn as nn
import matplotlib.pyplot as plt
from models import Net
import torch.utils.data as Data
from datasets import Citation, citation_collate
from continuum import Continuum


def performance_quiet(loader, net):
    correct, total = 0, 0
    with torch.no_grad():
        for batch_idx, (inputs, targets, neighbor) in enumerate(loader):
            if torch.cuda.is_available():
                inputs, targets, neighbor = inputs.cuda(), targets.cuda(), [item.cuda() for item in neighbor]
            outputs = net(inputs, neighbor)
            _, predicted = torch.max(outputs.data, 1)
            total += targets.size(0)
            correct += predicted.eq(targets.data).cpu().sum().item()
        acc = 100.*correct/total
    return acc

def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
    
# Arguements
parser = argparse.ArgumentParser(description='Feature Graph Networks')
parser.add_argument("--device", type=str, default='cuda:0', help="cuda or cpu")
parser.add_argument("--data-root", type=str, default='/data/datasets', help="dataset location")
parser.add_argument("--dataset", type=str, default='cora', help="cora, citeseer, or pubmed")
parser.add_argument("--lr", type=float, default=0.1, help="learning rate, 0.01 for citeseer")
parser.add_argument("--batch-size", type=int, default=15, help="minibatch size")
parser.add_argument("--iteration", type=int, default=5, help="number of training iteration")
parser.add_argument("--memory-size", type=int, default=100, help="number of samples")
parser.add_argument("--momentum", type=float, default=0, help="momentum of SGD optimizer")
parser.add_argument("--adj-momentum", type=float, default=0.9, help="momentum of the feature adjacency")
parser.add_argument('--seed', type=int, default=0, help='Random seed.')
parser.add_argument('--repeat', type=int, default=10, help='repeat experiment.')
parser.add_argument("-s", "--save", action="store_true", help="increase output verbosity")
parser.add_argument("-p", "--plot", action="store_true", help="plot the evaluation result")
args = parser.parse_args(); print(args)
torch.manual_seed(args.seed)

val_data = Continuum(root=args.data_root, name=args.dataset, data_type='val', download=True)
val_loader = Data.DataLoader(dataset=val_data, batch_size=args.batch_size, shuffle=False, collate_fn=citation_collate)
train_data = Continuum(root=args.data_root, name=args.dataset, data_type='train', download=True)    
train_loader = Data.DataLoader(dataset=test_data, batch_size=args.batch_size, shuffle=False, collate_fn=citation_collate)

total_result = []

def evaluate(result):
    evaluation_metrics = []
    net = Net(args, feat_len=train_data.feat_len, num_class=train_data.num_class).to(args.device)
    for i in range(train_data.num_class):
        incremental_data = Continuum(root=args.data_root, name=args.dataset, data_type='incremental', download=True, task_type = i)    
        incremental_Loader = Data.DataLoader(dataset=incremental_data, batch_size=args.batch_size, shuffle=True, collate_fn=citation_collate)
        for batch_idx, (inputs, targets, neighbor) in enumerate(incremental_Loader):
            inputs, targets = inputs.to(args.device), targets.to(args.device)
            neighbor = [item.to(args.device) for item in neighbor]
            net.observe(inputs, targets, neighbor)

        train_acc, val_acc, test_acc = performance_quiet(incremental_Loader, net), performance_quiet(val_loader, net), performance_quiet(train_loader, net)
        evaluation_metrics.append([i, incremental_data.__len__(), train_acc, val_acc, test_acc])
    result.append(evaluation_metrics)

for memory in [50,100,200,500,1000]:
    result = []
    args.memory_size = memory
    for ite in range(args.repeat):
        evaluate(result)
    total_result.append(result)
total_result = np.array(total_result)

if args.save:
    save_file = "doc/save-%f"%time.time()
    with open(save_file,"wb") as file:
        pickle.dump(total_result, file)
    np.savetxt(save_file+".txt",total_result[...,:,3].mean(axis=1),fmt="%2.3f")

if args.plot:
    tasks = np.arange(total_result.shape[2])
    plt.plot(tasks, total_result[...,:,3].mean(axis=1)[4],"k-^", label = "memory_size: 1000")
    plt.plot(tasks, total_result[...,:,3].mean(axis=1)[3],"r-o", label = "memory_size: 500")
    plt.plot(tasks, total_result[...,:,3].mean(axis=1)[2],"g-x", label = "memory_size: 200")
    plt.plot(tasks, total_result[...,:,3].mean(axis=1)[1],"b-+", label = "memory_size: 100")
    plt.plot(tasks, total_result[...,:,3].mean(axis=1)[0],"y-*", label = "memory_size: 50")

    # plt.plot(tasks, total_result[...,:,4].mean(axis=1),"b-o", label = "train_acc")
    plt.title("datasets: %s iteration: %s lr: %s batch_szie: %s"%\
              (args.dataset,args.iteration, args.lr, args.batch_size))
    plt.legend()
    plt.xlabel("task")
    plt.ylabel("accuracy (%)")
    plt.savefig("doc/plt.png")
