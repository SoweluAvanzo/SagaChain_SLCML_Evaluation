"""
bounds.py — the grounded analytical scalability model (P1-P4).

Every formula here is derivable from 100%-sure sources:
  [WP-I]   SagaChain Technical Whitepaper §I  (main loop: 3f+1 nodes, 2f+1
           votes, all-to-all validation messages, PoW in critical path,
           pipelined validation -> 2-block local finality)
  [WP-II]  §II (D-PoW: H_i = r_i/d_i, H_net = sum_i H_i, max-cumulative-
           hashpower fork choice)
  [WP-III] §III (account-local state; disjoint-account transactions execute
           in parallel on separate shards; cross-shard data dependence is a
           point of serialization; Amdahl's Law)
  [CODE]   marginal execution costs measured on the SagaPython runtime
           (results/bench_results.json)

Anything NOT derivable from those sources enters only as an explicit,
sweepable free parameter (FreeParams).
"""
import json
import math
from dataclasses import dataclass, field


# --------------------------------------------------------------------------- cost fitting
def _ols(xs, ys):
    """Least-squares slope/intercept with R^2."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return slope, intercept, r2


@dataclass
class MeasuredCosts:
    """Marginal validator-side costs of the SagaPython runtime [CODE].

    All in seconds. These characterize the *prototype implementation*;
    they are used for decomposition ratios and workload-profile t_exec,
    never for cross-platform absolute-TPS claims.
    """
    tx_floor: float            # pipeline floor (minimal tx, validator stages)
    per_class: float           # define one CMI class (intercept over floor)
    per_create: float          # instantiate one persistent object
    per_method_call: float     # one CMI method dispatch
    per_field_pair: float      # one field write+read pair
    per_obj2obj_call: float    # one object-to-object call (2 dispatches)
    sig_verify: float          # Ed25519 verify (validator pays per signature)
    persist_object: float      # serialize+store one median-size object
    fits: dict = field(default_factory=dict)

    @classmethod
    def from_bench(cls, path):
        with open(path) as f:
            res = json.load(f)
        by = {}
        for wl in res['workloads']:
            by.setdefault(wl['name'], []).append(wl)

        floor = by['minimal'][0]['stages']['validator_total']['median']

        def fit(name, key):
            pts = [(wl['params'][key], wl['stages']['validator_total']['median'])
                   for wl in by[name]]
            pts.sort()
            slope, intercept, r2 = _ols([p[0] for p in pts], [p[1] for p in pts])
            return slope, intercept, r2

        c_create, i_create, r2_c = fit('create', 'K')
        c_method, i_method, r2_m = fit('methods', 'M')
        c_field, i_field, r2_f = fit('fields', 'M')
        c_o2o, i_o2o, r2_o = fit('obj2obj', 'M')

        mb = res['microbench']
        return cls(
            tx_floor=floor,
            per_class=max(i_method - floor - c_create, 0.0),
            per_create=c_create,
            per_method_call=c_method,
            per_field_pair=c_field,
            per_obj2obj_call=c_o2o,
            sig_verify=mb['ed25519_verify']['median_s'],
            persist_object=mb['persist_object']['median_s'],
            fits={'create': {'slope': c_create, 'intercept': i_create, 'r2': r2_c},
                  'methods': {'slope': c_method, 'intercept': i_method, 'r2': r2_m},
                  'fields': {'slope': c_field, 'intercept': i_field, 'r2': r2_f},
                  'obj2obj': {'slope': c_o2o, 'intercept': i_o2o, 'r2': r2_o}},
        )

    def t_exec(self, n_sig=1, n_classes=0, n_create=1, n_calls=2,
               n_field_pairs=2, n_persist=None):
        """Validator-side cost of one transaction with the given profile."""
        if n_persist is None:
            n_persist = n_create
        return (self.tx_floor
                + n_sig * self.sig_verify
                + n_classes * self.per_class
                + n_create * self.per_create
                + n_calls * self.per_method_call
                + n_field_pairs * self.per_field_pair
                + n_persist * self.persist_object)


# --------------------------------------------------------------------------- free parameters
@dataclass
class FreeParams:
    """Everything the available documents do NOT fix. Sweep these.

    Implemented operating point from saganode config (nodespershardcommittee=21,
    posbftcount=powbftcount=15) → n=21, q=15 (the 2f+1-of-3f+1 shape, f=7)."""
    S: int = 16                 # number of shards               [unspecified]
    n: int = 21                 # nodes per shard (3f+1)         [code: 21]
    q: int = 15                 # BFT quorum (2f+1)              [code: 15]
    chi: float = 0.05           # cross-shard tx fraction        [workload]
    c_cross: float = 4.0        # cross-shard cost multiplier    [now grounded via L2L]
    sigma: float = 0.01         # busiest-object workload share  [workload]
    beta: float = 0.20          # global adversary fraction      [assumption]
    N_total: int = 1000         # total nodes in network         [unspecified]
    block_rate: float = 1.0     # blocks/s per shard r_i         [unspecified]
    pow_difficulty: float = 1.0 # d_i (smaller = more work)      [unspecified]
    # L2L cross-shard layer (round count GROUNDED from saganode; coordinator
    # throughput per second is NOT measurable -- expressed relative to one shard):
    l2l_rounds: int = 7         # HotStuff message rounds / cross-shard cycle [code]
    l2l_block_intervals: int = 3  # >= block intervals per L2L cycle [code]
    l2l_rho: float = 1.0        # L2L coordinator rate mu_L2L in units of lambda_shard
                                #   (one shard's worth of migration capacity) [swept]


# --------------------------------------------------------------------------- P1, P2
def p1_shard_ceiling(costs: MeasuredCosts, **tx_profile):
    """P1 [WP-I + CODE]: per-shard throughput < 1/t_exec.
    Validators re-execute every transaction; per-shard processing of one
    object's state is sequential."""
    te = costs.t_exec(**tx_profile)
    return 1.0 / te, te


