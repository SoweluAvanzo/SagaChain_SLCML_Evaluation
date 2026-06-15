const { expect } = require("chai");
const { ethers } = require("hardhat");

// The four scenarios of the paper's case study (Section 5.3), plus the two
// access-control guards (P1 clinician-only, R1 patient-only). Constants match
// the SagaPython workload in ../bench/usecase.py.
describe("ConsentDirective: SLCML consent directive on the EVM", function () {
  const purpose = "treatment";
  const expiry = 1764547200n; // expiry_epoch in bench/usecase.py
  const now = 1700000000n;
  const ehr = ethers.id("offchain://ehr/ref/123");
  let consent, patient, doctor, other;

  beforeEach(async function () {
    [patient, doctor, other] = await ethers.getSigners();
    const Factory = await ethers.getContractFactory("ConsentDirective");
    consent = await Factory.deploy(patient.address, doctor.address, purpose, expiry);
    await consent.waitForDeployment();
  });

  it("S1: valid access for the right purpose, in time, is granted and logged", async function () {
    await expect(consent.connect(doctor).requestAccess(purpose, ehr, now))
      .to.emit(consent, "AccessRequested").withArgs(doctor.address, true);
    expect(await consent.unauthorizedAccessFlag()).to.equal(false);
    expect(await consent.auditCount()).to.equal(1n); // O1: logged
  });

  it("S2: a request for the wrong purpose is denied and raises the flag", async function () {
    await expect(consent.connect(doctor).requestAccess("research", ehr, now))
      .to.emit(consent, "AccessRequested").withArgs(doctor.address, false);
    expect(await consent.unauthorizedAccessFlag()).to.equal(true);
    expect(await consent.auditCount()).to.equal(1n); // still logged
  });

  it("S3: only the patient may revoke consent (R1)", async function () {
    await expect(consent.connect(other).revokeConsent())
      .to.be.revertedWith("R1: only the patient may revoke");
    await consent.connect(patient).revokeConsent();
    expect(await consent.consentActive()).to.equal(false);
    expect(await consent.ehrAccessEnabled()).to.equal(false);
  });

  it("S4: after revocation a later access attempt is denied and logged", async function () {
    await consent.connect(patient).revokeConsent();
    await expect(consent.connect(doctor).requestAccess(purpose, ehr, now))
      .to.emit(consent, "AccessRequested").withArgs(doctor.address, false);
    expect(await consent.unauthorizedAccessFlag()).to.equal(true);
    expect(await consent.auditCount()).to.equal(1n); // every attempt logged
  });

  it("P1 access control: a non-clinician cannot request access", async function () {
    await expect(consent.connect(other).requestAccess(purpose, ehr, now))
      .to.be.revertedWith("P1: only the clinician may request");
  });
});
