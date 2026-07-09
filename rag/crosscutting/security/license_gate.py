from abc import ABC, abstractmethod


class LicenseGate(ABC):
    """Checked before auto-provisioning a user on first SSO/AD login (phase 8 §2's
    seat-cap requirement). Phase 9 (licensing) swaps in a real implementation."""

    @abstractmethod
    def can_provision_user(self) -> bool: ...


class NullLicenseGate(LicenseGate):
    def can_provision_user(self) -> bool:
        return True
