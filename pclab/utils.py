# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_utils.ipynb.

# %% auto 0
__all__ = ['pc_to_o3d', 'quick_vis', 'cal_loss']

# %% ../nbs/00_utils.ipynb 2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import open3d as o3d

# %% ../nbs/00_utils.ipynb 3
def pc_to_o3d(pc): # point cloud as np.array or torch.tensor
    "turn a point cloud, represented as a np.array or torch.tensor to an [Open3D.geometry.PointCloud](http://www.open3d.org/docs/0.16.0/python_api/open3d.geometry.PointCloud.html)"
    pc = o3d.geometry.PointCloud(
            o3d.utility.Vector3dVector(pc)
    )
    return pc

# %% ../nbs/00_utils.ipynb 4
def quick_vis(pc): # point cloud as np.array or torch.tensor
    pc = pc_to_o3d(pc)
    o3d.visualization.draw_geometries([pc])

# %% ../nbs/00_utils.ipynb 7
def cal_loss(pred, gold, smoothing=True):
    ''' Calculate cross entropy loss, apply label smoothing if needed. '''

    gold = gold.contiguous().view(-1)

    if smoothing:
        eps = 0.2
        n_class = pred.size(1)

        one_hot = torch.zeros_like(pred).scatter(1, gold.view(-1, 1), 1)
        one_hot = one_hot * (1 - eps) + (1 - one_hot) * eps / (n_class - 1)
        log_prb = F.log_softmax(pred, dim=1)

        loss = -(one_hot * log_prb).sum(dim=1).mean()
    else:
        loss = F.cross_entropy(pred, gold, reduction='mean')

    return loss
