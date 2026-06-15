// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ConsentDirective
/// @notice EVM counterpart of the SLCML healthcare consent directive used in the
/// paper's case study: permission P1 (only the clinician may request access,
/// while consent is active, before expiry, for the matching purpose), right R1
/// (only the patient may revoke), and obligation O1 (every access attempt is
/// logged). It mirrors the SagaPython contract in ../bench/usecase.py, with one
/// deliberate difference discussed in the paper: the audit log is an internal
/// array inside the contract rather than a separately addressable object.
contract ConsentDirective {
    address public immutable patient;       // party (fixed at construction)
    address public immutable doctor;        // party (fixed at construction)
    string  public purpose;                 // consideration / term
    uint256 public immutable expiryEpoch;   // time-frame

    bool public consentActive;
    bool public ehrAccessEnabled;
    bool public unauthorizedAccessFlag;

    // O1: append-only audit trail, held inside the contract (internal array)
    struct AuditEntry { address actor; uint256 timestamp; bytes32 context; }
    AuditEntry[] private auditTrail;

    event ConsentRevoked(address caller);
    event AccessRequested(address caller, bool granted);

    constructor(
        address _patient,
        address _doctor,
        string memory _purpose,
        uint256 _expiryEpoch
    ) {
        patient = _patient;
        doctor = _doctor;
        purpose = _purpose;
        expiryEpoch = _expiryEpoch;
        consentActive = true;
        ehrAccessEnabled = true;
        unauthorizedAccessFlag = false;
    }

    /// R1: only the patient may revoke consent.
    function revokeConsent() external {
        require(msg.sender == patient, "R1: only the patient may revoke");
        require(consentActive, "R1: consent already inactive");
        consentActive = false;
        ehrAccessEnabled = false;
        emit ConsentRevoked(msg.sender);
    }

    /// P1: only the clinician may request; O1: every attempt is logged.
    /// Returns true iff access is granted; on denial, raises the flag.
    function requestAccess(
        string calldata requestedPurpose,
        bytes32 ehrPointer,
        uint256 currentEpoch
    ) external returns (bool) {
        require(msg.sender == doctor, "P1: only the clinician may request");
        auditTrail.push(AuditEntry(msg.sender, currentEpoch, ehrPointer)); // O1
        bool purposeOk = keccak256(bytes(requestedPurpose)) == keccak256(bytes(purpose));
        bool timeOk = currentEpoch < expiryEpoch;
        if (!(consentActive && ehrAccessEnabled && timeOk && purposeOk)) {
            unauthorizedAccessFlag = true;
            emit AccessRequested(msg.sender, false);
            return false;
        }
        emit AccessRequested(msg.sender, true);
        return true;
    }

    function auditCount() external view returns (uint256) {
        return auditTrail.length;
    }
}
