import os
from functools import partial
import torch

from torchnet.dataset import TransformDataset, ListDataset
from torch.utils.data import random_split

from torchvision import transforms, datasets

from torchnet.transform import compose

from protonets.data.base import CudaTransform, MPSTransform, EpisodicBatchSampler, SequentialBatchSampler

DATA3D_DATA_DIR  = os.path.join(os.path.dirname(__file__), '../../data/')
DATA3D_CACHE = { }

def extract_episode(n_support, n_query, d):
    # data: N x C x H x W
    n_examples = d['data'].size(0)
    if n_query == -1:
        n_query = n_examples - n_support

    example_inds = torch.randperm(n_examples)[:(n_support+n_query)]
    support_inds = example_inds[:n_support]
    query_inds = example_inds[n_support:]

    xs = d['data'][support_inds]
    xq = d['data'][query_inds]

    support_idxs = [d['idxs'][i] for i in support_inds.tolist()]
    query_idxs = [d['idxs'][i] for i in query_inds.tolist()]
    return {
        'class': d['class'],
        'xs': xs,
        'xq': xq,
        'support_idxs': support_idxs,
        'query_idxs': query_idxs
    }
    
train_transform = transforms.Compose([
    transforms.RandomResizedCrop(224),
    transforms.Grayscale(num_output_channels=3),
    transforms.RandomHorizontalFlip(),
    transforms.RandomRotation(15),
    transforms.GaussianBlur(kernel_size=3),
    transforms.RandomAdjustSharpness(sharpness_factor=2),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]) 
])

val_test_transform = transforms.Compose([
    transforms.Resize(256),
    transforms.Grayscale(num_output_channels=3),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

def load_class_images(d):
    """Load all images for a given class."""
    if d['class'] not in DATA3D_CACHE:
        class_positions = [i for i, (_, label) in enumerate(d['dataset'])
                           if str(label) == d['class']]
        if not class_positions:
            raise ValueError(f"No images found for class {d['class']}")
        if hasattr(d['dataset'], 'indices'):
            full_idxs = [d['dataset'].indices[pos] for pos in class_positions]
        else:
            full_idxs = list(class_positions)
        class_data = []
        for pos in class_positions:
            img, _ = d['dataset'][pos]
            if d['transform']:
                img = d['transform'](img)
            class_data.append(img)
        DATA3D_CACHE[d['class']] = {'data': torch.stack(class_data), 'idxs': full_idxs}
    entry = DATA3D_CACHE[d['class']]
    return {'class': d['class'], 'data': entry['data'], 'idxs': entry['idxs']}

def load(opt):
    if opt['data.cuda']:
        train_transform.transforms.append(CudaTransform())
        val_test_transform.transforms.append(CudaTransform())
    elif opt.get('data.mps', False):
        train_transform.transforms.append(MPSTransform())
        val_test_transform.transforms.append(MPSTransform())
        
    settings = {
        'train': {
            'n_way': opt['data.way'],
            'n_support': opt['data.shot'],
            'n_query': opt['data.query'],
            'n_episodes': opt['data.train_episodes'],
            'transform': train_transform
        },
        'val': {
            'n_way': opt['data.test_way'] if opt['data.test_way'] != 0 else opt['data.way'],
            'n_support': opt['data.test_shot'] if opt['data.test_shot'] != 0 else opt['data.shot'],
            'n_query': opt['data.test_query'] if opt['data.test_query'] != 0 else opt['data.query'],
            'n_episodes': opt['data.test_episodes'],
            'transform': val_test_transform
        },
        'test': {
            'n_way': opt['data.test_way'] if opt['data.test_way'] != 0 else opt['data.way'],
            'n_support': opt['data.test_shot'] if opt['data.test_shot'] != 0 else opt['data.shot'],
            'n_query': opt['data.test_query'] if opt['data.test_query'] != 0 else opt['data.query'],
            'n_episodes': opt['data.test_episodes'],
            'transform': val_test_transform
        }
    }
    dataset_path = os.path.join(DATA3D_DATA_DIR, opt['data.dataset'])
    full_dataset = datasets.ImageFolder(dataset_path, transform=None)
    
    train_ratio = 0.7
    val_ratio = 0.15

    dataset_size = len(full_dataset)
    train_size = int(train_ratio * dataset_size)
    val_size = int(val_ratio * dataset_size)
    test_size = dataset_size - train_size - val_size

    train_dataset, val_dataset, test_dataset = random_split(
        full_dataset, [train_size, val_size, test_size],
        generator=torch.Generator().manual_seed(42)
    )
    
    ds = {
        'train': train_dataset,
        'val': val_dataset,
        'test': test_dataset
    }
    loaders = ds.copy()

    for split, setting in settings.items():
        dataset = ds[split]
        
        classes = set()
        for _, (_, label) in enumerate(dataset):
            classes.add(str(label))
        class_names = list(classes)
        
        if opt['data.sequential']:
            sampler = SequentialBatchSampler(len(class_names))
        else:
            sampler = EpisodicBatchSampler(len(class_names), setting['n_way'], setting['n_episodes'])
        
        list_ds = ListDataset(class_names)
        
        transforms_list = [
            (lambda x, dataset=dataset, transform=setting['transform']: {'class': x, 'dataset': dataset, 'transform': transform}),
            load_class_images,
            partial(extract_episode, setting['n_support'], setting['n_query'])
        ]
        
        if opt['data.cuda']:
            transforms_list.append(CudaTransform())
        elif opt.get('data.mps', False):
            transforms_list.append(MPSTransform())
            
        episode_transform = compose(transforms_list)
        t_ds = TransformDataset(list_ds, episode_transform)
        
        loaders[split] = torch.utils.data.DataLoader(t_ds, batch_sampler=sampler, num_workers=0)

    return loaders