"""
src/decision/decision_engine.py

WHAT THIS FILE DOES:
  This is the BRAIN that ties ALL phases together into one clean pipeline.
  You give it a list of fully enriched applications and it runs every
  step — rules, TLO, stipulations — and returns ONE structured result
  per application.

  The result looks like:
  {
    "application_id": 84,
    "applicant_name": "John Doe",
    "decision":       "Auto Approved",
    "tier":           "A",
    "bid_amount":     15000.0,
    "risk_score":     0.23,
    "risk_label":     "Low Risk",
    "stipulations":   ["Income Verification Required"],
    "decline_reasons":[]
  }

WHAT IS NEW HERE:
  - A proper FinalDecision dataclass with all fields
  - A DecisionEngine class that runs the whole pipeline
  - Counter-offer logic (we offer less than they asked for)
  - A clean method: engine.decide(apps) → list[FinalDecision]

THINK OF IT AS: the clean public interface to the whole system.
In Phase 5 (API), FastAPI will call this one class and get back results.
"""

from dataclasses import dataclass, field
from datetime    import datetime

from src.rules_engine.prescreen_rules     import PrescreenRules
from src.rules_engine.dealer_rules        import DealerRules
from src.rules_engine.decision_rules      import DecisionRules
from src.tlo.tlo_service                  import TLOService
from src.stipulations.stipulations_engine import StipulationsEngine


# ─────────────────────────────────────────────────────────────
# DECISION OUTCOMES
# ─────────────────────────────────────────────────────────────
class Outcome:
    AUTO_APPROVE   = "Auto Approved"
    PENDING        = "Pending"
    DECLINE        = "Decline"
    COUNTER_OFFER  = "Counter Offer"


# ─────────────────────────────────────────────────────────────
# DATA CLASS — the final structured result for ONE application
# ─────────────────────────────────────────────────────────────
@dataclass
class FinalDecision:
    # ── Identity ───────────────────────────────────────────────
    application_id:  int
    applicant_name:  str
    dealer_id:       str
    loan_type:       str
    loan_requested:  float

    # ── The Decision ───────────────────────────────────────────
    decision:        str      # one of the Outcome values above
    tier:            str      # "A", "B", "C", "D", or "N/A"
    bid_amount:      float    # how much we'll actually lend
    interest_band:   str      # "Low", "Medium", "High", "Very High"

    # ── Risk ───────────────────────────────────────────────────
    risk_score:      float
    risk_label:      str

    # ── Supporting info ────────────────────────────────────────
    stipulations:    list = field(default_factory=list)    # list of strings
    decline_reasons: list = field(default_factory=list)    # list of strings
    warnings:        list = field(default_factory=list)    # non-fatal flags
    is_counter_offer: bool = False   # True if bid < amount requested
    decided_at:      str  = ""       # timestamp

    def to_dict(self) -> dict:
        """
        Converts this object to a plain Python dictionary.
        This is what gets saved to the database and returned by the API.
        """
        return {
            "application_id":  self.application_id,
            "applicant_name":  self.applicant_name,
            "dealer_id":       self.dealer_id,
            "loan_type":       self.loan_type,
            "loan_requested":  self.loan_requested,
            "decision":        self.decision,
            "tier":            self.tier,
            "bid_amount":      self.bid_amount,
            "interest_band":   self.interest_band,
            "risk_score":      self.risk_score,
            "risk_label":      self.risk_label,
            "stipulations":    self.stipulations,
            "decline_reasons": self.decline_reasons,
            "warnings":        self.warnings,
            "is_counter_offer": self.is_counter_offer,
            "decided_at":      self.decided_at,
        }


