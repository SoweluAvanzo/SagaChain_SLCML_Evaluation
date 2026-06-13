# Grounded Scalability Model — Results

All formulas derive from the SagaChain whitepaper (WP §I–III) and measurements on the SagaPython runtime in this repository. Free parameters are explicit and swept. Absolute numbers characterize the Python prototype, not the architecture; cross-platform comparisons are made on *shape* only.

## 1. Measured marginal costs (SagaPython runtime, dev mode)

| Cost component | Value | Fit R² |
|---|---|---|
| Transaction pipeline floor | 0.915 ms | — |
| Define one CMI class | 0.977 ms | — |
| Create one persistent object | 0.427 ms | 0.9979 |
| One CMI method call | 86.6 µs | 0.9984 |
| One field write+read pair | 15.1 µs | 0.9590 |
| One object→object call | 159.2 µs | 0.9972 |
| Ed25519 signature verify | 35.6 µs | micro |
| Persist one object (serialize+store) | 4.1 µs | micro |

Internal consistency: obj→obj call / method call = 1.84 (dispatch-count prediction: 2.0).

## 2. P1 — per-shard throughput ceiling

λ_shard < 1/t_exec. Validators re-execute every transaction (WP §I).

| Tx profile | t_exec | λ_shard ceiling (tx/s, this prototype) |
|---|---|---|
| transfer-like (1 create, 2 calls) | 1.585 ms | 631 |
| minimal (signature + floor only) | 0.951 ms | 1,052 |
| contract-deploy (1 class, 1 create) | 2.460 ms | 406 |
| consent-like (2 creates, 4 calls) | 2.219 ms | 451 |

## 3. P2 — network ceiling and the unified comparison (shape)

Λ < min(S_eff·λ_shard, λ_shard/σ); identical form for all platforms, platform-specific S_eff (Ethereum 1, Solana ~cores, SagaChain S).

Sweep over shards S and hot-object share σ (transfer-like profile; χ=0 upper bound):

| S | σ=0 (fully disjoint) | σ=0.1% | σ=1% | σ=10% |
|---|---|---|---|---|
| 1 | 631 | 631 | 631 | 631 |
| 4 | 2,523 | 2,523 | 2,523 | 2,523 |
| 16 | 10,094 | 10,094 | 10,094 | 6,309 |
| 64 | 40,376 | 40,376 | 40,376 | 6,309 |
| 256 | 161,503 | 161,503 | 63,087 | 6,309 |

Reading: scaling is linear in S until the hot-object term binds — at σ=1% the ceiling is 100·λ_shard regardless of S; at σ=10%, 10·λ_shard. The hot-object term is identical on Ethereum/Solana/SagaChain; the architectural difference is S_eff only (WP §III; Sealevel docs; Gasper spec).

Cross-shard sensitivity (S=64, σ=0.1%): Λ-bound vs (χ, c):

| χ \ c | 2 | 4 | 8 |
|---|---|---|---|
| 1% | 39,976 | 39,200 | 37,734 |
| 5% | 38,453 | 35,109 | 29,908 |
| 20% | 33,646 | 25,235 | 16,823 |

c (cross-shard cost multiplier) is an EXPLICIT ASSUMPTION — no cross-shard protocol exists in the available documents.

### 3b. Cross-shard via L2L (grounded in saganode: ~7 rounds / ≥3 blocks)

Cross-shard txs migrate account ownership through the L2L HotStuff coordinator — a single global serialization point. Throughput stays near-linear in S for low χ, then is bounded by the L2L coordinator as χ grows (S=64, σ=0.1%, L2L capacity = 0.5·λ_shard):

| χ | Λ-bound (tx/s) | L2L saturated? | cross-shard latency |
|---|---|---|---|
| 0% | 40,376 | no | 5 block intervals (~7 msg rounds) |
| 5% | 12,617 | yes | 5 block intervals (~7 msg rounds) |
| 20% | 3,154 | yes | 5 block intervals (~7 msg rounds) |
| 50% | 1,262 | yes | 5 block intervals (~7 msg rounds) |
| 100% | 631 | yes | 5 block intervals (~7 msg rounds) |

The L2L coordinator is a second hot-spot: as χ→1 the system is bounded by Λ_L2L, not S·λ_shard. This is the sharpest code-grounded structural claim — SagaChain's sharding scales for low cross-shard workloads and is L2L-coordinator-bound otherwise.

## 4. P3 — message complexity per shard per block (WP §I)

| n (nodes/shard) | BFT all-to-all msgs | total lower bound |
|---|---|---|
| 4 | 12 | 20 |
| 16 | 240 | 272 |
| 64 | 4,032 | 4,160 |
| 256 | 65,280 | 65,792 |

Ω(n²) per shard per block — shard committee size is bandwidth-bounded; large validator sets per shard are not free.

## 5. P4 — finality and security scaling (WP §I–II)

Local finality: exactly 2 blocks (pipelined validation).

Per-shard capture probability P[Byzantine > n/3] (VRF assignment from N=1000 nodes, adversary fraction β):

| n \ β | 10% | 20% | 30% |
|---|---|---|---|
| 16 | 3.01e-03 | 8.00e-02 | 3.39e-01 |
| 64 | 2.81e-08 | 3.84e-03 | 2.55e-01 |
| 256 | 1.28e-41 | 1.10e-09 | 8.51e-02 |

D-PoW pooling: long-term rewrite requires out-working H_net = Σ rᵢ/dᵢ — a factor-S(=64) gain over committee-only sharding, by WP eq. (2).
Caveat: PoW weight attests expenditure, not state validity; no fraud-proof/data-availability mechanism is specified in the available documents.

## 6. Assumption ledger / threats to validity

- Measured costs are from the **Python prototype in dev mode** (in-memory store, no real network): valid for decomposition ratios and scaling shapes, NOT for absolute cross-platform TPS.
- Signature verification is not executed in the dev pipeline; it is added analytically (n_sig × measured Ed25519 verify).
- State persistence is added analytically (n_objects × measured serialize+store); real LevelDB disk I/O would be higher.
- Cross-shard atomicity has NO specified protocol; χ and c are assumptions, and the χ=0 column is the only unconditional bound.
- Consensus latency (PoW in critical path), block size and shard sizing are unspecified → no end-to-end latency/TPS prediction.
- No slashing/economic security is specified → economic comparison with Ethereum's slashable finality is out of scope.
- Ethereum/Solana reference forms come from their public specs, calibratable against live networks; SagaChain's cannot be calibrated against any deployment.

