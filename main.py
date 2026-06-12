"""
main.py  — PHASE 1 + 2 + 3 + 4
HOW TO RUN:  python main.py
"""

import os
from src.ingestion.application_ingestor  import ApplicationIngestor
from src.credit_bureau.bureau_parser     import BureauParser
from src.adm_lookup.adm_lookup           import ADMLookup
from src.models.risk_model               import RiskModel
from src.decision.decision_engine        import DecisionEngine
from src.database.db                     import DecisionDatabase


def main():
    print("\n" + "=" * 60)
    print("   CREDIT DECISIONING SYSTEM  —  PHASE 1 + 2 + 3 + 4")
    print("=" * 60)

    # PHASE 1
    print("\n STEP 1: Loading Applications...\n")
    ingestor     = ApplicationIngestor(filepath="data/applications.csv")
    applications = ingestor.run()
    if not applications:
        print("No valid applications. Exiting.")
        return

    print("\n STEP 2: Credit Bureau Data...\n")
    enriched = BureauParser(bureau_filepath="data/credit_bureau.csv").enrich(applications)

    # PHASE 2
    print("\n  STEP 3: ADM Lookup...\n")
    adm = ADMLookup()
    adm.seed_data([a.application_id for a in applications])
    fully_enriched = adm.enrich_all(enriched)
    adm.close()

    print("\n STEP 4: Risk Scoring Model...\n")
    model = RiskModel()
    if os.path.exists(RiskModel.MODEL_PATH):
        model.load()
    else:
        model.train()
    risk_scores = model.score_all(fully_enriched)

    # PHASE 4 — Decision Engine + Database
    print("\n STEP 5: Running Decision Engine...\n")
    engine   = DecisionEngine()
    decisions = engine.decide(fully_enriched, risk_scores)

    print("\n STEP 6: Saving to Database...\n")
    db = DecisionDatabase()
    db.save_all(decisions)

    # FINAL REPORT
    print("\n" + "=" * 60)
    print("   FINAL DECISION REPORT")
    print("=" * 60)

    for d in decisions:
        emoji = {
            "Auto Approved": "✅",
            "Counter Offer": "🔄",
            "Pending":       "🟡",
            "Decline":       "❌",
        }.get(d.decision, "❓")

        print(f"\n{emoji} [{d.decision}] App {d.application_id} — {d.applicant_name}")
        print(f"   Risk: {d.risk_score:.3f} ({d.risk_label}) | Tier: {d.tier} | Bid: ${d.bid_amount:,.0f} | Rate: {d.interest_band}")

        if d.decline_reasons:
            for r in d.decline_reasons:
                print(f"   ❌  {r}")
        if d.stipulations:
            for s in d.stipulations:
                print(f"   📎  {s[:75]}")

    # STATS FROM DATABASE
    print("\n" + "=" * 60)
    print("   DATABASE STATS")
    print("=" * 60)
    stats = db.get_stats()
    print(f"  Total decisions stored: {stats['total']}")
    for outcome, count in stats["by_decision"].items():
        pct   = count / stats["total"] * 100
        emoji = {"Auto Approved":"✅","Counter Offer":"🔄","Pending":"🟡","Decline":"❌"}.get(outcome,"❓")
        print(f"  {emoji}  {outcome:<18}: {count:>3}  ({pct:.0f}%)")

    print(f"\n  By Tier:")
    for row in stats["by_tier"]:
        print(f"    Tier {row['tier']}: {int(row['count'])} apps | "
              f"Avg Risk: {row['avg_risk']:.3f} | Avg Bid: ${row['avg_bid']:,.0f}")

    db.close()
    # print(f" Run:  uvicorn api.app:app --reload --port 8000")
    # print(f" Then open: http://localhost:8000/docs")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()