# ─────────────────────────────────────────────────────────────
# DECISION ENGINE — runs everything, returns FinalDecision list
# ─────────────────────────────────────────────────────────────
class DecisionEngine:

    # Counter-offer threshold:
    # If bid is less than this % of requested → flag as counter offer
    COUNTER_OFFER_THRESHOLD = 0.90   # 90% — if we offer less than 90% requested

    def __init__(self):
        # Instantiate all the rule engines once
        self.prescreen   = PrescreenRules()
        self.dealer      = DealerRules()
        self.decision    = DecisionRules()
        self.tlo         = TLOService(use_mock=True)
        self.stipulations = StipulationsEngine()

    def _build_final_decision(self,
                               fully_enriched_app,
                               risk_score_obj,
                               prescreen_result,
                               dealer_result,
                               decision_result,
                               tlo_result,
                               stip_result) -> FinalDecision:
        """
        Takes all the individual results and combines them into
        one clean FinalDecision object.

        This is where the FINAL OUTCOME is determined:
          1. Did prescreen fail?   → DECLINE
          2. Did dealer rules fail? → DECLINE
          3. Did decision rules fail? → DECLINE
          4. Are there required stips? → PENDING
          5. Is bid less than 90% of requested? → COUNTER OFFER
          6. Otherwise → AUTO APPROVE
        """
        app     = fully_enriched_app.enriched_app.application
        app_id  = app.application_id
        now     = datetime.now().isoformat(timespec="seconds")

        decline_reasons = []
        stip_list       = [s.description for s in stip_result.stipulations if s.required]
        warnings        = list(prescreen_result.warnings)

        # ── Step 1: Check for declines ─────────────────────────
        if not prescreen_result.passed:
            decline_reasons.append(f"Prescreen: {prescreen_result.decline_reason}")

        if not dealer_result.passed:
            for rule in dealer_result.failed_rules:
                decline_reasons.append(f"Dealer rule: {rule}")

        if not decision_result.passed:
            decline_reasons.append(f"Decision: {decision_result.decline_reason}")

        # ── Step 2: Determine outcome ──────────────────────────
        if decline_reasons:
            outcome      = Outcome.DECLINE
            tier         = "N/A"
            bid          = 0.0
            interest     = "N/A"
            is_counter   = False

        elif stip_result.has_required_stips:
            outcome      = Outcome.PENDING
            tier         = decision_result.tier
            bid          = decision_result.bid_amount
            interest     = decision_result.interest_band
            is_counter   = (bid < app.loan_amount * self.COUNTER_OFFER_THRESHOLD)

        else:
            # Check if it's a counter offer (we approve less than requested)
            bid        = decision_result.bid_amount
            is_counter = (bid < app.loan_amount * self.COUNTER_OFFER_THRESHOLD)
            outcome    = Outcome.COUNTER_OFFER if is_counter else Outcome.AUTO_APPROVE
            tier       = decision_result.tier
            interest   = decision_result.interest_band

        return FinalDecision(
            application_id   = app_id,
            applicant_name   = app.full_name,
            dealer_id        = app.dealer_id,
            loan_type        = app.loan_type,
            loan_requested   = app.loan_amount,
            decision         = outcome,
            tier             = tier,
            bid_amount       = bid,
            interest_band    = interest,
            risk_score       = risk_score_obj.risk_score,
            risk_label       = risk_score_obj.risk_label,
            stipulations     = stip_list,
            decline_reasons  = decline_reasons,
            warnings         = warnings,
            is_counter_offer = is_counter,
            decided_at       = now,
        )

    def decide(self,
               fully_enriched_apps: list,
               risk_scores: list) -> list[FinalDecision]:
        """
        THE MAIN METHOD.
        Pass in the fully enriched apps + risk scores from Phase 2.
        Get back a clean list of FinalDecision objects.
        """
        print("\n⚙️   Running Decision Engine...")

        # Build quick lookup dict for risk scores by app_id
        score_map = {s.application_id: s for s in risk_scores}

        # Run all rule engines in order
        # We pass the original applications for prescreen (needs LoanApplication)
        raw_apps         = [a.enriched_app.application for a in fully_enriched_apps]
        prescreen_map    = self.prescreen.run_all(raw_apps)
        dealer_map       = self.dealer.run_all(fully_enriched_apps)
        decision_map     = self.decision.run_all(fully_enriched_apps, risk_scores, dealer_map)
        tlo_map          = self.tlo.check_all(fully_enriched_apps)
        stip_map         = self.stipulations.run_all(fully_enriched_apps, tlo_map, decision_map)

        # Build FinalDecision for each application
        final_decisions = []
        for app in fully_enriched_apps:
            app_id = app.application_id
            fd = self._build_final_decision(
                fully_enriched_app = app,
                risk_score_obj     = score_map[app_id],
                prescreen_result   = prescreen_map[app_id],
                dealer_result      = dealer_map[app_id],
                decision_result    = decision_map[app_id],
                tlo_result         = tlo_map[app_id],
                stip_result        = stip_map[app_id],
            )
            final_decisions.append(fd)

        # Print summary
        counts = {}
        for fd in final_decisions:
            counts[fd.decision] = counts.get(fd.decision, 0) + 1

        print(f"\nDecision Engine complete — {counts}")
        return final_decisions