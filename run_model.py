#!/usr/bin/env python3
"""
run_model.py — evaluate the grounded scalability model with measured costs,
run the parameter sweeps, and write results/REPORT.md.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model.bounds import (MeasuredCosts, FreeParams,            # noqa: E402
                          p1_shard_ceiling, p2_network_ceiling,
                          unified_comparison, p3_messages_per_block,
                          p4_security, p2_l2l_throughput)

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'results')
BENCH = os.path.join(RESULTS, 'bench_results.json')

US = 1e6
MS = 1e3


def main():
    costs = MeasuredCosts.from_bench(BENCH)

    lines = []

    def out(s=''):
        print(s)
        lines.append(s)

    out("# Grounded Scalability Model — Results")
    out()
    out("All formulas derive from the SagaChain whitepaper (WP §I–III) and "
        "measurements on the SagaPython runtime in this repository. "
        "Free parameters are explicit and swept. Absolute numbers "
        "characterize the Python prototype, not the architecture; "
        "cross-platform comparisons are made on *shape* only.")
    out()
    out("## 1. Measured marginal costs (SagaPython runtime, dev mode)")
    out()
    out("| Cost component | Value | Fit R² |")
    out("|---|---|---|")
    out(f"| Transaction pipeline floor | {costs.tx_floor*MS:.3f} ms | — |")
    out(f"| Define one CMI class | {costs.per_class*MS:.3f} ms | — |")
    out(f"| Create one persistent object | {costs.per_create*MS:.3f} ms | "
        f"{costs.fits['create']['r2']:.4f} |")
    out(f"| One CMI method call | {costs.per_method_call*US:.1f} µs | "
        f"{costs.fits['methods']['r2']:.4f} |")
    out(f"| One field write+read pair | {costs.per_field_pair*US:.1f} µs | "
        f"{costs.fits['fields']['r2']:.4f} |")
    out(f"| One object→object call | {costs.per_obj2obj_call*US:.1f} µs | "
        f"{costs.fits['obj2obj']['r2']:.4f} |")
    out(f"| Ed25519 signature verify | {costs.sig_verify*US:.1f} µs | micro |")
    out(f"| Persist one object (serialize+store) | "
        f"{costs.persist_object*US:.1f} µs | micro |")
    out()
    ratio = costs.per_obj2obj_call / costs.per_method_call
    out(f"Internal consistency: obj→obj call / method call = {ratio:.2f} "
        f"(dispatch-count prediction: 2.0).")
    out()

    # ---- P1 ----
    out("## 2. P1 — per-shard throughput ceiling")
    out()
    out("λ_shard < 1/t_exec. Validators re-execute every transaction (WP §I).")
    out()
    profiles = {
        'transfer-like (1 create, 2 calls)': dict(n_sig=1, n_classes=0,
                                                  n_create=1, n_calls=2,
                                                  n_field_pairs=2),
        'minimal (signature + floor only)': dict(n_sig=1, n_classes=0,
                                                 n_create=0, n_calls=0,
                                                 n_field_pairs=0, n_persist=0),
        'contract-deploy (1 class, 1 create)': dict(n_sig=1, n_classes=1,
                                                    n_create=1, n_calls=1,
                                                    n_field_pairs=1),
        'consent-like (2 creates, 4 calls)': dict(n_sig=1, n_classes=0,
                                                  n_create=2, n_calls=4,
                                                  n_field_pairs=4),
    }
    out("| Tx profile | t_exec | λ_shard ceiling (tx/s, this prototype) |")
    out("|---|---|---|")
    p1 = {}
    for name, prof in profiles.items():
        lam, te = p1_shard_ceiling(costs, **prof)
        p1[name] = {'t_exec_s': te, 'lambda_shard': lam}
        out(f"| {name} | {te*MS:.3f} ms | {lam:,.0f} |")
    out()

    lam_ref = p1['transfer-like (1 create, 2 calls)']['lambda_shard']

    # ---- P2 + comparison ----
    out("## 3. P2 — network ceiling and the unified comparison (shape)")
    out()
    out("Λ < min(S_eff·λ_shard, λ_shard/σ); identical form for all platforms, "
        "platform-specific S_eff (Ethereum 1, Solana ~cores, SagaChain S).")
    out()
    out("Sweep over shards S and hot-object share σ "
        "(transfer-like profile; χ=0 upper bound):")
    out()
    out("| S | σ=0 (fully disjoint) | σ=0.1% | σ=1% | σ=10% |")
    out("|---|---|---|---|---|")
    sweep_S = [1, 4, 16, 64, 256]
    sweep_sigma = [0.0, 0.001, 0.01, 0.10]
    p2_rows = []
    for S in sweep_S:
        row = []
        for sg in sweep_sigma:
            p = FreeParams(S=S, sigma=sg, chi=0.0)
            b = p2_network_ceiling(lam_ref, p)
            row.append(b['upper_bound_chi0'])
        p2_rows.append({'S': S, 'bounds': row})
        out(f"| {S} | " + " | ".join(f"{v:,.0f}" for v in row) + " |")
    out()
    out("Reading: scaling is linear in S until the hot-object term binds — "
        "at σ=1% the ceiling is 100·λ_shard regardless of S; at σ=10%, 10·λ_shard. "
        "The hot-object term is identical on Ethereum/Solana/SagaChain; the "
        "architectural difference is S_eff only (WP §III; Sealevel docs; "
        "Gasper spec).")
    out()
    out("Cross-shard sensitivity (S=64, σ=0.1%): Λ-bound vs (χ, c):")
    out()
    out("| χ \\ c | 2 | 4 | 8 |")
    out("|---|---|---|---|")
    p2_cross = []
    for chi in (0.01, 0.05, 0.20):
        row = []
        for c in (2.0, 4.0, 8.0):
            p = FreeParams(S=64, sigma=0.001, chi=chi, c_cross=c)
            row.append(p2_network_ceiling(lam_ref, p)['bound'])
        p2_cross.append({'chi': chi, 'bounds': row})
        out(f"| {chi:.0%} | " + " | ".join(f"{v:,.0f}" for v in row) + " |")
    out()
    out("c (cross-shard cost multiplier) is an EXPLICIT ASSUMPTION — no "
        "cross-shard protocol exists in the available documents.")
    out()

    # ---- P2'' L2L cross-shard (grounded) ----
    out("### 3b. Cross-shard via L2L (grounded in saganode: ~7 rounds / ≥3 blocks)")
    out()
    out("Cross-shard txs migrate account ownership through the L2L HotStuff "
        "coordinator — a single global serialization point. Throughput stays "
        "near-linear in S for low χ, then is bounded by the L2L coordinator as "
        "χ grows (S=64, σ=0.1%, L2L capacity = 0.5·λ_shard):")
    out()
    out("| χ | Λ-bound (tx/s) | L2L saturated? | cross-shard latency |")
    out("|---|---|---|---|")
    p2l2l = []
    for chi in (0.0, 0.05, 0.20, 0.50, 1.0):
        p = FreeParams(S=64, sigma=0.001, chi=chi)
        r = p2_l2l_throughput(lam_ref, p)
        p2l2l.append({'chi': chi, **{k: r[k] for k in
                      ('bound', 'l2l_bound_binds', 't_cross_block_intervals')}})
        out(f"| {chi:.0%} | {r['bound']:,.0f} | "
            f"{'yes' if r['l2l_bound_binds'] else 'no'} | "
            f"{r['t_cross_block_intervals']} block intervals (~{r['l2l_rounds']} msg rounds) |")
    out()
    out("The L2L coordinator is a second hot-spot: as χ→1 the system is bounded "
        "by Λ_L2L, not S·λ_shard. This is the sharpest code-grounded structural "
        "claim — SagaChain's sharding scales for low cross-shard workloads and "
        "is L2L-coordinator-bound otherwise.")
    out()

    # ---- P3 ----
    out("## 4. P3 — message complexity per shard per block (WP §I)")
    out()
    out("| n (nodes/shard) | BFT all-to-all msgs | total lower bound |")
    out("|---|---|---|")
    p3_rows = []
    for n in (4, 16, 64, 256):
        m = p3_messages_per_block(n)
        p3_rows.append({'n': n, **m})
        out(f"| {n} | {m['bft_all_to_all']:,} | {m['total_lower_bound']:,} |")
    out()
    out("Ω(n²) per shard per block — shard committee size is "
        "bandwidth-bounded; large validator sets per shard are not free.")
    out()

    # ---- P4 ----
    out("## 5. P4 — finality and security scaling (WP §I–II)")
    out()
    out("Local finality: exactly 2 blocks (pipelined validation).")
    out()
    out("Per-shard capture probability P[Byzantine > n/3] "
        "(VRF assignment from N=1000 nodes, adversary fraction β):")
    out()
    out("| n \\ β | 10% | 20% | 30% |")
    out("|---|---|---|---|")
    p4_rows = []
    for n in (16, 64, 256):
        row = []
        for beta in (0.10, 0.20, 0.30):
            p = FreeParams(n=n, beta=beta, N_total=1000)
            row.append(p4_security(p)['per_shard_capture_prob'])
        p4_rows.append({'n': n, 'probs': row})
        out(f"| {n} | " + " | ".join(f"{v:.2e}" for v in row) + " |")
    out()
    sec = p4_security(FreeParams(S=64))
    out(f"D-PoW pooling: long-term rewrite requires out-working H_net = Σ rᵢ/dᵢ "
        f"— a factor-S(={64}) gain over committee-only sharding, by WP eq. (2).")
    out(f"Caveat: {sec['caveat']}")
    out()

    # ---- honesty section ----
    out("## 6. Assumption ledger / threats to validity")
    out()
    for item in [
        "Measured costs are from the **Python prototype in dev mode** "
        "(in-memory store, no real network): valid for decomposition ratios "
        "and scaling shapes, NOT for absolute cross-platform TPS.",
        "Signature verification is not executed in the dev pipeline; it is "
        "added analytically (n_sig × measured Ed25519 verify).",
        "State persistence is added analytically (n_objects × measured "
        "serialize+store); real LevelDB disk I/O would be higher.",
        "Cross-shard atomicity has NO specified protocol; χ and c are "
        "assumptions, and the χ=0 column is the only unconditional bound.",
        "Consensus latency (PoW in critical path), block size and shard "
        "sizing are unspecified → no end-to-end latency/TPS prediction.",
        "No slashing/economic security is specified → economic comparison "
        "with Ethereum's slashable finality is out of scope.",
        "Ethereum/Solana reference forms come from their public specs, "
        "calibratable against live networks; SagaChain's cannot be "
        "calibrated against any deployment.",
    ]:
        out(f"- {item}")
    out()

    # save
    os.makedirs(RESULTS, exist_ok=True)
    model_out = {
        'costs': {k: getattr(costs, k) for k in
                  ('tx_floor', 'per_class', 'per_create', 'per_method_call',
                   'per_field_pair', 'per_obj2obj_call', 'sig_verify',
                   'persist_object')},
        'fits': costs.fits,
        'p1': p1,
        'p2_sweep_S': p2_rows,
        'p2_cross': p2_cross,
        'p2_l2l': p2l2l,
        'p3': p3_rows,
        'p4': p4_rows,
    }
    with open(os.path.join(RESULTS, 'model_results.json'), 'w') as f:
        json.dump(model_out, f, indent=1)
    with open(os.path.join(RESULTS, 'REPORT.md'), 'w') as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSaved: {RESULTS}/model_results.json and {RESULTS}/REPORT.md")


if __name__ == '__main__':
    main()
