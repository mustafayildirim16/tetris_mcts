import numpy as np
import pickle 
import os
import sys
import glob
import argparse
import random
import gc
from util.Data import DataLoader, LossSaver
from math import ceil
eps = 0.001

"""
ARGS
"""
parser = argparse.ArgumentParser()
parser.add_argument('--backend', default='pytorch', type=str, help='DL backend')
parser.add_argument('--batch_size', default=32, type=int, help='Batch size (default:32)')
parser.add_argument('--cycle', default=-1, type=int, help='Cycle (default:-1)')
parser.add_argument('--data_paths', default=[], nargs='*', help='Training data paths (default: empty list)')
parser.add_argument('--eligibility_trace', default=False, action='store_true', help='Use eligibility trace')
parser.add_argument('--eligibility_trace_lambda', default=0.9, type=float, help='Lambda in eligibility trace (default:0.9)')
parser.add_argument('--epochs', default=10, type=int, help='Training epochs (default:10)')
parser.add_argument('--ewc', default=False, help='Elastic weight consolidation (default:False)', action='store_true')
parser.add_argument('--ewc_lambda', default=1, type=float, help='Elastic weight consolidation importance parameter(default:1)')
parser.add_argument('--last_nfiles', default=1, type=int, help='Use last n files in training only (default:1, -1 for all)')
parser.add_argument('--min_iters', default=2000, type=int, help='Min training iterations (default:2000, negative for unlimited)')
parser.add_argument('--max_iters', default=-1, type=int, help='Max training iterations (default:100000, negative for unlimited)')
parser.add_argument('--new', default=False, help='Create a new model instead of training the old one', action='store_true')
parser.add_argument('--validation', default=False, help='Validation set (default:False)', action='store_true')
parser.add_argument('--val_episodes', default=0, type=float, help='Number of validation episodes (default:0)')
parser.add_argument('--val_mode', default=0, type=int, help='Validation mode (0: random, 1:episodic, default:0)')
parser.add_argument('--val_set_size', default=0.05, type=float, help='Validation set size (fraction of total) (default:0.05)')
parser.add_argument('--val_set_size_max', default=-1, type=int, help='Maximum validation set size (default:-1, negative for unlimited)')
parser.add_argument('--val_total', default=25, type=int, help='Total number of validations (default:25)')
parser.add_argument('--save_loss', default=False, help='Save loss history', action='store_true')
parser.add_argument('--save_interval', default=100, type=int, help='Number of iterations between save_loss')
parser.add_argument('--shuffle', default=False, help='Shuffle dataset', action='store_true')
parser.add_argument('--target_normalization', default=False, help='Standardizes the targets', action='store_true')
parser.add_argument('--td', default=False, help='Temporal difference update', action='store_true')
parser.add_argument('--weighted_mse', default=False, help='Use weighted least square', action='store_true')
parser.add_argument('--weighted_mse_mode', default=0, type=int, help='0: inverse of variance, 1: number of visits')
args = parser.parse_args()

backend = args.backend
batch_size = args.batch_size
cycle = args.cycle
data_paths = args.data_paths
eligibility_trace = args.eligibility_trace
eligibility_trace_lambda = args.eligibility_trace_lambda
epochs = args.epochs
ewc = args.ewc
ewc_lambda = args.ewc_lambda
last_nfiles = args.last_nfiles
min_iters = args.min_iters
max_iters = args.max_iters
new = args.new
validation = args.validation
val_episodes = args.val_episodes
val_mode = args.val_mode
val_set_size = args.val_set_size
val_set_size_max = args.val_set_size_max
val_total = args.val_total
save_loss = args.save_loss
save_interval = args.save_interval
shuffle = args.shuffle
target_normalization = args.target_normalization
td = args.td
weighted_mse = args.weighted_mse
weighted_mse_mode = args.weighted_mse_mode

#========================
""" 
LOAD DATA 
"""
list_of_data = []
for path in data_paths:
    list_of_data += glob.glob(path) 
list_of_data.sort(key=os.path.getmtime)

if last_nfiles > 0:
    list_of_data = list_of_data[-last_nfiles:]

if len(list_of_data) == 0:
    exit()

loader = DataLoader(list_of_data)    

