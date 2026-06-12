"""
src/tlo/tlo_service.py

WHAT THIS FILE DOES:
  In the real Athena system, we call TransUnion TLO API to verify
  whether an applicant owns their home. Homeownership is important
  because homeowners are statistically less likely to default.

  Since we can't call the real API in this project, we MOCK it.
  Mocking = writing a fake function that behaves exactly like the
  real API would, but returns dummy data.

  THIS IS A REAL SKILL — in professional Python development,
  you mock external APIs in tests and development all the time.

WHAT MOCKING TEACHES YOU:
  - How to structure an API call with requests library
  - How to handle timeouts and errors from external services
  - How to write code that works with either real or fake data
  - The concept of "dependency injection"
"""

import random
import time
from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────
# DATA CLASS — what TLO returns for one applicant
# ─────────────────────────────────────────────────────────────
@dataclass
class TLOResponse:
    application_id: int
    is_homeowner:   bool
    years_at_property: float
    property_state:    str
    source:            str   # "TLO_API" or "MOCK" or "ADM_OVERRIDE"
    success:           bool  # False if the API call failed


# ─────────────────────────────────────────────────────────────
# MOCK TLO SERVICE
# ─────────────────────────────────────────────────────────────
class TLOService:
    """
    Simulates the TransUnion TLO API.

    In production you would replace _mock_api_call() with a real
    HTTP request using the requests library like this:

        import requests
        response = requests.post(
            url     = "https://api.transunion.com/tlo/homeownership",
            headers = {"Authorization": f"Bearer {api_key}"},
            json    = {"ssn": applicant_ssn, "name": full_name},
            timeout = 5
        )
        data = response.json()

    For now we simulate the same behavior without real credentials.
    """

    # Simulate realistic API latency (milliseconds)
    MOCK_LATENCY_MS = 50

    # Chance that the mock API "fails" — to simulate real-world errors
    MOCK_FAILURE_RATE = 0.02   # 2% failure rate

    def __init__(self, use_mock: bool = True):
        """
        use_mock = True  → use fake data (development/testing)
        use_mock = False → use real API (production)
        """
        self.use_mock = use_mock

    # ── MOCK: Simulates what TLO API would return ──────────────
    def _mock_api_call(self, application_id: int,
                       full_name: str,
                       state: str) -> TLOResponse:
        """
        Fake API call that returns realistic-looking data.
        Uses application_id as a seed so results are consistent.
        """
        # Simulate network latency
        time.sleep(self.MOCK_LATENCY_MS / 1000)

        # Simulate occasional API failure
        random.seed(application_id * 7)   # deterministic per app
        if random.random() < self.MOCK_FAILURE_RATE:
            return TLOResponse(
                application_id    = application_id,
                is_homeowner      = False,
                years_at_property = 0.0,
                property_state    = state,
                source            = "MOCK",
                success           = False,
            )

        # 35% chance of homeownership — realistic US average
        is_homeowner      = random.random() < 0.35
        years_at_property = round(random.uniform(0.5, 20.0), 1) if is_homeowner else 0.0

        return TLOResponse(
            application_id    = application_id,
            is_homeowner      = is_homeowner,
            years_at_property = years_at_property,
            property_state    = state,
            source            = "MOCK",
            success           = True,
        )

    # ── PUBLIC: Call TLO for one applicant ─────────────────────
    def check_homeownership(self, application_id: int,
                            full_name: str,
                            state: str) -> TLOResponse:
        """
        Main method — call this for each applicant.
        Returns a TLOResponse regardless of mock or real.
        """
        if self.use_mock:
            return self._mock_api_call(application_id, full_name, state)

        # ── Real API call would go here ────────────────────────
        # import requests
        # try:
        #     response = requests.post(
        #         url     = "https://api.transunion.com/tlo",
        #         headers = {"Authorization": f"Bearer {self.api_key}"},
        #         json    = {"name": full_name, "state": state},
        #         timeout = 5
        #     )
        #     data = response.json()
        #     return TLOResponse(
        #         application_id    = application_id,
        #         is_homeowner      = data["homeowner"],
        #         years_at_property = data["years"],
        #         property_state    = state,
        #         source            = "TLO_API",
        #         success           = True,
        #     )
        # except requests.exceptions.Timeout:
        #     print(f"  ⚠️  TLO API timeout for App {application_id}")
        #     return TLOResponse(..., success=False)
        raise NotImplementedError("Real TLO API not configured")

    # ── Check all applications ─────────────────────────────────
    def check_all(self, enriched_apps: list) -> dict:
        """Returns dict: { application_id: TLOResponse }"""
        results   = {}
        homeowner = 0
        failed    = 0

        for app in enriched_apps:
            a      = app.enriched_app.application
            result = self.check_homeownership(
                application_id = a.application_id,
                full_name      = a.full_name,
                state          = a.state,
            )
            results[a.application_id] = result

            if result.success and result.is_homeowner:
                homeowner += 1
            if not result.success:
                failed += 1

        print(f"TLO check complete — {homeowner} homeowners found, {failed} API failures")
        return results