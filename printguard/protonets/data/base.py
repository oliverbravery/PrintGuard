"""
This code was adapted from the original implementation of Prototypical Networks for Few-Shot Learning.
Link: https://github.com/jakesnell/prototypical-networks
"""

import torch

def convert_dict(k, v):
    return { k: v }

class CudaTransform(object):
    def __init__(self):
        pass

    def __call__(self, data):
        if isinstance(data, torch.Tensor):
            return data.cuda()
        if not hasattr(data, 'items'):
            return data
        for k, v in data.items():
            if hasattr(v, 'cuda'):
                data[k] = v.cuda()
        return data

class MPSTransform(object):
    def __init__(self):
        pass

    def __call__(self, data):
        if isinstance(data, torch.Tensor):
            if torch.backends.mps.is_available():
                return data.to('mps')
            return data
        if not hasattr(data, 'items'):
            return data
        for k, v in data.items():
            if hasattr(v, 'to') and torch.backends.mps.is_available():
                data[k] = v.to('mps')
        return data

class SequentialBatchSampler(object):
    def __init__(self, n_classes):
        self.n_classes = n_classes

    def __len__(self):
        return self.n_classes

    def __iter__(self):
        for i in range(self.n_classes):
            yield torch.LongTensor([i])

class EpisodicBatchSampler(object):
    def __init__(self, n_classes, n_way, n_episodes):
        self.n_classes = n_classes
        self.n_way = n_way
        self.n_episodes = n_episodes

    def __len__(self):
        return self.n_episodes

    def __iter__(self):
        for i in range(self.n_episodes):
            yield torch.randperm(self.n_classes)[:self.n_way]
