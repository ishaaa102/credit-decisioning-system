"""
src/rules_engine/dealer_rules.py

WHAT THIS FILE DOES:
  Each dealer has DIFFERENT thresholds loaded from dealer_rules.json.
  Dealer D001 might accept credit score 620,
  but Dealer D004 requires 700 minimum.

  This file:
    - Loads the dealer rules from the JSON config file
    - Checks if this application meets THAT dealer's specific rules
    - Returns pass/fail with the exact rule that failed

WHY JSON CONFIG?
  In real systems, rules come from a database or config file — NOT
  hardcoded in Python. That way, business teams can change rules
  without touching code. This is called "config-driven logic".
"""

import json
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────
# DATA CLASS — result of running dealer rules
# ─────────────────────────────────────────────────────────────
@dataclass
class DealerRuleResult:
    application_id: int
    dealer_id:      str
    passed:         bool
    failed_rules:   list = field(default_factory=list)   # which rules failed
    dealer_tier:    str  = ""


# ─────────────────────────────────────────────────────────────
# DEALER RULES ENGINE
# ─────────────────────────────────────────────────────────────
class DealerRules:

    def __init__(self, config_path: str = "data/dealer_rules.json"):
        self.config_path = config_path
        self.rules       = self._load_rules()

    # ── Load rules from JSON file ──────────────────────────────
    def _load_rules(self) -> dict:
        with open(self.config_path, "r") as f:
            rules = json.load(f)
        print(f"Loaded dealer rules for {len(rules)} dealers from '{self.config_path}'")
        return rules

    # ── Get rules for one dealer (with safe fallback) ──────────
    def _get_dealer_config(self, dealer_id: str) -> dict:
        if dealer_id in self.rules:
            return self.rules[dealer_id]

        # Unknown dealer — use the most conservative defaults
        print(f"Unknown dealer '{dealer_id}' — using default rules")
        return {
            "dealer_name"       : "Unknown Dealer",
            "tier"              : "Standard",
            "min_credit_score"  : 650,
            "max_loan_amount"   : 30000,
            "max_dti_ratio"     : 0.43,
            "min_annual_income" : 25000,
            "allow_bankruptcies": False,
        }

    # ── Check one application against its dealer's rules ───────
    def run(self, enriched_app) -> DealerRuleResult:
        """
        enriched_app = FullyEnrichedApplication from Phase 2.
        We check it against the rules for its specific dealer.
        """
        app       = enriched_app.enriched_app.application
        bureau    = enriched_app.enriched_app
        dealer_id = app.dealer_id
        config    = self._get_dealer_config(dealer_id)

        failed_rules = []

        # ── Rule 1: Minimum credit score for this dealer ────────
        if bureau.credit_score < config["min_credit_score"]:
            failed_rules.append(
                f"Credit score {bureau.credit_score} below dealer minimum {config['min_credit_score']}"
            )

        # ── Rule 2: Maximum loan amount for this dealer ─────────
        if app.loan_amount > config["max_loan_amount"]:
            failed_rules.append(
                f"Loan amount ${app.loan_amount:,.0f} exceeds dealer max ${config['max_loan_amount']:,.0f}"
            )

        # ── Rule 3: Maximum DTI ratio for this dealer ───────────
        if bureau.debt_to_income_ratio > config["max_dti_ratio"]:
            failed_rules.append(
                f"DTI {bureau.debt_to_income_ratio:.1%} exceeds dealer max {config['max_dti_ratio']:.1%}"
            )

        # ── Rule 4: Minimum income for this dealer ──────────────
        if app.annual_income < config["min_annual_income"]:
            failed_rules.append(
                f"Income ${app.annual_income:,.0f} below dealer minimum ${config['min_annual_income']:,.0f}"
            )

        # ── Rule 5: Bankruptcy restriction ─────────────────────
        if not config["allow_bankruptcies"] and bureau.bankruptcies > 0:
            failed_rules.append(
                f"Dealer does not allow bankruptcies — applicant has {bureau.bankruptcies}"
            )

        passed = len(failed_rules) == 0

        return DealerRuleResult(
            application_id = app.application_id,
            dealer_id      = dealer_id,
            passed         = passed,
            failed_rules   = failed_rules,
            dealer_tier    = config["tier"],
        )

    def run_all(self, enriched_apps: list) -> dict:
        """Returns dict: { application_id: DealerRuleResult }"""
        results = {}
        passed  = 0
        failed  = 0

        for app in enriched_apps:
            result = self.run(app)
            results[app.application_id] = result
            if result.passed:
                passed += 1
            else:
                failed += 1

        print(f"Dealer rules complete — {passed} passed, {failed} failed")
        return results