# A Formal Model of SagaChain Consensus, with Comparison to Ethereum PoS, Solana, and Classical BFT/Nakamoto

*Self-contained analytical model. Grounded sources: SagaChain Technical
Whitepaper §§I–II (Beberman, Holdmann, Moore); granted patent US11362832B2
(D‑PoW); direct reading of the `saganode` Go implementation
(`SAGANODE_DEEPDIVE.md`); and execution costs measured on the SagaPython runtime
(`results/bench_results.json`). Comparator models use each system's public
specification. Every symbol introduced as "free" is one the sources do not fix;
these are swept, never hidden.*

---

## 1. System, network, and adversary model

We model a sharded, committee-based blockchain uniformly so the four systems are
comparable.

**Nodes and committees.** Let `N` be the total validator population. The system
runs `S ≥ 1` shards (`S = 1` for a non-sharded chain). Each shard is operated by
a committee of `n` nodes drawn from `N`. Classical BFT tolerance is assumed:
`n = 3f + 1`, safe while at most `f` nodes are Byzantine; a quorum is `q = 2f + 1`.

> **Grounding.** saganode's config uses `nodespershardcommittee = 21` and
> `posbftcount = powbftcount = 15`, i.e. `n = 21`, `q = 15`. This is exactly the
> `2f+1`-of-`3f+1` shape with `f = 7` (`3·7 = 21`, `2·7+1 = 15`). We therefore
> take `n = 21, q = 15` as the implemented operating point and `n` as a free
> sweep variable elsewhere.

**Network.** Messages incur one-way latency `δ` (a random variable; we use its
mean and tail). A node's usable bandwidth is `W`; a consensus message has size
`m_msg`; a block has size `B_blk` bytes carrying `B_tx` transactions.
Gossip dissemination to `n` nodes with fan-out `k` completes in `≈ ⌈log_k n⌉·δ`.

**Execution.** Re-validating one transaction costs `t_exec` seconds on a
validator (it re-executes, as in every replicated ledger). We treat `t_exec` as
a measured input. Its decomposition (SagaPython prototype, dev mode) is:

```
t_exec(profile) = t_floor + n_sig·t_verify + n_obj·t_create
                          + n_call·t_call + n_fld·t_field + n_obj·t_persist
```

with measured medians `t_floor ≈ 0.92 ms`, `t_verify ≈ 36 µs` (Ed25519),
`t_create ≈ 0.43 ms`, `t_call ≈ 87 µs`, `t_field ≈ 15 µs`, `t_persist ≈ 4 µs`
(R² of the linear fits 0.96–0.998). These characterize the *prototype*, and are
used only for decomposition ratios and scaling shapes — never as a cross-system
absolute-throughput claim (threat T1, §8).

**Adversary.** A static adversary controls a fraction `β` of `N` (Byzantine).
For randomized committee assignment we use the hypergeometric model; for
work-based security we use a hashrate fraction `α` of total hashpower `H`.

**Workload.** Transactions arrive at rate `Λ`. A fraction `χ` are *cross-shard*
(touch accounts on more than one shard). `σ ∈ [0,1]` is the share of all
transactions that contend on the single busiest object/account (the hot-spot).
`χ, σ` are properties of the workload, swept.

---

## 2. SagaChain: the model

### 2.1 Per-shard main loop — latency and message complexity

Each shard runs the four-stage loop (WP §I; saganode leader/follower/member
FSMs). Stage costs over the critical path of one block:

```
T_block = T_propose + T_vote + T_pow + T_gossip                         (S1)
```

| stage | model | grounding |
|---|---|---|
| `T_propose` | `δ + B_blk/W` (leader multicast) | leader `sendBlock` to committee |
| `T_vote` (PoS‑BFT) | `≈ 2δ` to reach `q` votes; **all‑to‑all** ⇒ `Θ(n²)` messages | followers multicast validation msgs until `q` sigs |
| `T_pow` | `E[W_d]/(n·h) + 2δ` — `n` miners at hashrate `h`, two sig rounds (50%+1, then `f`) | real SHA‑512/256 mining; difficulty `d` |
| `T_gossip` | `⌈log_k n⌉·δ` (+ inter‑leader unicast, async) | libp2p pubsub + DHT |

**Message complexity per shard per block** (the binding scaling fact):

```
M_block(n) = Θ(n²)        (all-to-all PoS-BFT + PoW sig rounds)           (S2)
```

so per-block network load is `Θ(S·n²·m_msg)`. This bounds committee size: large
`n` is bandwidth-limited — the reason real systems cap `n` (here `n = 21`).

**Finality.** Validation is pipelined: a transaction in block `B` is validated in
`B+1` (WP §I; confirmed in code). Hence

