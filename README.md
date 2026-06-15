# Replication package: *Legally-Relevant Smart Contracts on a Stateful Blockchain*

This repository reproduces every figure and quantitative claim in the evaluation
of the paper *"Legally-Relevant Smart Contracts on a Stateful Blockchain: SLCML on
SagaChain"* (GoodIT 2026). It contains the measurement harness, the analytical
throughput/security model, the discrete-event simulation, and the scripts that
produce the figure and tables, together with the input data needed to regenerate
the published results.

The package is organised so that **the figure and all simulation numbers can be
regenerated with one command and no special runtime**, while the underlying
prototype measurements can be re-taken by anyone who also installs the SagaPython
runtime (see *Experiment 1–2*).

---

## 1. What is measured, and what reproduces exactly

The evaluation rests on three experiments. Two of them produce **deterministic**
results that reproduce bit-for-bit; one produces **wall-clock timings** that are
host-dependent.

| Result | Script | Reproduces |
|---|---|---|
| Per-operation cost decomposition, giving `t_exec ≈ 2.05 ms` | `run_bench.py` | wall-clock (host-dependent value; **shape**/linearity stable) |
| Use-case: K independent consent directives → **2.000 objects/directive** | `run_usecase.py` | object count **exact**; timing host-dependent |
| Discrete-event simulation → **`figures/scaling.pdf`** and all sim numbers | `run_sim.py` | **exact** (fixed seeds; reads shipped `results/bench_results.json`) |

> **Why some numbers are host-dependent.** The object-creation cost is measured as
> wall-clock time on a Python research prototype, so its *absolute* value depends
> on the machine and on system load. What is stable, and what the paper claims, is
> (a) the **object count** (a deterministic property of the object graph — exactly
> two persistent objects per consent directive), and (b) the **shape** of how cost
> and throughput scale (linear cost in the number of contracts; throughput growing
> with the shard count until a hot object or the cross-shard coordinator binds).
> The simulation's vertical axis inherits the measured `t_exec`; the published
> figure ships the exact `t_exec` used (`results/bench_results.json`), so the
> figure regenerates identically.

---

## 2. Quick start (figure + simulation, no SagaPython needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # matplotlib, numpy

# Reproduce the paper figure and all simulation numbers from the shipped cost data:
python3 run_sim.py
#   -> writes results/sim_results.json and results/scaling.{pdf,png}
#   -> prints the swept throughput values (Fig. 4a/4b of the paper)

# Reproduce the analytical model report (bounds, message complexity, security):
python3 run_model.py
#   -> writes results/REPORT.md and results/model_results.json
```

`run_sim.py` reads the measured cost from `results/bench_results.json` and is fully
deterministic (12 fixed seeds, seeds 0–11). The expected output is provided in
`results/expected_sim_results.json`; the regenerated `results/sim_results.json`
should match it exactly (e.g. `σ=0, S=256 → 93,470 tx/s`).

---

## 3. The three experiments in detail

### Experiment 1 — Cost decomposition (`run_bench.py`)
Measures the marginal cost of each primitive runtime operation by running
transaction scripts that perform a controlled, increasing number of one operation
at a time (define a class, create an object, call a method, read/write a field)
and fitting a line to `(count, time)`. The slopes give a fixed transaction floor
plus the cost of one object creation, one method call, one field access, one
Ed25519 signature verification, and one object persist. Composing these for the
consent-directive profile yields `t_exec ≈ 2.05 ms`. Output:
`results/bench_results.json` (shipped, used by the simulation).

### Experiment 2 — Use case (`run_usecase.py`)
Builds the e-healthcare consent directive (two cooperating classes: a consent
object implementing the permission and right rules, and an append-only audit
object implementing the logging obligation) and instantiates `K = 1..64`
*independent* directives in one transaction, exercising an access request on each.
It records the validator-side execution time and the number of persistent objects
created, then fits the marginal cost and marginal object count. Result: **exactly
2.000 objects per directive (R² = 1.000)** — each directive is its own disjoint
object pair, so the K directives share no mutable state and are independently
shardable. Output: `results/usecase_results.json`.

### Experiment 3 — Discrete-event simulation (`run_sim.py`, `sim/des.py`)
Models a sharded network as a set of single-server queues — one server per shard
plus one cross-shard coordinator — driven by the measured `t_exec`. A saturating
batch of 20,000 transactions is released; each is routed to a random shard (so the
simulation includes random load imbalance), contends for one designated hot object
with probability `σ`, and is cross-shard with probability `χ` (occupying the
coordinator, then a shard). Throughput is `transactions / makespan`, averaged over
12 seeds with a 95% confidence interval; the analytical bound is overlaid.
Sweeps: shards `S ∈ {1..256}` at `σ ∈ {0, 0.1%, 1%, 10%}`, and `χ ∈ [0,1]` at
`S = 64`. Output: `figures/scaling.pdf` (Fig. 4 of the paper) and
`results/sim_results.json`.

The implementation (`sim/des.py`) is a non-preemptive, event-driven scheduler over
a priority queue of task-ready events; see its module docstring for the exact
queueing discipline.

---

## 4. Re-taking the prototype measurements (Experiments 1–2)

`run_bench.py` and `run_usecase.py` execute real transaction scripts on the
**SagaPython runtime** (the reference implementation of the SagaChain object
model). The exact runtime version used for the published measurements is pinned
as a git submodule at `external/sagapython`
(`https://code.prasaga.com/sagachain/sagapython`, commit
`378deaaa154b066d5905c3149dfbab57836f4887`, "fixed Log()"). Fetch it with:

