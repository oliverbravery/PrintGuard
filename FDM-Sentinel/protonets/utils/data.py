"""
This code was adapted from the original implementation of Prototypical Networks for Few-Shot Learning.
Link: https://github.com/jakesnell/prototypical-networks
"""

import protonets.data
import protonets.data.fault

def load(opt, splits):
    ds = protonets.data.fault.load(opt)
    return ds