```
T_final^local = 2·T_block       (local, BFT-quorum finality)              (S3)
```

`T_pow` is *in the critical path* (a block is incomplete until its PoW is
gossiped). This yields a derivable tension: low latency wants small per-shard
work `E[W_d]`, but security (next) wants large pooled work — so D‑PoW's security
budget is paid in either latency or shard count.

### 2.2 Throughput — the `S_eff` form and the hot-object bound

Per-shard throughput is execution-bounded (validators re-execute every tx):

```
λ_shard = B_tx / T_block  <  1 / t_exec                                   (P1)
```

Aggregate throughput is the parallel sum over shards, discounted by cross-shard
overhead and capped by the hottest object (whose state is sequential — Amdahl):

```
Λ_saga(S) < min(  S · λ_shard / (1 + χ(c−1)) ,   λ_shard / σ  )           (P2)
            └─────── parallel/cross-shard term ──────┘ └ hot-object ┘
```

- `S·λ_shard`: WP §III disjoint-account parallelism (grounded).
- `c`: the cross-shard cost multiplier — **now grounded**, §2.4.
- `λ_shard/σ`: a single contended object serializes; for σ>0 this caps `Λ`
  *independently of `S`*. **This bound is identical for all four systems**
  (it is a property of shared mutable state, not of the consensus). The
  architectural difference lives entirely in the *effective parallelism*
  `S_eff`:

```
Λ_X < min( S_eff(X) · λ_shard ,  λ_shard / σ )                           (P2′)
S_eff(Ethereum)=1   S_eff(Solana)=#cores   S_eff(SagaChain)=S
```

### 2.3 D‑PoW security (long-term immutability)

Per shard, `H_i = r_i / d_i` (block-rate over difficulty; WP eq. 1, patent).
Pooled across shards (patent capture phase = block "braids" in code):

```
H_net = Σ_{i=1..S} r_i / d_i                                              (D1)
```

**Two security regimes.**

*Short-term (per-shard committee).* With committee `n` sampled from `N` at
adversary fraction `β`, the probability a shard is captured
(`> n/3` Byzantine, breaking BFT safety) is a hypergeometric tail:

```
P_capture(n,β,N) = P[ X > ⌊n/3⌋ ],  X ~ Hypergeom(N, βN, n)              (D2)
```

e.g. `n=21, β=0.2, N=1000 → P_capture ≈ 8·10⁻²` per assignment; `n=64 → ≈4·10⁻³`
— motivating the (specified but **not implemented**) periodic re-assignment.

*Long-term (work).* Rewriting history of depth `k` (time `τ = k/r`) requires
out-producing the **pooled** work:

```
Cost_rewrite ≈ H_net · τ · p_hash                                        (D3)
```

(`p_hash` = energy/price per hash). The fork choice selects the chain-group of
maximal cumulative hashpower (patent evaluation phase). Versus committee-only
sharding, D‑PoW multiplies long-term attack cost by a factor `Θ(S)`.

> **Implementation caveat (load-bearing).** In `saganode`, the *capture* plumbing
> exists (block braids) but the *evaluation* (cumulative-hashpower fork choice,
> partition recovery) is **absent**, and per-shard BFT signature verification is
> **stubbed** (returns `true`). So (D2)–(D3) describe the *design*, not the
> running code; they are analytic, and any security claim must footnote this.

### 2.4 Cross-shard transactions (L2L) — grounding `c`

A transaction spanning shards is **not** committed by a distributed two-phase
commit on the transaction; instead the **account ownership is migrated** to a
single shard via the L2L layer (a HotStuff BFT instance above the shards;
`L2L*FSM` in code). One L2L cycle:

```
NewView (tuples from trial-exec) → account-negotiation (Monte-Carlo)
 → Prepare → Precommit → Commit → Decide → apply (Pending{Acq,Rel} + 2-proof release)
```

Measured structurally from the code: **≈7 message rounds, ≥3 block intervals**
per cycle. Hence the cross-shard latency and the multiplier `c` are *derived*,
not assumed:

```
T_cross ≈ T_L2L + T_final^local ,   T_L2L ≳ 3·T_block                     (X1)
c ≈ 1 + (rounds_extra · work_per_account_migration) / (work of an intra-shard tx)
```

Because *every* cross-shard tx passes the single L2L coordinator (service rate
`μ_L2L`), a fraction `χ` of cross-shard load means `χ·Λ ≤ μ_L2L`, i.e. the
coordinator is a **global serial bottleneck**:

```
Λ_saga < min( S·λ_shard ,  λ_shard/σ ,  μ_L2L/χ )                         (P2″)
```

