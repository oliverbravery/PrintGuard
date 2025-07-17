"""
This code was adapted from the original implementation of Prototypical Networks for Few-Shot Learning.
Link: https://github.com/jakesnell/prototypical-networks
"""
import torch.nn as nn

class Protonet(nn.Module):
    def __init__(self, encoder):
        super(Protonet, self).__init__()
        self.encoder = encoder
