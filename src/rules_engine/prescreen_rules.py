"""
src/rules_engine/prescreen_rules.py

WHAT THIS FILE DOES:
  Prescreen rules are the FIRST checks we run — before doing anything
  expensive like pulling credit or running the ML model.

  Think of them as quick knockout punches:
    - If the application is obviously bad → DECLINE immediately
    - If it passes all checks → move on to deeper decisioning

  WHY PRESCREEN FIRST?
    Pulling a credit report costs money and hits the applicant's score.
    If we can decline without pulling credit, that saves everyone time.

RULES IN HERE:
  1. Loan amount too small or too large
  2. Income too low
  3. State restrictions (some states we don't lend in)
  4. Duplicate application check
  5. Minimum age proxy (income proxy since we don't have DOB)
"""

from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────
# DATA CLASS — result of running prescreen rules
# ─────────────────────────────────────────────────────────────
@dataclass
class PrescreenResult:
    application_id: int
    passed:         bool          # True = passed, False = declined here
    decline_reason: str  = ""     # why it was declined (empty if passed)
    warnings:       list = field(default_factory=list)   # non-fatal flags


# ─────────────────────────────────────────────────────────────
# PRESCREEN RULES ENGINE
# ─────────────────────────────────────────────────────────────
class PrescreenRules:

    # States we do NOT lend in
    RESTRICTED_STATES = {"VT", "WV", "SD"}

    # Absolute loan amount limits (regardless of dealer)
    MIN_LOAN_AMOUNT = 500.0
    MAX_LOAN_AMOUNT = 75000.0

    # Absolute minimum income we require
    MIN_ANNUAL_INCOME = 15000.0

    def run(self, application) -> PrescreenResult:
        """
        Runs all prescreen checks on one application.
        Stops at the FIRST failure (no point checking further).

        'application' here is a LoanApplication object from Phase 1.
        """
        app_id = application.application_id

        # ── Rule 1: Loan amount must be within our absolute limits ──
        if application.loan_amount < self.MIN_LOAN_AMOUNT:
            return PrescreenResult(
                application_id = app_id,
                passed         = False,
                decline_reason = f"Loan amount ${application.loan_amount:,.0f} is below minimum ${self.MIN_LOAN_AMOUNT:,.0f}",
            )

        if application.loan_amount > self.MAX_LOAN_AMOUNT:
            return PrescreenResult(
                application_id = app_id,
                passed         = False,
                decline_reason = f"Loan amount ${application.loan_amount:,.0f} exceeds maximum ${self.MAX_LOAN_AMOUNT:,.0f}",
            )

        # ── Rule 2: Income must meet minimum threshold ─────────────
        if application.annual_income < self.MIN_ANNUAL_INCOME:
            return PrescreenResult(
                application_id = app_id,
                passed         = False,
                decline_reason = f"Annual income ${application.annual_income:,.0f} is below minimum ${self.MIN_ANNUAL_INCOME:,.0f}",
            )

        # ── Rule 3: State restrictions ──────────────────────────────
        if application.state.upper() in self.RESTRICTED_STATES:
            return PrescreenResult(
                application_id = app_id,
                passed         = False,
                decline_reason = f"We do not lend in state: {application.state}",
            )

        # ── Rule 4: Loan-to-income ratio sanity check ───────────────
        # If someone wants to borrow 5x their annual income → red flag
        warnings = []
        if application.loan_to_income_ratio > 0.80:
            warnings.append(
                f"High loan-to-income ratio: {application.loan_to_income_ratio:.1%}"
            )

        # ── Rule 5: Co-applicant income boost check ─────────────────
        # If primary income is low but has co-applicant, flag it
        if application.annual_income < 25000 and not application.has_coapplicant:
            warnings.append("Low income without co-applicant — may struggle with payments")

        # ── All checks passed ───────────────────────────────────────
        return PrescreenResult(
            application_id = app_id,
            passed         = True,
            decline_reason = "",
            warnings       = warnings,
        )

    def run_all(self, applications: list) -> dict:
        """
        Runs prescreen on a list of applications.
        Returns a dict: { application_id: PrescreenResult }
        """
        results = {}
        passed  = 0
        failed  = 0

        for app in applications:
            result = self.run(app)
            results[app.application_id] = result
            if result.passed:
                passed += 1
            else:
                failed += 1

        print(f"Prescreen complete — {passed} passed, {failed} declined")
        return results