This bottleneck form **replaced an earlier, optimistic estimate**
(`(1−χ)·S·λ + min(χ·S·λ, Λ_L2L)`) once the discrete-event simulation
(`sim/des.py`, `run_sim.py`) made the serialisation explicit — a build/evaluate
loop in the design-science sense. The simulation (12 seeds, saturating batch,
random account routing, `t_exec` measured) matches (P2″): for disjoint workloads
realised throughput is `≈0.74·S·λ_shard` at S=256 (the gap is finite-size load
imbalance), and even a coordinator as fast as one shard (`μ_L2L = λ_shard`) caps
cross-shard-heavy workloads at `λ_shard/χ`. So SagaChain's horizontal scaling
holds only for **low-σ, low-χ** workloads. `μ_L2L = ρ·λ_shard` with `ρ` swept
(round count grounded in code; absolute per-cycle rate unmeasured).

> **Caveat.** L2L signature verification and the L2L fork rule are also `tbd` in
> code; (P2″) is a spec+structure+simulation model, not measured live throughput.

---

## 3. Ethereum PoS (Gasper = Casper-FFG + LMD-GHOST)

Single global state ⇒ `S_eff = 1`; no `χ` (no shards). Slots of `t_slot = 12 s`,
epochs of 32 slots. Per slot a committee attests; attestations are
BLS-**aggregated** (signature aggregation ⇒ `Θ(n)` effective verification, not
`Θ(n²)`). Finalization spans two epochs:

```
S_eff = 1
Λ_eth < min( λ_eth ,  λ_eth/σ ) = λ_eth ,  λ_eth = gas_per_slot / gas_per_tx
T_final^eth ≈ 2 epochs ≈ 12.8 min                                        (E1)
M_slot = Θ(n) effective (aggregated attestations)
```

**Security is economic, not work-based.** Safety requires `> 2/3` of *staked*
value honest; finalizing two conflicting checkpoints is *slashable*:

```
Cost_attack^eth ≈ (1/3)·TotalStake   (slashed)                           (E2)
```

Energy ≈ 0. Calibration anchor: real L1 throughput ≈ 10–30 tx/s; finality ≈ 13
min — the model must reproduce these (it does, for plausible `gas_per_slot`).

---

## 4. Solana (Tower-BFT over Proof-of-History, Sealevel execution)

