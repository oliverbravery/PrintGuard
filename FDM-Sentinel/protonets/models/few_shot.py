"""
This code was adapted from the original implementation of Prototypical Networks for Few-Shot Learning.
Link: https://github.com/jakesnell/prototypical-networks
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models.shufflenetv2 import ShuffleNet_V2_X1_0_Weights, ShuffleNetV2
from torch.autograd import Variable

from protonets.models import register_model

from .utils import euclidean_dist

from torchvision import models

class Flatten(nn.Module):
    def __init__(self):
        super(Flatten, self).__init__()

    def forward(self, x):
        return x.view(x.size(0), -1)

class ShuffleNetV2Added(ShuffleNetV2):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.added = nn.Sequential(
            nn.Conv2d(in_channels=1024, out_channels=64, kernel_size=(1,1), stride=(1,1)),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.Conv2d(in_channels=64, out_channels=64, kernel_size=(1,1), stride=(1,1)),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True)
        )
        self.pooling = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
        )
        self.fc = nn.Linear(64, 2)


    def _forward_impl(self, x):
        x = self.conv1(x)
        x = self.maxpool(x)
        x = self.stage2(x)
        x = self.stage3(x)
        x = self.stage4(x)
        x = self.conv5(x)
        x = self.added(x)
        x = self.pooling(x)
        x = x.view(x.size(0), -1)
        x = self.fc(x) 
        return x

    def forward(self, x):
        return self._forward_impl(x)


class Protonet(nn.Module):
    def __init__(self, encoder):
        super(Protonet, self).__init__()
        
        self.encoder = encoder

    def loss(self, sample):
        xs = Variable(sample['xs']) # support
        xq = Variable(sample['xq']) # query

        n_class = xs.size(0)
        assert xq.size(0) == n_class
        n_support = xs.size(1)
        n_query = xq.size(1)

        target_inds = torch.arange(0, n_class).view(n_class, 1, 1).expand(n_class, n_query, 1).long()
        target_inds = Variable(target_inds, requires_grad=False)

        if xq.is_cuda:
            target_inds = target_inds.cuda()
        elif xq.is_mps:
            target_inds = target_inds.to('mps')

        x = torch.cat([xs.view(n_class * n_support, *xs.shape[2:]),
                       xq.view(n_class * n_query, *xq.shape[2:])], 0)

        z = self.encoder.forward(x)
        if z.ndim > 1:
            z_dim = z.size(-1)
        else:
            raise ValueError(f"Encoder output z has unexpected shape: {z.shape}")

        z_proto = z[:n_class*n_support].view(n_class, n_support, z_dim).mean(1)
        zq = z[n_class*n_support:]

        dists = euclidean_dist(zq, z_proto)

        log_p_y = F.log_softmax(-dists, dim=1).view(n_class, n_query, -1)

        loss_val = -log_p_y.gather(2, target_inds).squeeze().view(-1).mean()

        _, y_hat = log_p_y.max(2)
        acc_val = torch.eq(y_hat, target_inds.squeeze()).float().mean()
        y_true = target_inds.squeeze().view(-1)
        y_pred = y_hat.view(-1)
        return loss_val, {
            'loss': loss_val.item(),
            'acc': acc_val.item(),
            'y_true': y_true.cpu().numpy(),
            'y_pred': y_pred.cpu().numpy()
        }

def apply_dropout(model, dropout_prob):
    if hasattr(model, 'fc') and isinstance(model.fc, nn.Linear):
        num_features = model.fc.in_features
        original_output_features = model.fc.out_features
        fc_dropout_prob = dropout_prob.get("fc", 0.0)
        model.fc = nn.Sequential(
            nn.Linear(num_features, original_output_features),
            nn.Dropout(p=fc_dropout_prob)
        )
    elif hasattr(model, 'fc') and isinstance(model.fc, nn.Sequential):
        linear_layer_index = -1
        for i, layer in enumerate(model.fc):
            if isinstance(layer, nn.Linear):
                linear_layer_index = i
                break
        if linear_layer_index != -1:
            fc_dropout_prob = dropout_prob.get("fc", 0.0)
            model.fc.insert(linear_layer_index + 1, nn.Dropout(p=fc_dropout_prob))

    if hasattr(model, 'conv5'):
        new_conv5 = nn.Sequential()
        for name, layer in model.conv5.named_children():
            new_conv5.add_module(name, layer)
            if isinstance(layer, nn.ReLU):
                conv5_dropout_prob = dropout_prob.get("conv5", 0.0)
                if conv5_dropout_prob > 0:
                    new_conv5.add_module(f"{name}_Dropout2d", nn.Dropout2d(p=conv5_dropout_prob))
        model.conv5 = new_conv5

    stages_dropout_prob = dropout_prob.get("stages", {})
    for stage_name, dropout_rate in stages_dropout_prob.items():
        if hasattr(model, stage_name) and dropout_rate > 0:
            stage_module = getattr(model, stage_name)
            for i, inverted_residual in enumerate(stage_module):
                if hasattr(inverted_residual, 'branch1') and inverted_residual.branch1 is not None:
                    new_branch1 = nn.Sequential()
                    for j, layer in enumerate(inverted_residual.branch1):
                        new_branch1.add_module(f"{j}_{layer.__class__.__name__}", layer)
                        if isinstance(layer, nn.ReLU):
                            new_branch1.add_module(f"{j}_Dropout2d", nn.Dropout2d(p=dropout_rate))
                    inverted_residual.branch1 = new_branch1

                if hasattr(inverted_residual, 'branch2'):
                    new_branch2 = nn.Sequential()
                    for j, layer in enumerate(inverted_residual.branch2):
                        new_branch2.add_module(f"{j}_{layer.__class__.__name__}", layer)
                        if isinstance(layer, nn.ReLU):
                            new_branch2.add_module(f"{j}_Dropout2d", nn.Dropout2d(p=dropout_rate))
                    inverted_residual.branch2 = new_branch2
    return model

def load_shufflenet_from_weights(cnn_type, weights_path=None, dropout=False, dropout_prob=None):
    if dropout is False or dropout_prob is None:
        dropout_prob = {"fc": 0.0, "conv5": 0.0, "stages": {"stage3": 0.0, "stage4": 0.0}}
    model = None
    num_classes = 2
    if cnn_type == "ADDED":
        print("Instantiating ShuffleNetV2Added model")
        model = ShuffleNetV2Added(stages_repeats=[4, 8, 4], 
                                  stages_out_channels=[24, 116, 232, 464, 1024], 
                                  num_classes=num_classes) 
        if dropout:
            model = apply_dropout(model, dropout_prob)
        if weights_path:
            print(f"Loading weights for ADDED model from: {weights_path}")
            model.load_state_dict(torch.load(weights_path,
                                             map_location=torch.device('mps')),
                                  strict=False)
    else:
        weights = None
        if cnn_type == 'STANDARD':
            print("Instantiating Standard ShuffleNetV2 with ImageNet weights")
            weights = ShuffleNet_V2_X1_0_Weights.IMAGENET1K_V1
            model = models.shufflenet_v2_x1_0(weights=weights)
            num_features = model.fc.in_features
            model.fc = nn.Linear(num_features, num_classes)
        elif cnn_type == 'FT':
            print("Instantiating Standard ShuffleNetV2 for Fine-Tuning")
            model = models.shufflenet_v2_x1_0(weights=None)
            num_features = model.fc.in_features
            model.fc = nn.Linear(num_features, num_classes)
            if weights_path:
                print(f"Loading weights for FT model from: {weights_path}")
                model.load_state_dict(torch.load(weights_path,
                                                 map_location=torch.device('mps')),
                                      strict=False)
        else:
            raise ValueError(f"Unknown cnn_type: {cnn_type}")
        if dropout:
            model = apply_dropout(model, dropout_prob)
    return model

@register_model('protonet_conv')
def load_protonet_conv(**kwargs):
    dropout = kwargs.get('dropout', True)
    default_dropout_prob = {"fc": 0.0, "conv5": 0.0, "stages": {"stage3": 0.0, "stage4": 0.0}}
    dropout_prob = kwargs.get('dropout_prob', default_dropout_prob)
    cnn_type = kwargs.get('cnn_type', 'STANDARD')
    model = None
    weights_path = None

    if cnn_type == 'FT':
        weights_path = 'protonets/models/weights/model.pth'
        model = load_shufflenet_from_weights(cnn_type='FT',
                                         weights_path=weights_path,
                                         dropout=dropout,
                                         dropout_prob=dropout_prob)
    elif cnn_type == 'STANDARD':
        model = load_shufflenet_from_weights(cnn_type='STANDARD',
                                         weights_path=None,
                                         dropout=dropout,
                                         dropout_prob=dropout_prob)
    elif cnn_type == "ADDED":
        weights_path = 'protonets/models/weights/model_additional_convolutions.pth'
        model = load_shufflenet_from_weights(cnn_type='ADDED',
                                             weights_path=weights_path,
                                             dropout=dropout,
                                             dropout_prob=dropout_prob)
    else:
        raise ValueError(f"Unknown cnn_type provided to load_protonet_conv: {cnn_type}")
    if hasattr(model, 'fc'):
        model.fc = nn.Identity()
    final_encoder = nn.Sequential(
        model,
        nn.Flatten()
    )
    return Protonet(encoder=final_encoder)
