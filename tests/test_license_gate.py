from rag.crosscutting.security.license_gate import LicenseGate, NullLicenseGate


def test_null_license_gate_always_allows():
    gate: LicenseGate = NullLicenseGate()
    assert gate.can_provision_user() is True


def test_null_license_gate_is_a_license_gate():
    assert isinstance(NullLicenseGate(), LicenseGate)
