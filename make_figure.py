#!/usr/bin/env python3
"""make_figure.py — model figure for the paper (no SagaPython runtime needed).
Reads bench_results.json + usecase_results.json, plots Λ-bounds from bounds.py."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'results')

from model.bounds import (MeasuredCosts, FreeParams,        # noqa: E402
                          p1_shard_ceiling, p2_network_ceiling,
                          p2_l2l_throughput)

import matplotlib                                            # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                             # noqa: E402

costs = MeasuredCosts.from_bench(os.path.join(RESULTS, 'bench_results.json'))
lam, _ = p1_shard_ceiling(costs, n_sig=1, n_classes=0, n_create=2,
                          n_calls=2, n_field_pairs=4)        # consent profile

fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.7))

Svals = [1, 2, 4, 8, 16, 32, 64, 128, 256]
for sg, mk in [(0.0, 'o'), (0.001, 's'), (0.01, '^'), (0.1, 'd')]:
    ys = [p2_network_ceiling(lam, FreeParams(S=S, sigma=sg, chi=0.0))['upper_bound_chi0']
          for S in Svals]
    lbl = r'$\sigma=0$' if sg == 0 else rf'$\sigma={sg:g}$'
    ax[0].loglog(Svals, ys, marker=mk, ms=3.5, lw=1.2, label=lbl)
ax[0].axhline(lam, color='gray', ls='--', lw=0.8)
ax[0].annotate(r'Ethereum $S_{\mathrm{eff}}{=}1$', (1.1, lam*1.25), fontsize=6.5,
               color='gray')
ax[0].set_xlabel(r'shards $S\;(=S_{\mathrm{eff}})$', fontsize=8)
ax[0].set_ylabel(r'throughput bound $\Lambda$ (tx/s)', fontsize=8)
ax[0].set_title('(a) Horizontal scaling vs. hot-object share', fontsize=8)
ax[0].legend(fontsize=6.5, loc='lower right', ncol=2)
ax[0].grid(True, which='both', ls=':', alpha=0.4)
ax[0].tick_params(labelsize=7)

chis = [i/40 for i in range(41)]
ys = [p2_l2l_throughput(lam, FreeParams(S=64, sigma=0.001, chi=c))['bound'] for c in chis]
ax[1].plot([c*100 for c in chis], ys, color='C3', lw=1.6)
ax[1].set_xlabel(r'cross-shard fraction $\chi$ (%)', fontsize=8)
ax[1].set_ylabel(r'throughput bound $\Lambda$ (tx/s)', fontsize=8)
ax[1].set_title(r'(b) L2L cross-shard bound ($S{=}64$)', fontsize=8)
ax[1].grid(True, ls=':', alpha=0.4)
ax[1].tick_params(labelsize=7)

fig.tight_layout()
out = os.path.join(RESULTS, 'scaling.pdf')
fig.savefig(out)
fig.savefig(os.path.join(RESULTS, 'scaling.png'), dpi=200)
print('saved', out)
