"""
des.py — discrete-event simulation of SagaChain account-local sharded execution.

Model (one server per shard + one L2L coordinator server; non-preemptive,
list-scheduling by task-ready time -> a valid FIFO flow-shop schedule):

  * S shards, each a single server that re-executes transactions serially at a
    deterministic service time t_exec (validators re-execute every tx; WP §I).
  * Accounts are assigned to shards uniformly at random (so the simulation
    exhibits real load imbalance, unlike the closed-form bound).
  * A transaction touches the designated HOT account with probability sigma -> it
    is pinned to the hot account's shard (shared mutable state serialises there).
  * A transaction is CROSS-SHARD with probability chi -> it first occupies the
    single L2L coordinator for t_l2l (account migration; saganode L2L ~7 rounds /
    >=3 block intervals) and is then executed on a shard.
  * The workload is saturating (M transactions released at t=0); throughput is
    M / makespan, where makespan is the last task completion.

The simulation INSTANTIATES the analytical bound min(S/t_exec, 1/(sigma*t_exec),
L2L) with stochastic routing; the realised throughput sits at or below the bound
because of finite-size load imbalance, which is exactly what a simulation adds
over the closed form. t_exec is taken from measurement; t_l2l = kappa * t_exec
encodes the L2L coordinator's relative capacity (round count grounded in code,
per-round cost assumed -> swept).
"""
import heapq
import random


def simulate_throughput(S, sigma, chi, t_exec, l2l_rho=1.0,
                        M=20000, seed=0):
    """Return realised throughput (tx/s) under a saturating batch of M txs.

    l2l_rho = L2L coordinator service rate in units of one shard's rate, so the
    coordinator's per-migration service time is t_exec / l2l_rho."""
    rng = random.Random(seed)
    t_l2l = t_exec / l2l_rho
    hot_shard = rng.randrange(S)

    # next-free time per server
    shard_free = [0.0] * S
    l2l_free = 0.0

    # ready-event heap: (ready_time, kind, job_id, shard_target)
    #   kind 0 = L2L stage (cross-shard), kind 1 = shard-execute stage
    heap = []
    for j in range(M):
        if sigma > 0 and rng.random() < sigma:
            target = hot_shard                      # contend on hot account
        else:
            target = rng.randrange(S)               # random account -> random shard
        if chi > 0 and rng.random() < chi:
            heapq.heappush(heap, (0.0, 0, j, target))   # needs L2L first
        else:
            heapq.heappush(heap, (0.0, 1, j, target))   # intra-shard

    makespan = 0.0
    while heap:
        ready, kind, j, target = heapq.heappop(heap)
        if kind == 0:                                # L2L coordinator stage
            start = max(ready, l2l_free)
            finish = start + t_l2l
            l2l_free = finish
            heapq.heappush(heap, (finish, 1, j, target))  # then execute on shard
        else:                                        # shard execution stage
            start = max(ready, shard_free[target])
            finish = start + t_exec
            shard_free[target] = finish
            if finish > makespan:
                makespan = finish

    return M / makespan if makespan > 0 else 0.0


def simulate_repeated(S, sigma, chi, t_exec, l2l_rho=1.0, M=20000,
                     seeds=10):
    vals = [simulate_throughput(S, sigma, chi, t_exec, l2l_rho, M, seed=s)
            for s in range(seeds)]
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1) if n > 1 else 0.0
    sd = var ** 0.5
    ci95 = 1.96 * sd / (n ** 0.5)
    return {'mean': mean, 'sd': sd, 'ci95': ci95, 'n': n,
            'min': min(vals), 'max': max(vals)}
