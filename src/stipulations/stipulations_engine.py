"""
src/stipulations/stipulations_engine.py

WHAT THIS FILE DOES:
  Stipulations = CONDITIONS attached to an approval.
  "You're approved, BUT you need to prove X first."

  Common examples:
    - Income Verification  → we need pay stubs or bank statements
    - Homeownership Proof  → we need a mortgage statement
    - Identity Verification → we need a government ID

  HOW IT WORKS:
    1. Application is approved (passed all rules)
    2. Stipulations engine checks if any conditions apply
    3. If yes → decision becomes "Pending" with a list of stips
    4. Once applicant provides documents → human reviews → final approval

  THINK OF IT AS: the "approved but not yet funded" zone.
"""

from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────
# DATA CLASS — one stipulation
# ─────────────────────────────────────────────────────────────
@dataclass
class Stipulation:
    code:        str    # short code like "INCOME_VERIFY"
    description: str    # human-readable: "Income Verification Required"
    required:    bool   # True = must resolve before funding
                        # False = preferred but not blocking


# ─────────────────────────────────────────────────────────────
# DATA CLASS — result of stipulations check
# ─────────────────────────────────────────────────────────────
@dataclass
class StipulationResult:
    application_id:      int
    stipulations:        list = field(default_factory=list)   # list of Stipulation
    has_required_stips:  bool = False    # True = must go to Pending

    @property
    def count(self) -> int:
        return len(self.stipulations)

    def describe(self) -> str:
        if not self.stipulations:
            return "No stipulations"
        lines = [f"  {s.code}: {s.description} ({'REQUIRED' if s.required else 'optional'})"
                 for s in self.stipulations]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# STIPULATIONS ENGINE
# ─────────────────────────────────────────────────────────────
class StipulationsEngine:

    # Income thresholds that trigger verification
    INCOME_VERIFY_THRESHOLD       = 75000.0   # high income needs proof
    INCOME_LOW_THRESHOLD          = 30000.0   # low income needs proof too
    SELF_EMPLOYED_LOAN_THRESHOLD  = 15000.0   # self-employed + big loan

    def run(self, enriched_app, tlo_response, decision_result) -> StipulationResult:
        """
        Checks what stipulations apply to this approved application.

        enriched_app    = FullyEnrichedApplication
        tlo_response    = TLOResponse (homeownership check)
        decision_result = DecisionRuleResult (tier, bid amount)
        """
        app     = enriched_app.enriched_app.application
        bureau  = enriched_app.enriched_app
        adm     = enriched_app.adm_data
        app_id  = app.application_id

        stips = []

        # ── Stip 1: Income Verification ────────────────────────
        # Required if income is very high (fraud risk) or
        # very low (ability to pay risk) or self-employed with big loan
        needs_income_verify = (
            app.annual_income > self.INCOME_VERIFY_THRESHOLD
            or app.annual_income < self.INCOME_LOW_THRESHOLD
            or (adm.employment_status == "Self-Employed"
                and app.loan_amount > self.SELF_EMPLOYED_LOAN_THRESHOLD)
        )
        if needs_income_verify:
            stips.append(Stipulation(
                code        = "INCOME_VERIFY",
                description = "Income Verification Required — please provide recent pay stubs or bank statements",
                required    = True,
            ))

        # ── Stip 2: Homeownership Proof ─────────────────────────
        # If TLO says they're a homeowner but ADM doesn't confirm it,
        # OR the loan is large enough that homeownership matters
        tlo_says_homeowner = tlo_response.success and tlo_response.is_homeowner
        if tlo_says_homeowner and app.loan_amount > 20000:
            stips.append(Stipulation(
                code        = "HOMEOWNERSHIP_PROOF",
                description = "Homeownership Verification — please provide mortgage statement or property tax bill",
                required    = True,
            ))

        # ── Stip 3: Employment Verification ────────────────────
        # If unemployed but still approved (maybe has other income)
        if adm.employment_status == "Unemployed":
            stips.append(Stipulation(
                code        = "EMPLOYMENT_VERIFY",
                description = "Employment Verification — please provide proof of alternative income source",
                required    = True,
            ))

        # ── Stip 4: Identity Verification ──────────────────────
        # Required for large loans or first-time customers
        if app.loan_amount > 30000 or adm.previous_loans == 0:
            stips.append(Stipulation(
                code        = "ID_VERIFY",
                description = "Identity Verification Required — please provide government-issued photo ID",
                required    = True,
            ))

        # ── Stip 5: Prior Default Warning ──────────────────────
        # Non-blocking but logged — human reviewer sees it
        if adm.previous_defaults > 0:
            stips.append(Stipulation(
                code        = "PRIOR_DEFAULT_NOTE",
                description = f"Applicant has {adm.previous_defaults} prior default(s) on record — for reviewer awareness",
                required    = False,
            ))

        has_required = any(s.required for s in stips)

        return StipulationResult(
            application_id     = app_id,
            stipulations       = stips,
            has_required_stips = has_required,
        )

    def run_all(self, enriched_apps, tlo_results, decision_results) -> dict:
        """Returns dict: { application_id: StipulationResult }"""
        results       = {}
        with_stips    = 0
        without_stips = 0

        for app in enriched_apps:
            app_id = app.application_id
            result = self.run(
                enriched_app    = app,
                tlo_response    = tlo_results[app_id],
                decision_result = decision_results[app_id],
            )
            results[app_id] = result
            if result.count > 0:
                with_stips += 1
            else:
                without_stips += 1

        print(f"Stipulations complete — {with_stips} with stips, {without_stips} clean")
        return results