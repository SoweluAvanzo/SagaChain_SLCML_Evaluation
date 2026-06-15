# Solidity counterpart of the consent directive

EVM implementation of the SLCML healthcare consent directive from the paper's
case study (permission P1, right R1, obligation O1), with a Hardhat test that
runs the four scenarios of Section 5.3 (valid access granted; wrong-purpose
denied and flagged; patient revokes; post-revocation access denied), plus the
P1/R1 access-control guards. It mirrors the SagaPython contract in
`../bench/usecase.py`; this is the functional feasibility check only, not a
performance comparison.

```bash
npm install
npm test
```
