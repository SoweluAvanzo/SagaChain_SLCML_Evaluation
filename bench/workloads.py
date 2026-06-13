"""
workloads.py — parametric SagaPython transaction-script generators.

Each generator returns (name, params, source) where source is a complete
transaction script (__hdr / __CMIClasses / __body). Class names are unique
per transaction so repeated runs in one process never collide in the object DB.

Workload set (chosen to expose marginal costs by linear regression):
  minimal          floor cost of the transaction pipeline
  create(K)        K persistent-object instantiations of a simple class
  methods(M)       M CMI method calls on one persistent object
  fields(M)        M CMI field write+read pairs on one persistent object
  obj2obj(M)       M object-to-object method calls (A's method invokes B's)
"""
import itertools

_SEQ = itertools.count(2000)
_UID = itertools.count(0)


def _hdr():
    return f"""
def __hdr():
    hdr = {{
        'accts': CMIConst.SPSystemAccount,
        'seq': {next(_SEQ)},
        'maxGU': 1000000,
        'feePerGU': 1,
        'extraPerGU': 2
    }}
    return hdr
"""


def minimal():
    src = _hdr() + """

def __CMIClasses():
    pass


def __body():
    return True
"""
    return ('minimal', {}, src)


def create_objects(K):
    uid = next(_UID)
    cls = f"ClsBenchCreate{uid}"
    src = _hdr() + f"""

def __CMIClasses():
    @SagaClass(CMIConst.SPClassObject)
    class {cls}:
        count = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite,
            spftype=int)

        @SagaMethod()
        def __init__(self, initcount: int):
            self.count = initcount


def __body():
    for i in range({K}):
        obj = {cls}.new(i)[0]
    return True
"""
    return ('create', {'K': K}, src)


def method_calls(M):
    uid = next(_UID)
    cls = f"ClsBenchMeth{uid}"
    src = _hdr() + f"""

def __CMIClasses():
    @SagaClass(CMIConst.SPClassObject)
    class {cls}:
        count = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite,
            spftype=int)

        @SagaMethod()
        def __init__(self):
            self.count = 0

        @SagaMethod()
        def Inc(self, n: int) -> int:
            self.count = self.count + n
            return self.count


def __body():
    obj = {cls}.new()[0]
    for i in range({M}):
        obj.Inc(1)
    return True
"""
    return ('methods', {'M': M}, src)


def field_ops(M):
    uid = next(_UID)
    cls = f"ClsBenchFld{uid}"
    src = _hdr() + f"""

def __CMIClasses():
    @SagaClass(CMIConst.SPClassObject)
    class {cls}:
        count = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite,
            spftype=int)

        @SagaMethod()
        def __init__(self):
            self.count = 0


def __body():
    obj = {cls}.new()[0]
    for i in range({M}):
        obj.count = i
        x = obj.count
    return True
"""
    return ('fields', {'M': M}, src)


def obj_to_obj(M):
    uid = next(_UID)
    cls_a = f"ClsBenchA{uid}"
    cls_b = f"ClsBenchB{uid}"
    src = _hdr() + f"""

def __CMIClasses():
    @SagaClass(CMIConst.SPClassObject)
    class {cls_b}:
        hits = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite,
            spftype=int)

        @SagaMethod()
        def __init__(self):
            self.hits = 0

        @SagaMethod()
        def Pong(self) -> int:
            self.hits = self.hits + 1
            return self.hits

    @SagaClass(CMIConst.SPClassObject)
    class {cls_a}:
        sent = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite,
            spftype=int)

        @SagaMethod()
        def __init__(self):
            self.sent = 0

        @SagaMethod()
        def Ping(self, other: {cls_b}) -> int:
            self.sent = self.sent + 1
            return other.Pong()


def __body():
    a = {cls_a}.new()[0]
    b = {cls_b}.new()[0]
    for i in range({M}):
        a.Ping(b)
    return True
"""
    return ('obj2obj', {'M': M}, src)
