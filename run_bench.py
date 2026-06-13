#!/usr/bin/env python3
"""
run_bench.py — measure t_exec and its decomposition on the SagaPython runtime.

Usage:
    python3 run_bench.py [--quick]

Outputs results/bench_results.json with:
  bootstrap time, per-workload per-size repeated stage timings + DB op counts,
  micro-benchmarks, and environment metadata.
"""
import argparse
import json
import os
import platform
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bench import env_bootstrap as ENV          # noqa: E402
from bench import workloads as W                # noqa: E402
from bench import microbench                    # noqa: E402
from bench.harness import run_transaction       # noqa: E402

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')


def summarize(samples):
    return {
        'n': len(samples),
        'median': statistics.median(samples),
        'mean': statistics.fmean(samples),
        'stdev': statistics.stdev(samples) if len(samples) > 1 else 0.0,
        'min': min(samples),
        'max': max(samples),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true',
                    help='small sizes/reps for a fast smoke run')
    args = ap.parse_args()

    if args.quick:
        sizes = [1, 4, 8]
        reps = 3
        warmup = 1
    else:
        sizes = [1, 2, 4, 8, 16, 32, 64]
        reps = 10
        warmup = 3

    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("Bootstrapping runtime (foundation classes)...")
    info = ENV.bootstrap()
    print(f"  bootstrap: {info['bootstrap_time_s']:.2f}s")

    # Warmup: first transactions pay import/JIT-ish costs
    for _ in range(warmup):
        run_transaction(W.minimal()[2])

    results = {
        'meta': {
            'python': sys.version,
            'platform': platform.platform(),
            'cpu_count': os.cpu_count(),
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'bootstrap_time_s': info['bootstrap_time_s'],
            'note': ('Development-mode runtime: in-memory state store '
                     '(CountingLevelDB), signature verification NOT in stage '
                     'timings (see microbench ed25519_verify).'),
        },
        'workloads': [],
        'microbench': None,
    }

    def record(name, params, source, reps):
        rows = []
        for _ in range(reps):
            t = run_transaction(source)
            if t['result'] is not True:
                raise RuntimeError(f"workload {name} {params} did not commit: "
                                   f"{t['result']!r}")
            rows.append(t)
        entry = {
            'name': name, 'params': params,
            'stages': {k: summarize([r[k] for r in rows])
                       for k in ('sign', 'hdr', 'tail', 'classes', 'body',
                                 'validator_total', 'wall_total')},
            'db': {k: summarize([r['db'][k] for r in rows])
                   for k in rows[0]['db']},
            'objects_delta': summarize([r['objects_delta'] for r in rows]),
            'script_bytes': rows[0]['script_bytes'],
        }
        results['workloads'].append(entry)
        v = entry['stages']['validator_total']['median']
        b = entry['stages']['body']['median']
        d = entry['db']
        print(f"  {name:8s} {str(params):12s} validator={v*1e3:8.2f} ms  "
              f"body={b*1e3:8.2f} ms  gets={d['gets']['median']:6.0f}  "
              f"puts={d['puts']['median']:5.0f}")

    print("\n[1/5] minimal")
    name, params, src = W.minimal()
    record(name, params, src, reps)

    print("[2/5] create(K)")
    for K in sizes:
        name, params, src = W.create_objects(K)
        record(name, params, src, reps)

    print("[3/5] methods(M)")
    for M in sizes:
        name, params, src = W.method_calls(M)
        record(name, params, src, reps)

    print("[4/5] fields(M)")
    for M in sizes:
        name, params, src = W.field_ops(M)
        record(name, params, src, reps)

    print("[5/5] obj2obj(M)")
    for M in sizes:
        name, params, src = W.obj_to_obj(M)
        record(name, params, src, reps)

    print("\nmicro-benchmarks...")
    results['microbench'] = microbench.run_all()
    for k, v in results['microbench'].items():
        print(f"  {k:22s} {v['median_s']*1e6:9.2f} µs")

    out = os.path.join(RESULTS_DIR, 'bench_results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=1)
    print(f"\nSaved: {out}")


if __name__ == '__main__':
    main()
