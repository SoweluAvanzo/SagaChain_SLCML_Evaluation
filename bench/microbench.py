"""
microbench.py — component micro-benchmarks for the t_exec decomposition.

Measures, in isolation:
  ed25519_sign / ed25519_verify   PyNaCl, per signature (validator pays verify)
  sha256                          per 1 KiB hashed
  method_compile                  base64-decode + compile() of a stored CMI
                                  method source (the dispatch path's static cost)

These complement the stage timings from harness.py: the development pipeline
does not verify signatures, so validator-side verification cost must be added
explicitly to the model as  n_sig * t_verify.
"""
import base64
import hashlib
import statistics
import time

import nacl.signing


def _time(fn, reps, inner=1):
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        for _ in range(inner):
            fn()
        samples.append((time.perf_counter() - t0) / inner)
    return {
        'median_s': statistics.median(samples),
        'mean_s': statistics.fmean(samples),
        'stdev_s': statistics.stdev(samples) if len(samples) > 1 else 0.0,
        'reps': reps, 'inner': inner,
    }


METHOD_SRC = '''@SagaMethod()
def Inc(self, n: int) -> int:
    self.count = self.count + n
    return self.count
'''


def run_all(reps=50, inner=20):
    out = {}

    sk = nacl.signing.SigningKey.generate()
    vk = sk.verify_key
    payload = b'x' * 1024
    digest = hashlib.sha256(payload).digest()
    signed = sk.sign(digest)

    out['ed25519_sign'] = _time(lambda: sk.sign(digest), reps, inner)
    out['ed25519_verify'] = _time(
        lambda: vk.verify(signed.message, signed.signature), reps, inner)
    out['sha256_1KiB'] = _time(lambda: hashlib.sha256(payload).digest(), reps, inner)

    b64 = base64.b64encode(METHOD_SRC.encode())

    def _decode_compile():
        src = base64.b64decode(b64).decode()
        compile(src, '<cmi-method>', 'exec')

    out['method_b64_compile'] = _time(_decode_compile, reps, inner)

    # per-object persistence: JSON round-trip + store Put of a representative
    # serialized object taken from the foundation set in the write store
    try:
        from . import env_bootstrap as ENV
        import ObjectDataBase as _odb
        vals = sorted(_odb.writedb._data.values(), key=len)
        if vals:
            sample = vals[len(vals) // 2]              # median-size object
            parsed = __import__('json').loads(sample)
            store = ENV.CountingLevelDB('persistbench')
            import json as _json

            def _persist():
                blob = _json.dumps(parsed).encode()
                store.Put(b'k' * 32, blob)

            r = _time(_persist, reps, inner)
            r['sample_bytes'] = len(sample)
            out['persist_object'] = r
    except Exception as exc:                            # pragma: no cover
        out['persist_object'] = {'error': repr(exc)}
    return out