def p2_network_ceiling(lam_shard, p: FreeParams):
    """P2 [WP-III]: Lambda < min( S_parallel_term , hot-object term ).
    Cross-shard penalty (chi, c_cross) is an EXPLICIT ASSUMPTION: no protocol
    exists in the documents; c_cross can only make things worse, so the
    chi=0 value remains a valid upper bound."""
    parallel = p.S * lam_shard / (1.0 + p.chi * (p.c_cross - 1.0))
    hot = lam_shard / p.sigma if p.sigma > 0 else float('inf')
    return {'parallel_term': parallel, 'hot_object_term': hot,
            'bound': min(parallel, hot),
            'upper_bound_chi0': min(p.S * lam_shard, hot)}


def p2_l2l_throughput(lam_shard, p: FreeParams):
    """(P2'') L2L cross-shard bound, corrected to the bottleneck form after the
    discrete-event simulation. Every cross-shard transaction must pass the single
    L2L HotStuff coordinator (saganode), which migrates account ownership; the
    coordinator is therefore a global serial server. If its service rate is
    mu_L2L and a fraction chi of all transactions are cross-shard, then
    chi*Lambda <= mu_L2L, i.e. Lambda <= mu_L2L/chi. Hence

        Lambda < min( S*lambda_shard,  lambda_shard/sigma,  mu_L2L/chi ),

    with mu_L2L = rho * lambda_shard (rho = coordinator capacity in units of one
    shard; the round count is grounded in code, the absolute rate is swept).
    Even rho=1 (a coordinator as fast as one shard) caps cross-shard-heavy
    workloads, so the S-shard speed-up is realised only for small chi."""
    mu_l2l = p.l2l_rho * lam_shard
    parallel = p.S * lam_shard
    hot = lam_shard / p.sigma if p.sigma > 0 else float('inf')
    l2l = mu_l2l / p.chi if p.chi > 0 else float('inf')
    t_cross_blocks = p.l2l_block_intervals + 2
    return {'parallel_term': parallel, 'hot_object_term': hot,
            'l2l_term': l2l, 'bound': min(parallel, hot, l2l),
            'l2l_bound_binds': l2l < min(parallel, hot),
            't_cross_block_intervals': t_cross_blocks,
            'l2l_rounds': p.l2l_rounds}


def unified_comparison(lam_shard, p: FreeParams, cores_solana=32):
    """Lambda_platform < min(S_eff/t_exec, 1/(sigma*t_exec)) — identical form,
    platform-specific S_eff. Shapes are implementation-independent."""
    hot = lam_shard / p.sigma
    return {
        'ethereum': {'S_eff': 1, 'bound': min(1 * lam_shard, hot)},
        'solana': {'S_eff': cores_solana,
                   'bound': min(cores_solana * lam_shard, hot)},
        'sagachain': {'S_eff': p.S, 'bound': min(p.S * lam_shard, hot)},
        'hot_object_term': hot,
    }


# --------------------------------------------------------------------------- P3
def p3_messages_per_block(n):
    """P3 [WP-I]: message complexity per shard per block.
    Lower bound: leader multicast O(n) + all-to-all validation Omega(n^2)
    + PoW signature rounds (two rounds, broadcast) + gossip O(n)."""
    return {'propose': n,
            'bft_all_to_all': n * (n - 1),
            'pow_sig_rounds': 2 * n * (n - 1),     # upper-bound style; >= n(n-1)
            'gossip': n,
            'total_lower_bound': n + n * (n - 1) + n,
            'scaling': 'Omega(n^2) per shard per block'}


# --------------------------------------------------------------------------- P4
def _hyper_tail_ge(N, K, m, kmin):
    """P[X >= kmin], X ~ Hypergeometric(N, K, m)."""
    def C(a, b):
        if b < 0 or b > a:
            return 0
        return math.comb(a, b)
    denom = C(N, m)
    return sum(C(K, k) * C(N - K, m - k) for k in range(kmin, m + 1)) / denom


def p4_security(p: FreeParams, depth_blocks=100):
    """P4 [WP-I, WP-II]:
      - per-shard BFT safety: P[Byzantine > n/3] under VRF assignment
        (hypergeometric tail) — per assignment epoch;
      - D-PoW long-term: rewrite work > H_net * tau (pooled across shards);
      - local finality: exactly 2 blocks (pipelined validation)."""
    K_adv = int(p.beta * p.N_total)
    kmin = p.n // 3 + 1
    p_capture = _hyper_tail_ge(p.N_total, K_adv, p.n, kmin)

    H_i = p.block_rate / p.pow_difficulty            # WP eq. (1)
    H_net = p.S * H_i                                # WP eq. (2), equal shards
    tau = depth_blocks / p.block_rate
    return {
        'finality_blocks_local': 2,
        'per_shard_capture_prob': p_capture,
        'committee_only_equivalent': 'security ~ single shard H_i',
        'H_shard': H_i,
        'H_net': H_net,
        'rewrite_work_required': H_net * tau,
        'pooling_gain_vs_committee_sharding': p.S,
        'caveat': ('PoW weight attests expenditure, not state validity; '
                   'no fraud-proof/data-availability mechanism is specified '
                   'in the available documents.'),
    }
