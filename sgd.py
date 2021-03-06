import ctf, time, random, sys
import numpy as np
from functools import reduce
import numpy.linalg as la
from ctf import random as crandom

glob_comm = ctf.comm()
import gzip
import shutil
import os

INDEX_STRING = "ijklmnopq"

def sparse_update(T, factors, Lambda, sizes, rank, stepSize, sample_rate, times, use_MTTKRP):
    starting_time = time.time()
    t_go = ctf.timer("SGD_getOmega")
    t_go.start()
    omega = getOmega(T)
    t_go.stop()
    dimension = len(sizes)
    indexes = INDEX_STRING[:dimension]
    R = ctf.tensor(copy=T) #ctf.tensor(tuple(sizes), sp = True)
    times[2] += time.time() - starting_time
    for i in range(dimension):
        starting_time = time.time()
        R.i(indexes) << -1.* ctf.TTTP(omega, factors).i(indexes)
        times[3] += time.time() - starting_time
        starting_time = time.time()
        times[4] += time.time() - starting_time
        starting_time = time.time()
        times[5] += time.time() - starting_time
        starting_time = time.time()
        t_ctr = ctf.timer("SGD_main_contraction")
        t_ctr.start()
        if use_MTTKRP:
            new_fi = (1- stepSize * 2 * Lambda * sample_rate)*factors[i]
            ctf.MTTKRP(R, factors, i)
            stepSize*factors[i].i("ir") << new_fi.i("ir")
        else:
            tup_list = [factors[i].i(indexes[i] + "r") for i in range(dimension)]
            Hterm = reduce(lambda x, y: x * y, tup_list[:i] + tup_list[i + 1:])
            (1- stepSize * 2 * Lambda * sample_rate)*factors[i].i(indexes[i] + "r") << stepSize * Hterm * R.i(indexes)
        t_ctr.stop()
        times[6] += time.time() - starting_time
        if i < dimension - 1:
            R = ctf.tensor(copy=T)

def sparse_SGD(T, U, V, W, Lambda, omega, I, J, K, r, stepSize, sample_rate, num_iter, errThresh, time_limit, work_cycle, use_MTTKRP):
    times = [0 for i in range(7)]

    iteration_count = 0
    total_count = 0
    R = ctf.tensor((I, J, K), sp=T.sp)
    if T.sp == True:
        nnz_tot = T.nnz_tot
    else:
        nnz_tot = ctf.sum(omega)
    start_time = time.time()
    starting_time = time.time()
    dtime = 0
    R.i("ijk") << T.i("ijk") - ctf.TTTP(omega, [U, V, W]).i("ijk")
    curr_err_norm = ctf.vecnorm(R) + (ctf.vecnorm(U) + ctf.vecnorm(V) + ctf.vecnorm(W)) * Lambda
    times[0] += time.time() - starting_time
    norm = [curr_err_norm]
    step = stepSize * 0.5
    t_obj_calc = 0.

    while iteration_count < num_iter and time.time() - start_time - t_obj_calc < time_limit:
        iteration_count += 1
        starting_time = time.time()
        sampled_T = T.copy()
        sampled_T.sample(sample_rate)
        times[1] += time.time() - starting_time

        sparse_update(sampled_T, [U, V, W], Lambda, [I, J, K], r, stepSize * 0.5 + step, sample_rate, times, use_MTTKRP)
        #step *= 0.99
        sampled_T.set_zero()

        if iteration_count % work_cycle == 0:
            duration = time.time() - start_time - t_obj_calc
            t_b_obj = time.time()
            total_count += 1
            R.set_zero()
            R.i("ijk") << T.i("ijk") - ctf.TTTP(omega, [U, V, W]).i("ijk")
            diff_norm = ctf.vecnorm(R)
            RMSE = diff_norm/(nnz_tot**.5)
            next_err_norm = diff_norm + (ctf.vecnorm(U) + ctf.vecnorm(V) + ctf.vecnorm(W)) * Lambda
            if glob_comm.rank() == 0:
                print('Objective after',duration,'seconds (',iteration_count,'iterations) is: {}'.format(next_err_norm))
                print('RMSE after',duration,'seconds (',iteration_count,'iterations) is: {}'.format(RMSE))
            t_obj_calc += time.time() - t_b_obj

            if abs(curr_err_norm - next_err_norm) < errThresh:
                break

            curr_err_norm = next_err_norm
            norm.append(curr_err_norm)

    duration = time.time() - start_time - t_obj_calc
    if ctf.comm().rank() == 0:
        print('SGD amortized seconds per sweep: {}'.format(duration/(iteration_count*sample_rate)))
        print("Time/SGD iteration: {}".format(duration/iteration_count))
    return norm

def getOmega(T):
    [inds, data] = T.read_local_nnz()
    data[:] = 1.
    Omega = ctf.tensor(T.shape,sp=True)
    Omega.write(inds,data)
    return Omega