```bash
git submodule update --init external/sagapython     # or: git clone --recurse-submodules ...
```

The runtime additionally needs `pynacl` (its `posix_ipc`/protobuf/LevelDB
dependencies are stubbed by `bench/env_bootstrap.py`, which opens an in-memory
store). To run against a different checkout instead of the pinned submodule, set
`SAGAPYTHON_HOME` to that checkout's root. Then:

```bash
python3 run_bench.py      # re-measures the per-operation costs -> results/bench_results.json
python3 run_usecase.py    # re-runs the K-directive experiment  -> results/usecase_results.json
```

Re-running these reproduces the **object counts and linear shape exactly** but the
**absolute milliseconds depend on the host**; keep the shipped
`results/bench_results.json` to regenerate the published figure with `run_sim.py`.

Re-running these will reproduce the **object counts and the linear shape** exactly,
but the **absolute milliseconds will differ** from run to run and machine to
machine. To regenerate the published figure with the original cost basis, keep the
shipped `results/bench_results.json` and run `run_sim.py`.

---

## 5. Repository layout

```
run_bench.py        Experiment 1: per-operation cost decomposition (needs SagaPython)
run_usecase.py      Experiment 2: K independent consent directives (needs SagaPython)
run_sim.py          Experiment 3: discrete-event simulation + figure (self-contained)
run_model.py        Analytical bounds report (self-contained)
make_figure.py      Standalone figure generator from saved results
model/bounds.py     Throughput (S_eff), cross-shard (L2L), message-complexity and
                    security bounds; cost model fitted from bench_results.json
sim/des.py          The discrete-event simulator
bench/              Measurement harness: runtime bootstrap, transaction-script
                    harness, micro-benchmarks, workload + use-case generators
results/            bench_results.json (shipped input); expected_*.json (reference
                    outputs to diff against)
figures/            scaling.pdf / .png (the published figure)
MODEL.md            Full derivation of the analytical model and its assumptions
```

## 6. Mapping to the paper
- `figures/scaling.pdf` → Fig. 4 (throughput vs. shards; throughput vs. cross-shard share).
- `run_sim.py` console output → the throughput values discussed in *Case study*.
- `run_usecase.py` → the *2.000 objects per directive* result and Table 3.
- `run_model.py` / `MODEL.md` → the bounds of Section 3 (the `S_eff` form, the
  cross-shard coordinator bound, the `Θ(n²)` committee cost, the security pooling).

## 7. Honesty / scope
The SagaPython runtime is a research prototype; the security mechanisms (committee
signature verification, randomised selection, and the pooled-proof-of-work
fork-choice) are not yet wired, so the security results in the paper are analytical
rather than measured. These scripts therefore characterise the **execution cost and
scaling shape** of the object model, not absolute throughput or security of a
deployed network.