if td:
    if eligibility_trace:
        _child_stats = loader.child_stats
        n = _child_stats[:,0]
        q = _child_stats[:,3]

        _episode = loader.episode
        _score = loader.score
        _v = np.sum(n * q, axis=1) / np.sum(n, axis=1)
        values = np.zeros(_v.shape)
        for idx, ep in enumerate(_episode):
            idx_r = idx
            weight = 1.0
            _sum = 0
            _weight_sum = 0
            while idx_r < len(_episode) and _episode[idx_r] == _episode[idx] :
                _sum += weight * ( _score[idx_r] + _v[idx_r] - _score[idx] )
                _weight_sum += weight
                idx_r += 1
                weight *= eligibility_trace_lambda
            values[idx] = _sum / _weight_sum
        weights = np.ones(values.shape)
    else:
        values = loader.value
        variance = loader.variance
        if weighted_mse:
            if weighted_mse_mode == 0:
                weights = 1 / (variance + eps)
            elif weighted_mse_mode == 1:
                weights = np.sum(loader.child_stats[:, 0], axis=1)
                weights = weights / np.average(weights)
            elif weighted_mse_mode == 2:
                weights = np.sum(loader.child_stats[:, 0], axis=1)
                weights = weights / np.average(weights)
                weights = weights / (variance + eps)
        else:
            weights = np.ones(values.shape)
else:
    values = np.zeros((len(loader.score), ), dtype=np.float32)
    idx = 0
    while idx < len(loader.episode):
        for idx_end in range(idx, len(loader.episode)):
            if loader.episode[idx] != loader.episode[idx_end]:
                idx_end -= 1
                break
        ep_score = loader.score[idx_end]
        for _i in range(idx, idx_end+1):
            values[_i] = ep_score - loader.score[_i]
        idx = idx_end + 1
    variance = loader.variance 
    weights = np.ones(values.shape)

if backend == 'pytorch':
    states = np.expand_dims(loader.board, 1).astype(np.float32)
    policy = loader.policy.astype(np.float32)
    values = np.expand_dims(values, -1).astype(np.float32)
    variance = np.expand_dims(variance, -1).astype(np.float32)
    weights = np.expand_dims(weights, -1).astype(np.float32)
elif backend == 'tensorflow':
    states = np.expand_dims(np.stack(loader['board'].values),-1)
    policy = loader.policy
    values = np.expand_dims(values,-1)

#========================
"""
Shuffle
"""
if shuffle:
    indices = np.random.permutation(len(states))

    states = states[indices]
    policy = policy[indices]
    values = values[indices]
    variance = variance[indices]
    weights = weights[indices]
#=========================
"""
VALIDATION SET
"""
if validation:
    if val_mode == 0:
        if val_set_size <= 0: 
            t_idx = list(range(len(states)))
            v_idx = []
        elif val_set_size >= 1:
            t_idx = []
            v_idx = list(range(len(states)))
        else:
            n_val_data = int(len(states) * val_set_size)
            if val_set_size_max > 0:
                v_idx = np.random.choice(len(states), size=min(n_val_data, val_set_size_max), replace=False)
            else:
                v_idx = np.random.choice(len(states), size=n_val_data, replace=False)
            t_idx = [x for x in range(len(states)) if x not in v_idx] 
    elif val_mode == 1:
        if val_episodes <= 0:    
            t_idx = list(range(len(states)))
            v_idx = []
        else:
            v_idx = np.where(loader.episode < val_episodes + 1)
            if val_set_size_max > 0:
                idx = np.random.choice(len(v_idx[0]), size=min(len(v_idx[0]), val_set_size_max), replace=False)
                v_idx = (v_idx[0][idx],)
            t_idx = np.where(loader.episode >= val_episodes + 1)
            
    batch_val = [states[v_idx], values[v_idx], variance[v_idx], policy[v_idx], weights[v_idx]]

    batch_train = [states[t_idx], values[t_idx], variance[t_idx], policy[t_idx], weights[t_idx]]
else:
    batch_train = [states, values, variance, policy, weights]
