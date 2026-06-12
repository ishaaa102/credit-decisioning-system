"""
src/rules_engine/decision_rules.py

WHAT THIS FILE DOES:
  After passing prescreen and dealer rules, this is where we determine:
    1. What TIER is this applicant? (A, B, C, D)
       Tier = how creditworthy they are
    2. What BID AMOUNT do we offer? (how much we'll actually lend)
       Bid = min(loan requested, ACA from model, dealer max)
    3. What INTEREST RATE tier do they qualify for?

  TIER TABLE:
    Tier A  → Credit 720+, DTI <0.30, no delinquencies  → best rates
    Tier B  → Credit 660+, DTI <0.40, max 1 delinquency → standard rates
    Tier C  → Credit 600+, DTI <0.50, max 2 delinquency → higher rates
    Tier D  → Everything else that still passed prescreen → highest rates

  BID AMOUNT:
    = min(what they asked for, what model says they can handle, dealer max)
    If bid < $1000 → decline (not worth processing)
"""

from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────
# DATA CLASS — result of decision rules
# ─────────────────────────────────────────────────────────────
@dataclass
class DecisionRuleResult:
    application_id: int
    tier:           str     # "A", "B", "C", "D", or "DECLINE"
    bid_amount:     float   # how much we'll lend
    interest_band:  str     # "Low", "Medium", "High", "Very High"
    passed:         bool
    decline_reason: str = ""


# ─────────────────────────────────────────────────────────────
# DECISION RULES ENGINE
# ─────────────────────────────────────────────────────────────
class DecisionRules:

    # Interest rate band by tier
    INTEREST_BANDS = {
        "A": "Low",
        "B": "Medium",
        "C": "High",
        "D": "Very High",
    }

    # Minimum bid we'll process
    MIN_BID = 1000.0

    def _determine_tier(self, credit_score: int,
                        dti: float,
                        delinquencies: int,
                        risk_score: float) -> str:
        """
        Works top-down — if you qualify for A, you get A.
        Otherwise tries B, then C, then D.
        """
        # Tier A — best applicants
        if (credit_score >= 720
                and dti <= 0.30
                and delinquencies == 0
                and risk_score < 0.20):
            return "A"

        # Tier B — good applicants
        if (credit_score >= 660
                and dti <= 0.40
                and delinquencies <= 1
                and risk_score < 0.40):
            return "B"

        # Tier C — acceptable applicants
        if (credit_score >= 600
                and dti <= 0.50
                and delinquencies <= 2
                and risk_score < 0.60):
            return "C"

        # Tier D — everyone else who passed prescreen
        return "D"

    def _calculate_bid(self, requested: float,
                       aca: float,
                       dealer_max: float,
                       tier: str) -> float:
        """
        Bid = minimum of (requested, ACA, dealer max)
        Then apply a tier-based reduction for riskier tiers.

        Tier A → full amount
        Tier B → 90% of calculated max
        Tier C → 75% of calculated max
        Tier D → 60% of calculated max
        """
        tier_multipliers = {"A": 1.00, "B": 0.90, "C": 0.75, "D": 0.60}

        # Start with the lowest of the three limits
        base_bid = min(requested, aca, dealer_max)

        # Apply tier multiplier
        bid = base_bid * tier_multipliers[tier]

        return round(bid, 2)

    def run(self, enriched_app, risk_score_obj, dealer_result) -> DecisionRuleResult:
        """
        enriched_app    = FullyEnrichedApplication (Phase 2)
        risk_score_obj  = RiskScore (Phase 2)
        dealer_result   = DealerRuleResult (Phase 3 - dealer rules)
        """
        bureau  = enriched_app.enriched_app
        app     = bureau.application
        app_id  = app.application_id

        # Determine tier
        tier = self._determine_tier(
            credit_score  = bureau.credit_score,
            dti           = bureau.debt_to_income_ratio,
            delinquencies = bureau.delinquencies_last_2yr,
            risk_score    = risk_score_obj.risk_score,
        )

        # Get dealer max for bid calculation
        # dealer_result.passed means we already know it's within dealer limits
        # We use ACA from risk model as the ceiling
        dealer_max_map = {"D001": 40000, "D002": 35000,
                          "D003": 25000, "D004": 50000}
        dealer_max = dealer_max_map.get(app.dealer_id, 30000)

        bid = self._calculate_bid(
            requested  = app.loan_amount,
            aca        = risk_score_obj.aca,
            dealer_max = dealer_max,
            tier       = tier,
        )

        # If bid is too low — decline
        if bid < self.MIN_BID:
            return DecisionRuleResult(
                application_id = app_id,
                tier           = "DECLINE",
                bid_amount     = 0.0,
                interest_band  = "",
                passed         = False,
                decline_reason = f"Calculated bid ${bid:,.0f} is below minimum ${self.MIN_BID:,.0f}",
            )

        return DecisionRuleResult(
            application_id = app_id,
            tier           = tier,
            bid_amount     = bid,
            interest_band  = self.INTEREST_BANDS[tier],
            passed         = True,
        )

    def run_all(self, enriched_apps, risk_scores, dealer_results) -> dict:
        """Returns dict: { application_id: DecisionRuleResult }"""
        # Build quick lookup dicts by application_id
        score_map  = {s.application_id: s for s in risk_scores}
        dealer_map = dealer_results   # already a dict by app_id

        results = {}
        tier_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "DECLINE": 0}

        for app in enriched_apps:
            app_id = app.application_id
            result = self.run(
                enriched_app   = app,
                risk_score_obj = score_map[app_id],
                dealer_result  = dealer_map[app_id],
            )
            results[app_id] = result
            tier_counts[result.tier] = tier_counts.get(result.tier, 0) + 1

        print(f"Decision rules complete — Tiers: {tier_counts}")
        return results