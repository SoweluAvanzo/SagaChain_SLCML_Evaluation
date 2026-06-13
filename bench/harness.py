"""
harness.py — execute SagaPython transaction scripts and measure per-stage cost.

The pipeline mirrors the project's own test fixture
(`tests/base_config.compile_scripts_transaction`) and standalone runner
(`run_healthcare_test.py`), with `time.perf_counter` timers around each stage:

    sign     client-side: AST transform + SHA-256 + Ed25519 sign  (NOT validator cost)
    hdr      header evaluation, account list binding
    tail     hash/signature extraction and binding
    classes  CMI class creation (decorator machinery -> object DB)
    body     transaction body execution (object creation, method dispatch)

Validator-side t_exec  =  hdr + tail + classes + body  (+ signature verification,
measured separately in microbench.py, since the development pipeline does not
verify signatures).

DB operation counts/time are deltas of env_bootstrap.DB_STATS around the
validator stages.
"""
import os
import sys
import time
import shutil
import tempfile
import linecache

from . import env_bootstrap as ENV
from .env_bootstrap import PRODUCT, BASE, DB_STATS

# --- names required inside saga globals (mirrors base_config star-imports) ---
from sagapython.product.sagapythonglobals import *      # noqa: F401,F403
from sagapythonself import *                             # noqa: F401,F403
from baseobjects import *                                # noqa: F401,F403
from cmidecorators import classlist, tempimportlist      # noqa: F401
from spexec import stripfunction                         # noqa: F401
import SPClassTransactionObject                          # noqa: F401
from transactionscriptglobals import *                   # noqa: F401,F403
from accountsignatureverification import *               # noqa: F401,F403
from apps.spclient.__main__ import (                     # noqa: F401
    transfrom_import, remove_comment, transfrom_import_all, addsignatures)
import apps.spclient.__main__ as spclient                # noqa: F401
import sagapythonself                                    # noqa: F401
import sputils                                           # noqa: F401
import cmifilefinder                                     # noqa: F401
from CMIImporter import _install                         # noqa: F401
import spexec as _spexec_direct                          # noqa: F401
import transientobject                                   # noqa: F401
import decimal                                           # noqa: F401
import decimalglobals                                    # noqa: F401

Dec = decimal.Decimal

KEYFILE = os.path.join(PRODUCT, 'systemaccount.signing.key')

_TX_STATE = {'transobj_created': False}


def _build_wrapper(wrapper_name, glbs):
    wrapper_path = os.path.join(PRODUCT, wrapper_name)
    with open(wrapper_path) as sf:
        ws = sf.read()
    src = compile(ws, wrapper_path, 'exec')
    exec(src, glbs)


