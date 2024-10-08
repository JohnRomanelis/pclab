# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/04_learner.ipynb.

# %% auto 0
__all__ = ['to_cpu', 'CancelFitException', 'CancelBatchException', 'CancelEpochException', 'Callback', 'run_cbs', 'with_cbs',
           'Learner', 'TrainLearner', 'TrainCB', 'LRFinderCB', 'MetricsCB', 'Accuracy', 'DeviceCB', 'ProgressCB',
           'BaseSchedCB', 'BatchSchedCB', 'EpochSchedCB', 'lr_find', 'WandBLogger']

# %% ../nbs/04_learner.ipynb 3
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.optim.lr_scheduler import ExponentialLR

from torcheval.metrics import Mean, MulticlassAccuracy

import fastcore.all as fc
from fastprogress import progress_bar,master_bar

import matplotlib.pyplot as plt

import math
import wandb

from copy import copy
from functools import partial
from operator import attrgetter
from collections.abc import Mapping

from .utils import def_device, to_device

# %% ../nbs/04_learner.ipynb 4
def to_cpu(x):
    if isinstance(x, Mapping): return {k:to_cpu(v) for k,v in x.items()}
    if isinstance(x, list): return [to_cpu(o) for o in x]
    if isinstance(x, tuple): return tuple(to_cpu(list(x)))
    res = x.detach().cpu()
    return res.float() if res.dtype==torch.float16 else res

# %% ../nbs/04_learner.ipynb 5
class CancelFitException(Exception): pass
class CancelBatchException(Exception): pass
class CancelEpochException(Exception): pass

# %% ../nbs/04_learner.ipynb 6
class Callback(): order = 0

# %% ../nbs/04_learner.ipynb 7
def run_cbs(cbs, method_nm, learn=None):
    for cb in sorted(cbs, key=attrgetter('order')):
        method = getattr(cb, method_nm, None)
        if method is not None: method(learn)       

# %% ../nbs/04_learner.ipynb 8
class with_cbs:
    def __init__(self, nm): self.nm = nm
    def __call__(self, f):
        def _f(o, *args, **kwargs):
            try:
                o.callback(f'before_{self.nm}')
                f(o, *args, **kwargs)
                o.callback(f'after_{self.nm}')
            except globals()[f'Cancel{self.nm.title()}Exception']: pass
            finally: o.callback(f'cleanup_{self.nm}')
        return _f

# %% ../nbs/04_learner.ipynb 9
class Learner():
    def __init__(self, model, dls=(0,), loss_func=F.mse_loss, lr=0.1, cbs=None, opt_func=optim.SGD):
        cbs = fc.L(cbs)
        fc.store_attr()

    @with_cbs('batch')
    def _one_batch(self):
        self.predict()
        self.callback('after_predict')
        self.get_loss()
        self.callback('after_loss')
        if self.training:
            self.backward()
            self.callback('after_backward')
            self.step()
            self.callback('after_step')
            self.zero_grad()

    @with_cbs('epoch')
    def _one_epoch(self):
        for self.iter,self.batch in enumerate(self.dl): self._one_batch()

    def one_epoch(self, training):
        self.model.train(training)
        self.dl = self.dls.train if training else self.dls.valid
        self._one_epoch()

    @with_cbs('fit')
    def _fit(self, train, valid):
        for self.epoch in self.epochs:
            if train: self.one_epoch(True)
            if valid: torch.no_grad()(self.one_epoch)(False)

    def fit(self, n_epochs=1, train=True, valid=True, cbs=None, lr=None):
        cbs = fc.L(cbs)
        # `add_cb` and `rm_cb` were added in lesson 18
        for cb in cbs: self.cbs.append(cb)
        try:
            self.n_epochs = n_epochs
            self.epochs = range(n_epochs)
            if lr is None: lr = self.lr
            if self.opt_func: self.opt = self.opt_func(self.model.parameters(), lr)
            self._fit(train, valid)
        finally:
            for cb in cbs: self.cbs.remove(cb)

    def __getattr__(self, name):
        if name in ('predict','get_loss','backward','step','zero_grad'): return partial(self.callback, name)
        raise AttributeError(name)

    def callback(self, method_nm): run_cbs(self.cbs, method_nm, self)
    
    @property
    def training(self): return self.model.training