n_data = len(batch_train[0])
#=========================
"""
TARGET NORMALIZATION
"""
if target_normalization:
    v_mean = batch_train[1].mean()
    v_std = batch_train[1].std()
    var_mean = batch_train[2].mean()
    var_std = batch_train[2].std()
    batch_train[1] = (batch_train[1] - v_mean) / v_std
    batch_train[2] = (batch_train[2] - var_mean) / var_std
    batch_val[1] = (batch_val[1] - v_mean) / v_std
    batch_val[2] = (batch_val[2] - var_mean) / var_std

#=========================
"""
MODEL SETUP
"""

if backend == 'pytorch':
    from model.model_pytorch import Model
    m = Model(weighted_mse=weighted_mse, ewc=ewc, ewc_lambda=ewc_lambda)
    if not new:
        m.load()
    train_step = lambda batch, step: m.train(batch)
    compute_loss = lambda batch: m.compute_loss(batch)
    scheduler_step = lambda val_loss: m.update_scheduler(val_loss)
    if target_normalization:
        m.v_mean = v_mean
        m.v_std = v_std
        m.var_mean = var_mean
        m.var_std = var_std
elif backend == 'tensorflow':
    from model.model import Model
    import tensorflow as tf
    sess = tf.Session()
    m = Model()
    if new:
        m.build_graph()
        sess.run(tf.global_variables_initializer())
    else:
        m.load(sess)
    train_step = lambda batch, step: m.train(sess,batch,step)
    compute_loss = lambda batch: m.compute_loss(sess,batch)
    scheduler_step = lambda val_loss: None
#=========================

iters_per_epoch = n_data//batch_size

iters = int(epochs * iters_per_epoch)

if max_iters >= 0:
    iters = int(min(iters, max_iters))

if min_iters >= 0:
    iters = int(max(iters, min_iters))

val_interval = iters // val_total + 1

if save_loss:
    #loss/loss_v/loss_var/loss_p
    hist_shape = (int(ceil(iters/save_interval)), 9)
    loss_history = np.empty(hist_shape)

#=========================
"""
TRAINING ITERATION
"""
loss_ma = 0
decay = 0.99
chunksize = 1000
loss_val, loss_val_v, loss_val_var, loss_val_p = 0, 0, 0, 0

for i in range(iters):
    idx = np.random.randint(n_data,size=batch_size)

    batch = [_arr[idx] for _arr in batch_train]

    loss, loss_v, loss_var, loss_p, loss_ewc = train_step(batch,i)
    
    loss_ma = decay * loss_ma + ( 1 - decay ) * loss
    
    if validation and i % val_interval == 0:
        loss_val, loss_val_v, loss_val_var, loss_val_p, loss_ewc = 0, 0, 0, 0, 0
        val_idx = 0
        while val_idx < len(batch_val[0]):
            if val_idx + chunksize < len(batch_val[0]):
                b_val = [_arr[val_idx:val_idx+chunksize] for _arr in batch_val] 
            else:
                b_val = [_arr[val_idx:] for _arr in batch_val]
            _l_val, _l_val_v, _l_val_var, _l_val_p, _l_ewc = compute_loss(b_val)
            loss_val += len(b_val[0]) * _l_val / len(batch_val[0])
            loss_val_v += len(b_val[0]) * _l_val_v / len(batch_val[0])
            loss_val_var += len(b_val[0]) * _l_val_var / len(batch_val[0])
            loss_val_p += len(b_val[0]) * _l_val_p / len(batch_val[0])
            loss_ewc += len(b_val[0]) * _l_ewc / len(batch_val[0])
            val_idx += chunksize
        scheduler_step(loss_val)
        
    sys.stdout.write('\riter:%d/%d loss: %.5f/%.5f'%(i,iters,loss_ma,loss_val))
    sys.stdout.flush()
        
    if save_loss and i % save_interval == 0:
        _idx = i // save_interval
        loss_history[_idx] = (loss, 
            loss_v, 
            loss_var,
            loss_p,
            loss_val,
            loss_val_v,
            loss_val_var,
            loss_val_p,
            loss_ewc)

if ewc:
    m.compute_fisher(batch_train)

sys.stdout.write('\n')
sys.stdout.flush()

if backend == 'tensorflow':
    m.save(sess)
elif backend == 'pytorch':
    m.save()


if save_loss:
    loss_saver = LossSaver(cycle)
    loss_saver.add(loss_history)
    loss_saver.close()

sys.stdout.write('\n')
sys.stdout.flush()
