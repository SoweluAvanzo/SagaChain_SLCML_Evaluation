"""
env_bootstrap.py — boot the SagaPython runtime in development mode for benchmarking.

Adapted from `run_healthcare_test.py` (the project's own standalone runner):
stubs the external saga-leveldb / saga-pbtype dependencies, unifies duplicate
module identities, patches ObjectDataBase into development mode, opens
in-memory state databases and bootstraps the foundation classes.

Instrumentation added for measurement:
  * CountingLevelDB — in-memory store counting Get/Put/Delete operations,
    payload bytes, and time spent inside store calls, so state-I/O can be
    separated from pure execution in the t_exec decomposition.

IMPORTANT: import this module FIRST, before any sagapython module.
"""
import sys
import os
import types
import builtins
import time
import importlib

# --------------------------------------------------------------------------- paths
# The SagaPython runtime is resolved, in order, from:
#   1. $SAGAPYTHON_HOME      — an explicit checkout of the runtime; else
#   2. external/sagapython   — the git submodule this repo pins to the exact
#                              commit the measurements were taken on
#                              (sagachain/sagapython @ 378deaaa, "fixed Log()").
# Otherwise a clear, actionable error is raised. This guarantees a re-run imports
# the *same* runtime version that produced the published numbers, instead of
# whatever happens to sit on the host. (Earlier versions hard-coded a sibling
# `Finance Pilot/src/sagapython` path, which only existed on the author's machine
# and pinned no version — see README "Reproducing the prototype measurements".)
PINNED_COMMIT = '378deaaa154b066d5905c3149dfbab57836f4887'
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_sagapython_home():
    """Locate the SagaPython runtime root (the dir containing sagapython/product)."""
    env = os.environ.get('SAGAPYTHON_HOME')
    if env:
        cand = os.path.abspath(os.path.expanduser(env))
        if os.path.isdir(os.path.join(cand, 'sagapython', 'product')):
            return cand
        raise RuntimeError(
            "SAGAPYTHON_HOME=%r is not a SagaPython checkout "
            "(no sagapython/product/ inside it)." % env)
    submodule = os.path.abspath(os.path.join(_THIS_DIR, '..',
                                             'external', 'sagapython'))
    if os.path.isdir(os.path.join(submodule, 'sagapython', 'product')):
        return submodule
    raise RuntimeError(
        "SagaPython runtime not found. Fetch the pinned runtime with\n"
        "    git submodule update --init external/sagapython\n"
        "or set SAGAPYTHON_HOME to a checkout of\n"
        "    https://code.prasaga.com/sagachain/sagapython  (commit %s)."
        % PINNED_COMMIT[:10])


BASE = _resolve_sagapython_home()
PRODUCT = os.path.join(BASE, 'sagapython', 'product')
APPS = os.path.join(BASE, 'sagapython', 'apps')
SAGAPYTHON = os.path.join(BASE, 'sagapython')
SAGACLIENT = os.path.join(PRODUCT, 'sagaclient')

for p in [PRODUCT, APPS, SAGAPYTHON, SAGACLIENT, BASE]:
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ['SPPATH'] = SAGAPYTHON
os.environ['SPIMPORTPATH'] = ':'.join([BASE, SAGAPYTHON, PRODUCT, APPS])

# CMIImporter resolves module paths like 'sagapython/product/X.py' relative to
# the working directory (the project's own runner executes from the repo root).
os.chdir(BASE)

# --------------------------------------------------------------------------- stubs
for name in ['session_pb2', 'posix_pb2', 'validate_accounts_pb2',
             'validate_accounts_pb2_grpc', 'node_sagapython_msg_pb2',
             'node_sagapython_msg_pb2_grpc', 'common_pb2']:
    if name not in sys.modules:
        m = types.ModuleType(name)

        class _D:
            def __init__(self, **kw):
                self.__dict__.update(kw)
        m.Ses = _D
        m.PosixRequest = _D
        m.PosixResponse = _D
        sys.modules[name] = m


