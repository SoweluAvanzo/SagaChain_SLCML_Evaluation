#!/usr/bin/env python3
"""
run_sim.py — run the discrete-event simulation sweeps and render the figure.

Uses t_exec measured on the SagaPython runtime (consent-directive profile) and
the L2L coordinator relative-cost kappa from the model. Produces:
  results/sim_results.json   (sweep data, mean +/- 95% CI over seeds)
  results/scaling.pdf/.png   (simulation points + analytical-bound reference)
No SagaPython runtime needed (pure model + DES), so numpy/matplotlib import
cleanly here.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'results')

from model.bounds import (MeasuredCosts, FreeParams,        # noqa: E402
                          p1_shard_ceiling, p2_network_ceiling,
                          p2_l2l_throughput)
from sim.des import simulate_repeated                       # noqa: E402

SEEDS = 12
M = 20000
RHOS = [1.0, 4.0]    # L2L coordinator speed in units of one shard (swept)


def main():
    costs = MeasuredCosts.from_bench(os.path.join(RESULTS, 'bench_results.json'))
    lam, t_exec = p1_shard_ceiling(
        costs, n_sig=1, n_classes=0, n_create=2, n_calls=2, n_field_pairs=4)
    print(f"t_exec (consent profile) = {t_exec*1e3:.3f} ms  "
          f"-> lambda_shard = {lam:.0f} tx/s")

    out = {'t_exec_s': t_exec, 'lambda_shard': lam, 'rhos': RHOS,
           'seeds': SEEDS, 'M': M, 'panel_a': [], 'panel_b': []}

    # ---- panel (a): throughput vs shards S, for several hot-object shares ----
    Svals = [1, 2, 4, 8, 16, 32, 64, 128, 256]
    print("\n(a) throughput vs S (sim mean +/- 95% CI; bound in []):")
    for sg in (0.0, 0.001, 0.01, 0.1):
        row = {'sigma': sg, 'S': [], 'sim_mean': [], 'sim_ci': [], 'bound': []}
        for S in Svals:
            r = simulate_repeated(S, sg, 0.0, t_exec, 1.0, M, SEEDS)
            b = p2_network_ceiling(lam, FreeParams(S=S, sigma=sg, chi=0.0))['upper_bound_chi0']
            row['S'].append(S); row['sim_mean'].append(r['mean'])
            row['sim_ci'].append(r['ci95']); row['bound'].append(b)
        out['panel_a'].append(row)
        s_lbl = 'σ=0' if sg == 0 else f'σ={sg}'
        print(f"  {s_lbl:8s} S=256: sim={row['sim_mean'][-1]:,.0f}"
              f"±{row['sim_ci'][-1]:,.0f}  bound=[{row['bound'][-1]:,.0f}]")

    # ---- panel (b): throughput vs cross-shard fraction chi, S=64, swept rho ----
    print("\n(b) throughput vs chi at S=64 (L2L coordinator bottleneck):")
    chis = [i/40 for i in range(41)]
    for rho in RHOS:
        row = {'rho': rho, 'S': 64, 'sigma': 0.001, 'chi': [],
               'sim_mean': [], 'sim_ci': [], 'bound': []}
        for c in chis:
            r = simulate_repeated(64, 0.001, c, t_exec, rho, M, SEEDS)
            b = p2_l2l_throughput(lam, FreeParams(S=64, sigma=0.001, chi=c,
                                                  l2l_rho=rho))['bound']
            row['chi'].append(c); row['sim_mean'].append(r['mean'])
            row['sim_ci'].append(r['ci95']); row['bound'].append(b)
        out['panel_b'].append(row)
        for c in (0.0, 0.05, 0.25):
            i = row['chi'].index(c) if c in row['chi'] else min(
                range(len(row['chi'])), key=lambda k: abs(row['chi'][k]-c))
            print(f"  rho={rho:g} chi={row['chi'][i]:.0%}: "
                  f"sim={row['sim_mean'][i]:,.0f}  bound=[{row['bound'][i]:,.0f}]")

    with open(os.path.join(RESULTS, 'sim_results.json'), 'w') as f:
        json.dump(out, f, indent=1)

    # ---- figure ----
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.7))

    markers = {0.0: 'o', 0.001: 's', 0.01: '^', 0.1: 'd'}
    for row in out['panel_a']:
        sg = row['sigma']
        lbl = r'$\sigma=0$' if sg == 0 else rf'$\sigma={sg:g}$'
        ax[0].errorbar(row['S'], row['sim_mean'], yerr=row['sim_ci'],
                       marker=markers[sg], ms=3.5, lw=1.1, capsize=2, label=lbl)
        ax[0].loglog(row['S'], row['bound'], ls=':', lw=0.8, color='gray')
    ax[0].set_xscale('log'); ax[0].set_yscale('log')
    ax[0].axhline(lam, color='gray', ls='--', lw=0.8)
    ax[0].annotate(r'$S_{\mathrm{eff}}{=}1$ (single-state)', (1.1, lam*1.3),
                   fontsize=6.5, color='gray')
    ax[0].set_xlabel(r'shards $S\;(=S_{\mathrm{eff}})$', fontsize=8)
    ax[0].set_ylabel(r'throughput $\Lambda$ (tx/s)', fontsize=8)
    ax[0].set_title('(a) Simulated throughput vs. hot-object share', fontsize=8)
    ax[0].legend(fontsize=6.5, loc='lower right', ncol=2)
    ax[0].grid(True, which='both', ls=':', alpha=0.3)
    ax[0].tick_params(labelsize=7)

    colors = {1.0: 'C3', 4.0: 'C0'}
    for b in out['panel_b']:
        rho = b['rho']
        ax[1].errorbar([c*100 for c in b['chi']], b['sim_mean'], yerr=b['sim_ci'],
                       color=colors.get(rho, 'C2'), lw=1.3, marker='o', ms=2.0,
                       capsize=1.5, label=rf'sim, $\rho={rho:g}$')
        ax[1].plot([c*100 for c in b['chi']], b['bound'], ls=':',
                   color=colors.get(rho, 'C2'), lw=0.8)
    ax[1].set_yscale('log')
    ax[1].set_xlabel(r'cross-shard fraction $\chi$ (%)', fontsize=8)
    ax[1].set_ylabel(r'throughput $\Lambda$ (tx/s)', fontsize=8)
    ax[1].set_title(r'(b) L2L coordinator bound ($S{=}64$)', fontsize=8)
    ax[1].legend(fontsize=6.5, loc='upper right')
    ax[1].grid(True, ls=':', alpha=0.3)
    ax[1].tick_params(labelsize=7)

    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, 'scaling.pdf'))
    fig.savefig(os.path.join(RESULTS, 'scaling.png'), dpi=200)
    print(f"\nsaved sim_results.json and scaling.pdf/.png")


if __name__ == '__main__':
    main()
