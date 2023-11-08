# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/Datasets/01_modelnet40.ipynb.

# %% auto 0
__all__ = ['m40_odered_labels', 'm40_cat2int', 'download', 'load_data', 'ModelNet40']

# %% ../../nbs/Datasets/01_modelnet40.ipynb 4
import os
import glob
import h5py
import numpy as np
from torch.utils.data import Dataset
from ..transforms import *

# %% ../../nbs/Datasets/01_modelnet40.ipynb 5
def download(path:str = None): # if path is None, it will download the data on the current dir, under the `data` subfolder.
    "A functions that downloads the ModelNet40 data, if not already downloaded, in the specified path"
    # adding the ability to use custom path
    if path == None:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        DATA_DIR = os.path.join(BASE_DIR, 'data')
        # Creating the path is it doesn't exist
        if not os.path.exists(DATA_DIR):
            os.mkdir(DATA_DIR)
    else:
        DATA_DIR = path
        
    if not os.path.exists(os.path.join(DATA_DIR, 'modelnet40_ply_hdf5_2048')):
        www = 'https://shapenet.cs.stanford.edu/media/modelnet40_ply_hdf5_2048.zip'
        zipfile = os.path.basename(www)
        os.system('wget %s; unzip %s' % (www, zipfile))
        os.system('mv %s %s' % (zipfile[:-4], DATA_DIR))
        os.system('rm %s' % (zipfile))

# %% ../../nbs/Datasets/01_modelnet40.ipynb 7
def load_data(partition:str, # `train` or `test` partition
              path:str=None):
    download(path)
    
    if path is None:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        DATA_DIR = os.path.join(BASE_DIR, 'data')
    else:
        DATA_DIR = path
        
    all_data = []
    all_label = []
    for h5_name in glob.glob(os.path.join(DATA_DIR, 'modelnet40_ply_hdf5_2048', 'ply_data_%s*.h5'%partition)):
        f = h5py.File(h5_name)
        data = f['data'][:].astype('float32')
        label = f['label'][:].astype('int64')
        f.close()
        all_data.append(data)
        all_label.append(label)
        
    all_data = np.concatenate(all_data, axis=0)
    all_label = np.concatenate(all_label, axis=0)
    
    return all_data, all_label

# %% ../../nbs/Datasets/01_modelnet40.ipynb 9
m40_odered_labels = 'airplane bathtub bed bench bookshelf bottle bowl car chair cone \
cup curtain desk door dresser plower_pot glass_box guitar keyboard lamp \
laptop mantel monitor night_stand person piano plant radio range_hood sink \
sofa stairs stool table tent toilet tv_stand vase wardrobe xbox'.split(' ')

m40_cat2int = {m40_odered_labels[i] : i for i in range(40)} 

# %% ../../nbs/Datasets/01_modelnet40.ipynb 13
class ModelNet40(Dataset):
    "A ModelNet40 class is necessary for loading and accessing the data, and it inherits from the torch.utils.Dataset class."
    def __init__(self, 
                 path:str,               # path of the dataset
                 num_points:int,         # number of points 
                 partition:str='train',  # which partition to use (`train` or `test`)
                 transforms=[],          # the transforms to apply on each sample
                 category=-1):           # select a specific category of the dataset either by index or by name. By default returns samples from all 40 categories. 
        assert partition in ['train', 'test'], "Partition should be either 'train' or 'test'"
        self.path, self.num_points, self.partition=path, num_points, partition
        self.transforms = transforms if isinstance(transforms, (tuple, list)) else [transforms]
        self.data, self.label = load_data(partition, path)
        
        if type(category) == str:
            assert category in m40_odered_labels, "Please select a valid category label"
            category = m40_cat2int[category]
        else:
            assert category in [-1] + list(range(40)), "Category index should be either -1 or a number in [0, 39]"
        
        if category != -1:
            mask = np.zeros_like(self.label).astype('bool')
            mask[self.label == category] = 1
            self.data = self.data[mask.squeeze(), ...]
            self.label = self.label[mask]
        
    def __len__(self):
        return len(self.data)
    
    def __getitem__(self, item):
        pointcloud = self.data[item][:self.num_points]
        label = self.label[item]
        for t in self.transforms:
            pointcloud = t(pointcloud)
        return pointcloud, label               