# %% ../nbs/04_learner.ipynb 10
class TrainLearner(Learner):
    def predict(self): self.preds = self.model(self.batch[0])
    def get_loss(self): self.loss = self.loss_func(self.preds, self.batch[1])
    def backward(self): self.loss.backward()
    def step(self): self.opt.step()
    def zero_grad(self): self.opt.zero_grad()

# %% ../nbs/04_learner.ipynb 12
class TrainCB(Callback):
    def __init__(self, n_inp=1): self.n_inp = n_inp
    def predict(self, learn): learn.preds = learn.model(*learn.batch[:self.n_inp])
    def get_loss(self, learn): learn.loss = learn.loss_func(learn.preds, *learn.batch[self.n_inp:])
    def backward(self, learn): learn.loss.backward()
    def step(self, learn): learn.opt.step()
    def zero_grad(self, learn): learn.opt.zero_grad()

# %% ../nbs/04_learner.ipynb 13
class LRFinderCB(Callback):
    def __init__(self, gamma=1.3, max_mult=3): fc.store_attr()
    
    def before_fit(self, learn):
        self.sched = ExponentialLR(learn.opt, self.gamma)
        self.lrs,self.losses = [],[]
        self.min = math.inf

    def after_batch(self, learn):
        if not learn.training: raise CancelEpochException()
        self.lrs.append(learn.opt.param_groups[0]['lr'])
        loss = to_cpu(learn.loss)
        self.losses.append(loss)
        if loss < self.min: self.min = loss
        if math.isnan(loss) or (loss > self.min*self.max_mult):
            raise CancelFitException()
        self.sched.step()

    def cleanup_fit(self, learn):
        plt.plot(self.lrs, self.losses)
        plt.xscale('log')

# %% ../nbs/04_learner.ipynb 14
class MetricsCB(Callback):
    def __init__(self, *ms, **metrics):
        for o in ms: metrics[type(o).__name__] = o
        self.metrics = metrics
        self.all_metrics = copy(metrics)
        self.all_metrics['loss'] = self.loss = Mean()

    def _log(self, d): print(d)
    def before_fit(self, learn): learn.metrics = self
    def before_epoch(self, learn): [o.reset() for o in self.all_metrics.values()]

    def after_epoch(self, learn):
        log = {k:f'{v.compute():.3f}' for k,v in self.all_metrics.items()}
        log['epoch'] = learn.epoch
        log['train'] = 'train' if learn.model.training else 'eval'
        self._log(log)

    def after_batch(self, learn):
        x,y,*_ = to_cpu(learn.batch)
        for m in self.metrics.values(): m.update(to_cpu(learn.preds), y)
        self.loss.update(to_cpu(learn.loss), weight=len(x))

# %% ../nbs/04_learner.ipynb 15
class Accuracy(MulticlassAccuracy):
    """
    This class is a wrapper for torchval.metrics.MulticlassAccuracy.
    It receives as input the prediction of the model and the target and:
    - finds the index of the maximum value in the prediction - aka the class
    - squizes the target to remove the last dimension
    """
    def update(self, preds, target):
        # preds.shape = Bx40
        # target.shape = Bx1
        preds = torch.argmax(preds, dim=-1)
        super().update(preds, target.squeeze())

# %% ../nbs/04_learner.ipynb 16
class DeviceCB(Callback):
    def __init__(self, device=def_device): fc.store_attr()
    def before_fit(self, learn):
        if hasattr(learn.model, 'to'): learn.model.to(self.device)
    def before_batch(self, learn): learn.batch = to_device(learn.batch, device=self.device)

