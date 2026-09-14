"""The always-available fallback: a secret-free description the user enters themselves.

It changes nothing, claims nothing, and is what every client without proven support gets.
"""

from open_transcribe.desktop.clients.base import (
    ExistingEntry,
    RegistrationPlan,
    ServerRegistration,
    SupportStatus,
)

DOCUMENTATION_URL = "https://fbossiere.github.io/open-transcribe-mcp/desktop/"


class ManualRegistrationAdapter:
    adapter_id = "manual"
    display_name = "Another MCP client"
    support_status = SupportStatus.MANUAL_ONLY
    restart_required = True

    def detect(self) -> bool:
        return True

    def inventory(self) -> list[ExistingEntry]:
        return []

    def plan(
        self, registration: ServerRegistration, *, owned: frozenset[str], takeover: bool
    ) -> RegistrationPlan:
        return RegistrationPlan(
            adapter_id=self.adapter_id,
            registration=registration,
            target_description=DOCUMENTATION_URL,
        )

    def apply(self, plan: RegistrationPlan) -> None:
        """Nothing to apply: the user registers the server in their own client."""

    def readback(self, name: str) -> ExistingEntry | None:
        return None

    def remove(self, name: str) -> bool:
        return False
