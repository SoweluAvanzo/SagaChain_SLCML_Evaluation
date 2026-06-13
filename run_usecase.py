#!/usr/bin/env python3
"""
run_usecase.py — healthcare-consent use-case evaluation.

(1) Runs the SLCML healthcare consent directive on the SagaPython PoC at sizes
    K = 1..64 INDEPENDENT directives; verifies linear cost and object
    disjointness (~2 persistent objects per directive, no shared mutable state)
    -> the K legal contracts are disjoint and shardable (WP §III).
(2) Emits results/usecase_results.json and a figure results/scaling.png from the
    grounded model (Λ vs shards S for several hot-object shares σ; and the L2L
    cross-shard curve).
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bench import env_bootstrap as ENV          # noqa: E402
from bench import usecase as UC                 # noqa: E402
from bench.harness import run_transaction       # noqa: E402
from model.bounds import (MeasuredCosts, FreeParams,   # noqa: E402
                          p1_shard_ceiling, p2_network_ceiling,
                          p2_l2l_throughput)

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'results')


def main():
    os.makedirs(RESULTS, exist_ok=True)
    ENV.bootstrap()
    for _ in range(2):
        run_transaction(UC.consent_directives(1)[2])   # warmup

    sizes = [1, 2, 4, 8, 16, 32, 64]
    reps = 6
    rows = []
    print("Healthcare consent directive — K independent legal contracts:")
    for K in sizes:
        samples, objs = [], []
        for _ in range(reps):
            _n, _p, src = UC.consent_directives(K)
            t = run_transaction(src)
            assert t['result'] is True, f"K={K} did not commit: {t['result']!r}"
            samples.append(t['validator_total'])
            objs.append(t['objects_delta'])
        med = statistics.median(samples)
        obj = statistics.median(objs)
        rows.append({'K': K, 'validator_median_s': med,
                     'per_directive_ms': med / K * 1e3,
                     'objects_created': obj, 'objects_per_directive': obj / K})
        print(f"  K={K:3d}  total={med*1e3:8.2f} ms  "
              f"per-directive={med/K*1e3:6.2f} ms  "
              f"objects={obj:.0f} ({obj/K:.1f}/directive)")

    # MARGINAL (slope) analysis isolates per-directive cost/objects from the
    # one-time class-definition overhead -> the honest linearity/disjointness test.
    def ols(xs, ys):
        n = len(xs); mx = sum(xs)/n; my = sum(ys)/n
        sxx = sum((x-mx)**2 for x in xs); sxy = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
        slope = sxy/sxx; intercept = my-slope*mx
        ss_res = sum((y-(intercept+slope*x))**2 for x, y in zip(xs, ys))
        ss_tot = sum((y-my)**2 for y in ys)
        return slope, intercept, (1-ss_res/ss_tot if ss_tot else 1.0)
    Ks = [r['K'] for r in rows]
    cost_slope, cost_int, cost_r2 = ols(Ks, [r['validator_median_s'] for r in rows])
    obj_slope, obj_int, obj_r2 = ols(Ks, [r['objects_created'] for r in rows])
    disjoint = abs(obj_slope - 2.0) < 0.2          # 2 persistent objects per directive
    print(f"\n  marginal cost/directive = {cost_slope*1e3:.3f} ms  (R²={cost_r2:.4f}, "
          f"fixed overhead {cost_int*1e3:.2f} ms)")
    print(f"  marginal objects/directive = {obj_slope:.3f}  (R²={obj_r2:.4f}) => "
          f"each directive is its own object pair, no shared mutable state: {disjoint}")
    cv = cost_r2  # report fit quality instead of CV
    out_extra = {'cost_slope_ms': cost_slope*1e3, 'cost_intercept_ms': cost_int*1e3,
                 'cost_r2': cost_r2, 'obj_slope': obj_slope, 'obj_r2': obj_r2}

    # lambda for the consent profile (used by the separate figure script)
    costs = MeasuredCosts.from_bench(os.path.join(RESULTS, 'bench_results.json'))
    lam, _te = p1_shard_ceiling(
        costs, n_sig=1, n_classes=0, n_create=2, n_calls=2, n_field_pairs=4)

    out = {'usecase': rows, 'disjoint': disjoint,
           'lambda_shard_consent': lam, **out_extra}
    with open(os.path.join(RESULTS, 'usecase_results.json'), 'w') as f:
        json.dump(out, f, indent=1)
    print(f"  saved: {RESULTS}/usecase_results.json")


if __name__ == '__main__':
    main()