class DBStats:
    """Mutable counters shared by all CountingLevelDB instances."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.gets = 0
        self.puts = 0
        self.deletes = 0
        self.get_bytes = 0
        self.put_bytes = 0
        self.time_s = 0.0

    def snapshot(self):
        return dict(gets=self.gets, puts=self.puts, deletes=self.deletes,
                    get_bytes=self.get_bytes, put_bytes=self.put_bytes,
                    time_s=self.time_s)


DB_STATS = DBStats()


class CountingLevelDB:
    """In-memory LevelDB-compatible store with operation accounting."""
    def __init__(self, name, create_if_missing=True):
        self._data = {}

    def Put(self, key, value):
        t0 = time.perf_counter()
        if isinstance(key, str):
            key = key.encode()
        if isinstance(value, str):
            value = value.encode()
        self._data[key] = value
        DB_STATS.puts += 1
        DB_STATS.put_bytes += len(value)
        DB_STATS.time_s += time.perf_counter() - t0

    def Get(self, key):
        t0 = time.perf_counter()
        if isinstance(key, str):
            key = key.encode()
        v = self._data.get(key)
        DB_STATS.gets += 1
        if v is not None:
            DB_STATS.get_bytes += len(v)
        DB_STATS.time_s += time.perf_counter() - t0
        if v is None:
            raise KeyError(key)
        return v

    def Delete(self, key):
        if isinstance(key, str):
            key = key.encode()
        self._data.pop(key, None)
        DB_STATS.deletes += 1

    def RangeIter(self, key_from=None, key_to=None,
                  include_value=True, reverse=False):
        items = sorted(self._data.items())
        if reverse:
            items = list(reversed(items))
        if key_from:
            if isinstance(key_from, str):
                key_from = key_from.encode()
            items = [(k, v) for k, v in items if k >= key_from]
        if key_to:
            if isinstance(key_to, str):
                key_to = key_to.encode()
            items = [(k, v) for k, v in items if k <= key_to]
        if include_value:
            return iter(items)
        return iter([k for k, v in items])


if 'leveldb' not in sys.modules:
    _lm = types.ModuleType('leveldb')
    _lm.LevelDB = CountingLevelDB
    sys.modules['leveldb'] = _lm
    builtins.leveldb = _lm

# --------------------------------------------------------------------------- module aliasing
_all_product_modules = [
    'sagapythonglobals', 'CMILOID', 'splogging', 'ObjectTable',
    'ObjectDataBase', 'CMI', 'CMIClass', 'CMIObjectData',
    'SPClassObject', 'SPClassLinearization', 'SPClassRuntime',
    'SPClass', 'SPMetaClass', 'SPMetaMetaClass',
    'SPClassVerify', 'SPClassTransactionObject', 'SPClassAccount',
    'SPClassSystemAccount', 'SPClassAccountFactory', 'SPClassMerkelTree',
    'transactionscriptglobals', 'cmidecorators', 'CMIImporter',
    'cmifilefinder', 'baseobjects', 'spexec', 'writeobjects',
    'transientobject', 'accountsignatureverification', 'syanalyze',
    'sagapythonself',
]
for _mname in _all_product_modules:
    full = f'sagapython.product.{_mname}'
    if _mname not in sys.modules:
        try:
            importlib.import_module(_mname)
        except ImportError:
            pass
    if _mname in sys.modules and full not in sys.modules:
        sys.modules[full] = sys.modules[_mname]

import sagapython.apps.sputils as sputils            # noqa: E402
sputils.update_importpath_env()

import sagapython.product.ObjectDataBase as ObjectDataBase   # noqa: E402


def _patch_odb(odb):
    odb.leveldb = sys.modules['leveldb']
    odb.read = odb.read_development
    odb.write = odb.write_development
    odb.Exists = odb.Exists_development
    odb.starttransaction = lambda: None
    odb.stoptransaction = lambda: None

    def _local_write_batch():
        for k, v in odb.writtenobjs.items():
            odb.writedb.Put(k, v)
        odb.writtenobjs.clear()
    odb.write_foundation_batch = _local_write_batch
    odb.write_production_batch = _local_write_batch


import ObjectDataBase as _odb_direct                 # noqa: E402, F401
sys.modules['ObjectDataBase'] = ObjectDataBase
_patch_odb(ObjectDataBase)
for modname in list(sys.modules):
    if modname.endswith('ObjectDataBase') and sys.modules[modname] is not ObjectDataBase:
        sys.modules[modname] = ObjectDataBase

_modules_to_unify = [
    'sagapythonglobals', 'sagapythonself', 'CMI', 'CMIClass',
    'baseobjects', 'cmidecorators', 'splogging', 'CMILOID',
    'SPClassObject', 'SPClassLinearization', 'SPClassRuntime',
    'SPClass', 'SPMetaClass', 'SPClassVerify',
    'SPClassTransactionObject', 'SPClassAccount',
    'SPClassSystemAccount', 'SPClassAccountFactory',
    'transactionscriptglobals', 'CMIImporter', 'cmifilefinder',
    'CMIObjectData', 'CMILOID', 'spexec', 'writeobjects',
    'transientobject', 'accountsignatureverification',
    'ObjectTable', 'ObjectDataBase',
]
for _mname in _modules_to_unify:
    full = f'sagapython.product.{_mname}'
    short = _mname
    if short not in sys.modules:
        try:
            __import__(short)
        except ImportError:
            pass
    if full not in sys.modules:
        try:
            __import__(full)
        except ImportError:
            pass
    if full in sys.modules and short in sys.modules:
        if sys.modules[full] is not sys.modules[short]:
            sys.modules[full] = sys.modules[short]
    elif short in sys.modules:
        sys.modules[full] = sys.modules[short]
    elif full in sys.modules:
        sys.modules[short] = sys.modules[full]

import sagapython.product.sagapythonglobals as sagapythonglobals   # noqa: E402
import sagapythonself                                              # noqa: E402

import spexec as _spexec               # noqa: E402
from splogging import Log              # noqa: E402

_txmod = types.ModuleType('apps.sptransactionexecutor.__main__')
for attr in dir(_spexec):
    setattr(_txmod, attr, getattr(_spexec, attr))
_txmod.Log = Log
if 'apps' not in sys.modules:
    am = types.ModuleType('apps')
    am.__path__ = [APPS]
    sys.modules['apps'] = am
if 'apps.sptransactionexecutor' not in sys.modules:
    tp = types.ModuleType('apps.sptransactionexecutor')
    tp.__path__ = [os.path.join(APPS, 'sptransactionexecutor')]
    sys.modules['apps.sptransactionexecutor'] = tp
sys.modules['apps.sptransactionexecutor.__main__'] = _txmod

if not hasattr(sagapythonself, 'CMIData'):
    sagapythonself.CMIData = sagapythonglobals.CMIData

# --------------------------------------------------------------------------- bootstrap
_BOOTSTRAPPED = {'done': False, 'bootstrap_time_s': None}


def bootstrap():
    """Open in-memory DBs and create the foundation classes. Idempotent."""
    if _BOOTSTRAPPED['done']:
        return _BOOTSTRAPPED

    import tempfile
    from baseobjects import CreateBaseObjects

    instatedb = os.path.join(tempfile.mkdtemp(), 'sagapython.db')
    readstatedb = os.path.join(tempfile.mkdtemp(), 'sagapythonreadout.db')
    writestatedb = os.path.join(tempfile.mkdtemp(), 'sagapythonwriteout.db')

    sagapythonglobals.startExecuteTransaction = True

    if not ObjectDataBase.opendb(instatedb):
        raise Exception("unable to open input object DB: " + instatedb)
    if not ObjectDataBase.openreaddb(readstatedb):
        raise Exception("unable to open read object DB: " + readstatedb)
    if not ObjectDataBase.openwritedb(writestatedb):
        raise Exception("unable to open write object DB: " + writestatedb)

    t0 = time.perf_counter()
    CreateBaseObjects()
    _BOOTSTRAPPED['bootstrap_time_s'] = time.perf_counter() - t0
    _BOOTSTRAPPED['done'] = True
    return _BOOTSTRAPPED