def run_transaction(source_script, keyfiles=None):
    """Sign and execute one transaction script. Returns timing dict."""
    ENV.bootstrap()
    keyfiles = list(keyfiles or [KEYFILE])

    timings = {}
    t_total0 = time.perf_counter()

    # ---- per-transaction reset (mirrors the fixture) ----
    if os.path.exists(sagapythonself.CMIData.modlib):
        shutil.rmtree(sagapythonself.CMIData.modlib)
    os.makedirs(sagapythonself.CMIData.modlib, exist_ok=True)
    classlist.clear()
    tempimportlist.clear()

    # ---- client-side: transform + sign ----
    t0 = time.perf_counter()
    content = remove_comment(source_script)
    spclient.spimportpath = []
    content = transfrom_import(content)
    signed_script = addsignatures(content, keyfiles)
    timings['sign'] = time.perf_counter() - t0

    decimal.setcontext(decimal.ExtendedContext)
    ncont = decimal.getcontext()
    ncont.rounding = decimalglobals.DecimalData.rounding
    ncont.prec = decimalglobals.DecimalData.decimalprec
    decimal.setcontext(ncont)

    cmifilefinder._installcmicodeloaders()
    _install()

    sagaglobals = globals().copy()
    svmodules = sys.modules.copy()

    glbs, mds = sputils.loadmodulesinit(sagaglobals)
    CMIData.setglobals(glbs, mds)

    # ---- transaction object: create once per process, then reset per tx ----
    if not _TX_STATE['transobj_created']:
        transobj = transientobject.CreateTheSPTransactionObject()[0]
        _TX_STATE['transobj_created'] = True
    else:
        transobj = sagapythonself.ClsObjVar(CMIConst.SPTransactionObject)
    transobj.SetTransient()
    transobj.ResetLDincr()

    glbs['transactionobjectloid'] = CMIConst.SPTransactionObject
    glbs['transactionobject'] = transobj
    CMIData.setglobals(glbs, mds)

    # .new() creates objects under the transaction's transient account
    CMIData.transientAccount = sagapythonself.ClsObjVar.GetLOID(transobj)

    _spexec_direct.trans(transobj)
    if 'sagapython.product.spexec' in sys.modules and \
            sys.modules['sagapython.product.spexec'] is not _spexec_direct:
        sys.modules['sagapython.product.spexec'].trans(transobj)

    db0 = DB_STATS.snapshot()

    hdrname, CMIClassesname = "hdr", "CMIClasses"
    bodyname, tailname = "body", "tail"
    content_functions = sputils.getscripts(
        [hdrname, CMIClassesname, bodyname, tailname], signed_script)

    # ---- HDR ----
    t0 = time.perf_counter()
    hdrglobals, sys.modules = CMIData.getglobals()
    _build_wrapper('sagahdrwrapper.py', hdrglobals)
    hdrscript, hdr = content_functions[hdrname][0], content_functions[hdrname][1]
    hdrinfo = None
    if hdr and hdrscript:
        source = compile(hdr, str(hdrscript), 'exec')
        exec(source, hdrglobals)
        hdrinfo = eval('headerwrapper()', hdrglobals)
        transobj._member(SPClassTransactionObject.SPClassTransactionObjectConst.header).fld = hdrinfo
        acctlist = hdrinfo.get('accts', null)
        if not isinstance(acctlist, list):
            acctlist = [acctlist]
        transobj._member(TXSCGlobals.account).fld = acctlist
        primacct = acctlist[0]
        if hasattr(primacct, 'OIDstr'):
            primacct = primacct.OIDstr()
        transobj._member(TXSCGlobals.primacct).fld = primacct
        hdrinfo[TXSCGlobals.primacct] = primacct
        transobj._member(TXSCGlobals.seqnumber).fld = hdrinfo.get(TXSCGlobals.seqnumber, null)
        transobj._member(TXSCGlobals.maxGU).fld = hdrinfo.get(TXSCGlobals.maxGU, null)
        transobj._member(TXSCGlobals.feePerGU).fld = hdrinfo.get(TXSCGlobals.feePerGU, null)
        transobj._member(TXSCGlobals.extraPerGU).fld = hdrinfo.get(TXSCGlobals.extraPerGU, null)
        sys.modules = svmodules
    timings['hdr'] = time.perf_counter() - t0

    # ---- TAIL ----
    t0 = time.perf_counter()
    tailglobals, sys.modules = CMIData.getglobals()
    _build_wrapper('sagatailwrapper.py', tailglobals)
    tailscript, tail = content_functions[tailname][0], content_functions[tailname][1]
    tailinfo = None
    if tailscript and tail:
        source = compile(tail, str(tailscript), 'exec')
        exec(source, tailglobals)
        tailglobals['rvalue'] = 'rvalue'
        tailglobals['svalue'] = 'svalue'
        tailinfo = eval('tailwrapper()', tailglobals)
        transobj._member(SPClassTransactionObject.SPClassTransactionObjectConst.tail).fld = tailinfo
        scripthash = tailinfo.get(TXSCGlobals.hash, null)
        transobj._member(TXSCGlobals.hash).fld = scripthash
        siglist = tailinfo.get(TXSCGlobals.sig, null)
        if not isinstance(siglist, list):
            siglist = [siglist]
        transobj._member(TXSCGlobals.sig).fld = siglist
    timings['tail'] = time.perf_counter() - t0

    # ---- CLASSES ----
    t0 = time.perf_counter()
    classes = classesscript = classesinfo = None
    try:
        classesscript, classes = (content_functions[CMIClassesname][0],
                                  content_functions[CMIClassesname][1])
    except Exception:
        pass
    if classes is not None and classesscript is not None:
        cmiclassesglobals, sys.modules = CMIData.getglobals()
        _build_wrapper('sagaclasseswrapper.py', cmiclassesglobals)
        classes, classesscript = stripfunction(classes, classesscript)
        source = compile(classes, str(classesscript), 'exec')
        linecache.cache[str(classesscript)] = (
            len(classes), None, classes.splitlines(True), classesscript)
        exec(source, cmiclassesglobals)
        classesinfo = eval('classeswrapper()', cmiclassesglobals)
        transobj._member(SPClassTransactionObject.SPClassTransactionObjectConst.classlist).fld = classesinfo
        for ci in classesinfo:
            cmiclassesglobals[ci[0]] = ci[1]
        CMIData.setglobals(cmiclassesglobals, mds)
        sys.modules = svmodules
    timings['classes'] = time.perf_counter() - t0

    # ---- BODY ----
    t0 = time.perf_counter()
    bodyscript, body = content_functions[bodyname][0], content_functions[bodyname][1]
    result = None
    if bodyscript and body:
        bodyglobals, sys.modules = CMIData.getglobals()
        if hdrinfo:
            bodyglobals['hdrinfo'] = hdrinfo
        if tailinfo:
            bodyglobals['tailinfo'] = tailinfo
        if classesinfo:
            for data in classesinfo:
                bodyglobals[data[0]] = data[1]
        _build_wrapper('sagabodywrapper.py', bodyglobals)
        source = compile(body, str(bodyscript), 'exec')
        exec(source, bodyglobals)
        result = eval('bodywrapper()', bodyglobals, bodyglobals)
    timings['body'] = time.perf_counter() - t0

    db1 = DB_STATS.snapshot()

    timings['validator_total'] = (timings['hdr'] + timings['tail'] +
                                  timings['classes'] + timings['body'])
    timings['wall_total'] = time.perf_counter() - t_total0
    timings['result'] = result
    timings['db'] = {k: db1[k] - db0[k] for k in db1}
    timings['script_bytes'] = len(signed_script)

    # objects created in the in-memory state table by this transaction
    import ObjectTable as _OT
    n_now = len(_OT.statetable)
    timings['statetable_size'] = n_now
    timings['objects_delta'] = n_now - _TX_STATE.get('last_statetable', n_now)
    _TX_STATE['last_statetable'] = n_now
    return timings
