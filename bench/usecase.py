"""
usecase.py — healthcare-consent-directive workload generator.

Builds the SLCML healthcare consent directive (position paper Listings 4-6:
ClsAuditTrail implementing obligation O1, ClsConsentDirective implementing
permission P1 and right R1) and instantiates K INDEPENDENT directives in one
transaction, exercising a RequestAccess (P1) and the audit log (O1) on each.

Purpose: each directive is its own pair of persistent objects (consent + audit)
under its own object graph; the K pairs share no mutable state, so the work is
disjoint and (per WP §III) shardable. We measure (a) cost vs K — linear, no
shared-state superlinearity — and (b) object disjointness (objects created ~= 2K).
Verbatim legal logic from the SagaPython Language Reference / position paper.
"""
import itertools

_SEQ = itertools.count(7000)
_UID = itertools.count(0)


def consent_directives(K):
    uid = next(_UID)
    audit = f"ClsAudit{uid}"
    consent = f"ClsConsent{uid}"
    src = f"""
def __hdr():
    return {{
        'accts': CMIConst.SPSystemAccount,
        'seq': {next(_SEQ)},
        'maxGU': 100000000,
        'feePerGU': 1,
        'extraPerGU': 2
    }}


def __CMIClasses():
    @SagaClass(CMIConst.SPClassObject)
    class {audit}:
        entry_count = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite, spftype=int)
        entries = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite, spftype=str)

        @SagaMethod()
        def __init__(self):
            self.entry_count = 0
            self.entries = ""

        @SagaMethod()
        def Append(self, actor_oid: str, timestamp: str, context_oid: str):
            import hashlib
            raw = actor_oid + "|" + timestamp + "|" + context_oid
            h = hashlib.sha256(raw.encode()).hexdigest()
            if self.entries == "":
                self.entries = h
            else:
                self.entries = self.entries + "\\n" + h
            self.entry_count = self.entry_count + 1
            return h

    @SagaClass(CMIConst.SPClassObject, CMIConst.SPClassVerify)
    class {consent}:
        patient = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwriteonce, spftype=str)
        doctor = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwriteonce, spftype=str)
        purpose = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwriteonce, spftype=str)
        expiry_epoch = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwriteonce, spftype=int)
        consent_active = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite, spftype=bool)
        ehr_access_enabled = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite, spftype=bool)
        unauthorized_access_flag = SagaField(
            spff=SPDecConst.spfread | SPDecConst.spfwrite, spftype=bool)

        @SagaMethod()
        def __init__(self, isLocalPrivate: bool, acctlistCall: list,
                     patient_oid: str, doctor_oid: str,
                     purpose: str, expiry_epoch: int):
            self.isLocalPrivate = isLocalPrivate
            self.acctlistCall = acctlistCall
            self.patient = patient_oid
            self.doctor = doctor_oid
            self.purpose = purpose
            self.expiry_epoch = expiry_epoch
            self.consent_active = True
            self.ehr_access_enabled = True
            self.unauthorized_access_flag = False

        @SagaMethod()
        def RevokeConsent(self, caller_oid: str):
            if caller_oid != self.patient:
                raise Exception("R1: only the patient may revoke")
            if not self.consent_active:
                raise Exception("R1: consent already inactive")
            self.consent_active = False
            self.ehr_access_enabled = False

        @SagaMethod()
        def RequestAccess(self, caller_oid: str, requested_purpose: str,
                          ehr_pointer: str, audit_trail: {audit},
                          current_epoch: int):
            if caller_oid != self.doctor:
                raise Exception("P1: only the clinician may request")
            obj_id = ClsObjVar.GetLOID(self).OIDstr()
            audit_trail.Append(caller_oid, str(current_epoch), obj_id)
            purpose_ok = (requested_purpose == self.purpose)
            time_ok = (current_epoch < self.expiry_epoch)
            if not (self.consent_active and self.ehr_access_enabled
                    and time_ok and purpose_ok):
                self.unauthorized_access_flag = True
                return False
            return True


def __body():
    addr = ClsObjVar.GetLOID(
        ClsObjVar(CMIConst.SPSystemAccount)).OIDstr()
    now = 1700000000
    for i in range({K}):
        audit = {audit}.new()[0]
        consent = {consent}.new(
            True, [CMIConst.SPSystemAccount],
            addr, addr, "treatment", 1764547200)[0]
        # P1 permission + O1 obligation (audit) exercised
        consent.RequestAccess(addr, "treatment",
            "offchain://ehr/ref/123", audit, now)
    return True
"""
    return ('consent', {'K': K}, src)