# %% ../nbs/04_learner.ipynb 17
class ProgressCB(Callback):
    order = MetricsCB.order + 1
    def __init__(self, plot=False): self.plot = plot
    def before_fit(self, learn):
        learn.epochs = self.mbar = master_bar(learn.epochs)
        self.first = True
        if hasattr(learn, 'metrics'): learn.metrics._log = self._log
        self.losses = []
        self.val_losses = []

    def _log(self, d):
        if self.first:
            self.mbar.write(list(d.keys()), table=True)
            self.first = False
        self.mbar.write(list(d.values()), table=True)
    
    def before_epoch(self, learn): learn.dl = progress_bar(learn.dl, leave=False, parent=self.mbar)
    def after_batch(self, learn):
        learn.dl.comment = f'{learn.loss:.3f}'
        if self.plot and hasattr(learn, 'metrics') and learn.training:
            self.losses.append(learn.loss.item())
            if self.val_losses: self.mbar.update_graph([[fc.L.range(self.losses), self.losses],[fc.L.range(learn.epoch).map(lambda x: (x+1)*len(learn.dls.train)), self.val_losses]])
            
    def after_epoch(self, learn):
        if not learn.training:
            if self.plot and hasattr(learn, 'metrics'): 
                self.val_losses.append(learn.metrics.all_metrics['loss'].compute())
                self.mbar.update_graph([[fc.L.range(self.losses), self.losses],[fc.L.range(learn.epoch+1).map(lambda x: (x+1)*len(learn.dls.train)), self.val_losses]])

# %% ../nbs/04_learner.ipynb 19
class BaseSchedCB(Callback):
    def __init__(self, sched): self.sched = sched
    def before_fit(self, learn): self.schedo = self.sched(learn.opt)
    def _step(self, learn):
        if learn.training: self.schedo.step()

# %% ../nbs/04_learner.ipynb 20
class BatchSchedCB(BaseSchedCB):
    def after_batch(self, learn): self._step(learn)

# %% ../nbs/04_learner.ipynb 21
class EpochSchedCB(BaseSchedCB):
    def after_epoch(self, learn): self._step(learn)

# %% ../nbs/04_learner.ipynb 23
@fc.patch
def lr_find(self:Learner, gamma=1.3, max_mult=3, start_lr=1e-5, max_epochs=10):
    self.fit(max_epochs, lr=start_lr, cbs=LRFinderCB(gamma=gamma, max_mult=max_mult))

# %% ../nbs/04_learner.ipynb 25
class WandBLogger(MetricsCB):

    def __init__(self, project, name, config, *ms, **metrics):
        super().__init__(*ms, **metrics)
        self.project = project
        self.name = name
        self.config = config

        self.run = wandb.init(project=self.project, name=self.name, config=self.config)
    
    def wandb_log(self, metrics, epoch, train):

        # log the metrics to wandb
        if train:
            self.run.log({f'train_{k}':v for k,v in metrics.items()})
            self.run.log({"epoch": epoch})
        else:
            self.run.log({f'eval_{k}':v for k,v in metrics.items()})


    def wandb_log_step_loss(self, loss):
        self.run.log({'loss': loss})


    def after_epoch(self, learn):
        # compute the values of the metrics
        metrics = {k:v.compute() for k,v in self.all_metrics.items()}
        
        # keep metrics with low acc for display purposes
        log = {k:f'{v:.3f}' for k,v in metrics.items()}
        log['epoch'] = learn.epoch
        log['train'] = 'train' if learn.model.training else 'eval'
        # self._log is ment to be replaced by other callbacks such as the `ProgressCB`
        self._log(log)

        # log the metrics to wandb
        self.wandb_log(metrics, learn.epoch, learn.model.training)
    
        
    def after_batch(self, learn):
        super().after_batch(learn)
        if learn.model.training:
            self.wandb_log_step_loss(learn.loss)
            
    def after_fit(self, learn):
        self.run.finish()