Single global state, **vertical** parallelism: Sealevel executes
non-conflicting transactions in parallel on a multi-core leader using
*declared* read/write account sets ⇒ `S_eff = #cores`. PoH is a verifiable delay
clock that pre-orders transactions, removing one round of agreement on time. The
leader schedule is **stake-weighted and published an epoch ahead** (contrast:
SagaChain's intended per-block VRF unpredictability — though VRF is absent in
both SagaChain's spec-vs-code).

```
S_eff = #cores            (no sharding; one global state)
Λ_sol < min( C · λ_sol ,  λ_sol/σ ) ,  C = #cores                        (So1)
T_slot ≈ 0.4 s ; optimistic confirmation at 2/3 stake ; full finality ~ tens of slots
```

Crucially Solana shares the **identical hot-object term** `λ/σ`: a hot writable
account (AMM pool, popular mint) serializes regardless of cores. Security is PoS
(Tower-BFT lockouts); no work pooling; high validator hardware requirement is
the decentralization cost of the vertical-scaling choice. Calibration anchor:
sustained ~1–3k tx/s, with documented contention-driven slowdowns/outages — a
direct empirical instance of the `λ/σ` bound.

---

## 5. Baselines: classical PBFT/HotStuff and Nakamoto PoW

Two reference points bracket the design space.

**PBFT / HotStuff (single committee, no work).**
```
S_eff = 1
T_final = O(1) rounds (deterministic, immediate)
M = Θ(n²) (PBFT)  or  Θ(n) (HotStuff, leader-aggregated, linear)
Safety: f < n/3 Byzantine ; no long-range protection (key-dependent)
```
SagaChain's *per-shard* loop is PBFT-shaped (`Θ(n²)`, §2.1); its *L2L* layer is
explicitly HotStuff-shaped (linear, leader-driven) — a deliberate split.

**Nakamoto PoW (Bitcoin / pre-Merge Ethereum).**
```
S_eff = 1
T_final = probabilistic (k confirmations; "≈ irreversible over time")
M = Θ(n) (gossip)
Security: rewrite cost ≈ α·H·τ·p_hash (work) ; objective, key-independent
Energy: high
```
SagaChain = **per-shard PBFT/PoS for fast local finality** ⊕ **Nakamoto-style
pooled PoW for long-term, key-independent immutability and fork choice**. That
hybrid is its defining formal feature (and the part least realized in code).

---

## 6. Side-by-side comparison

| axis | **SagaChain** | Ethereum PoS | Solana | PBFT/HotStuff | Nakamoto PoW |
|---|---|---|---|---|---|
| parallelism `S_eff` | `S` (horizontal, sharded) | 1 | `#cores` (vertical) | 1 | 1 |
| hot-object bound | `λ/σ` (same for all) | `λ/σ` | `λ/σ` | `λ/σ` | `λ/σ` |
| local finality | `2·T_block` (pipelined) | ~2 epochs (~13 min) | ~0.4 s opt., ~12 s final | `O(1)` rounds | probabilistic |
| msg complexity (committee) | `Θ(n²)` per shard | `Θ(n)` aggregated | `Θ(n)` (leader, PoH) | `Θ(n²)`/`Θ(n)` | `Θ(n)` |
| cross-shard | L2L account migration, ~7 rounds / ≥3 blocks | n/a (no shards) | n/a | n/a | n/a |
| short-term security | committee BFT, `P_capture(n,β)` | economic, `>2/3` stake | economic, `>2/3` stake | `f<n/3` | — |
| long-term security | **pooled PoW** `H_net=ΣH_i`, `Θ(S)` gain | slashing `≈⅓` stake | lockouts (key-dep.) | key-dep. (none) | work `α·H·τ` |
| energy | medium (PoW per shard) | ~0 | low–medium | ~0 | high |
| selection/decentralization | VRF *spec'd*, **static config in code** | RANDAO, ~1M validators | stake-weighted schedule, high HW | fixed committee | open mining |
| key distinctive claim | sharded state ⊕ pooled-PoW security | economic finality | vertical parallel exec | classical safety | objective immutability |

**Implementation-status overlay** (what the running `saganode` actually does):
real per-shard PoW mining, gossip, FSMs, **and the L2L cross-shard protocol**;
**stubbed/absent**: BFT signature verification, VRF selection (static config),
D‑PoW evaluation/fork-choice. So the *performance* model (§2.1–2.4) is partly
measurable on the real node; the *security* model (§2.3) is analytic only.

---

## 7. What the model lets us assert (and not)

**Defensible (structural / bound-form), grounded in WP + code:**
1. `Λ < min(S_eff·λ_shard, λ_shard/σ)` holds for all four systems with the *same*
   hot-object term; SagaChain's only architectural lever is `S_eff = S`
   (horizontal) vs Solana's `#cores` (vertical) vs Ethereum's `1`.
2. Per-shard BFT is `Θ(n²)` ⇒ committee size is bandwidth-bounded (`n=21` in code).
3. Local finality is exactly `2·T_block` (pipelining).
4. Cross-shard throughput follows (P2″): graceful in `χ`, ultimately bounded by
   the single L2L coordinator — a global serialization point (≈7 rounds/≥3 blocks).
5. D‑PoW gives a `Θ(S)` long-term attack-cost multiplier over committee-only
   sharding (analytic; equations (D1)–(D3)).

**Not derivable as point predictions:** absolute tx/s, seconds, joules — they
need `n, S, d, B_blk, δ, W`, none fixed by any source; we sweep them.

---

## 8. Threats to validity

- **T1.** Measured `t_exec` is the *Python prototype* (in-memory store, no
  network): valid for decomposition/shape, not absolute cross-system TPS.
- **T2.** SagaChain's security model (§2.3) is **analytic**; the running code
  stubs BFT verification and omits D‑PoW fork-choice — so it cannot be
  *measured* as a system. State this in any write-up.
- **T3.** L2L `c`/`T_cross` are grounded in code *structure* (round count), not
  in measured latency (no buildable cluster — see `SAGANODE_DEEPDIVE.md`).
- **T4.** Comparator models (Gasper, Solana) are calibratable against live
  networks; SagaChain's is not — an asymmetry to disclose.
- **T5.** Workload parameters `χ, σ` dominate the comparison and are assumptions;
  results should be reported as families over `(χ, σ)` with sensitivity, not as
  single numbers (cf. `results/REPORT.md`).

---

## 9. Honest framing for a paper

A defensible contribution is: *"A uniform analytical model of sharded
committee+work consensus, instantiated for SagaChain (with its design grounded
in the released node code and the granted D‑PoW patent) and compared on
structural axes — throughput-scaling shape, message complexity,
finality-in-rounds, and long-term attack-cost form — against Ethereum PoS,
Solana, and the PBFT/Nakamoto baselines, with an explicit assumption ledger."*
The novel, code-grounded pieces are (i) the L2L account-migration cross-shard
model (P2″) and (ii) the implementation-status overlay separating measured
performance from analytic security. The claim is about the *design and its
bounds*, not "SagaChain is faster/safer than X."
