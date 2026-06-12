"""
api/app.py

WHAT THIS FILE DOES:
  Exposes the credit decisioning system as a REST API using FastAPI.
  Anyone (a frontend, another system, a mobile app) can now send an
  HTTP request and get back a credit decision.

  ENDPOINTS:
    POST /decide              → submit ONE application, get a decision back
    GET  /decision/{id}       → look up a past decision by application ID
    GET  /decisions           → list all decisions (with optional filter)
    GET  /stats               → summary statistics
    GET  /health              → health check (is the API running?)

  WHAT IS FastAPI?
    A modern Python web framework that:
      - Takes HTTP requests (POST, GET etc.)
      - Validates the incoming data automatically (using Pydantic)
      - Returns JSON responses
      - Auto-generates interactive docs at /docs

  WHAT IS PYDANTIC?
    A library for data validation. You define the SHAPE of your
    request/response data using Python classes, and FastAPI validates
    all incoming data against those shapes automatically.

HOW TO RUN THE API:
    uvicorn api.app:app --reload --port 8000

HOW TO TEST IT:
    Open http://localhost:8000/docs in your browser
    — you'll see an interactive UI to test every endpoint.
"""

from fastapi         import FastAPI, HTTPException
from pydantic        import BaseModel, Field
from typing          import Optional
import os
import sys

# Add project root to path so imports work when running from api/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion.application_ingestor  import LoanApplication
from src.credit_bureau.bureau_parser     import BureauParser, CreditBureauRecord, EnrichedApplication
from src.adm_lookup.adm_lookup           import ADMLookup, ADMData, FullyEnrichedApplication
from src.models.risk_model               import RiskModel
from src.decision.decision_engine        import DecisionEngine
from src.database.db                     import DecisionDatabase
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# CREATE THE FASTAPI APP
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "Credit Decisioning System",
    description = "Automated credit decisioning engine — Phase 4",
    version     = "1.0.0",
)


# ─────────────────────────────────────────────────────────────
# PYDANTIC MODELS — define the shape of API requests/responses
# FastAPI uses these to validate data and generate docs
# ─────────────────────────────────────────────────────────────

class ApplicationRequest(BaseModel):
    """Shape of the incoming application when submitted via API."""
    application_id:     int   = Field(..., example=101)
    first_name:         str   = Field(..., example="John")
    last_name:          str   = Field(..., example="Doe")
    email:              str   = Field(..., example="john@example.com")
    phone:              str   = Field(..., example="555-1234")
    annual_income:      float = Field(..., example=65000.0)
    loan_amount:        float = Field(..., example=15000.0)
    loan_type:          str   = Field(..., example="Personal Loan")
    dealer_id:          str   = Field(..., example="D001")
    has_coapplicant:    bool  = Field(False, example=False)
    state:              str   = Field(..., example="WI")
    zip_code:           str   = Field(..., example="53001")
    # Credit bureau fields (in real life these come from TransUnion)
    credit_score:       int   = Field(..., example=700)
    total_debt:         float = Field(0.0,  example=12000.0)
    monthly_debt_payments: float = Field(0.0, example=400.0)
    delinquencies_last_2yr: int = Field(0,  example=0)
    bankruptcies:       int   = Field(0,    example=0)
    open_accounts:      int   = Field(3,    example=3)
    oldest_account_years: float = Field(5.0, example=5.0)
    # ADM fields (customer history)
    employment_status:  str   = Field("Employed", example="Employed")
    years_employed:     float = Field(2.0,  example=2.0)
    is_homeowner:       bool  = Field(False, example=False)
    previous_loans:     int   = Field(0,    example=0)
    previous_defaults:  int   = Field(0,    example=0)


class DecisionResponse(BaseModel):
    """Shape of the response we send back."""
    application_id:  int
    applicant_name:  str
    decision:        str
    tier:            str
    bid_amount:      float
    interest_band:   str
    risk_score:      float
    risk_label:      str
    is_counter_offer: bool
    stipulations:    list[str]
    decline_reasons: list[str]
    decided_at:      str


# ─────────────────────────────────────────────────────────────
# STARTUP — load model once when API starts
# ─────────────────────────────────────────────────────────────
risk_model = RiskModel()

@app.on_event("startup")
def startup():
    """Runs once when the API server starts."""
    if os.path.exists(RiskModel.MODEL_PATH):
        risk_model.load()
    else:
        print("No model found — training now...")
        risk_model.train()
    print("Credit Decisioning API is ready!")


# ─────────────────────────────────────────────────────────────
# HELPER — build a FullyEnrichedApplication from API request
# ─────────────────────────────────────────────────────────────
def _build_fully_enriched(req: ApplicationRequest) -> FullyEnrichedApplication:
    """
    Converts a raw API request into a FullyEnrichedApplication object
    that the decision engine can process.

    In a real system, credit bureau and ADM data come from external calls.
    Here we accept them directly in the request for simplicity.
    """
    loan_app = LoanApplication(
        application_id    = req.application_id,
        first_name        = req.first_name,
        last_name         = req.last_name,
        email             = req.email,
        phone             = req.phone,
        annual_income     = req.annual_income,
        loan_amount       = req.loan_amount,
        loan_type         = req.loan_type,
        dealer_id         = req.dealer_id,
        has_coapplicant   = req.has_coapplicant,
        state             = req.state,
        zip_code          = req.zip_code,
        submitted_at      = datetime.now(),
    )

    monthly_income = req.annual_income / 12
    dti = req.monthly_debt_payments / monthly_income if monthly_income > 0 else 1.0

    # Build red flags list
    red_flags = []
    if req.credit_score < 580:
        red_flags.append(f"Very low credit score: {req.credit_score}")
    if dti > 0.43:
        red_flags.append(f"High DTI: {dti:.1%}")
    if req.bankruptcies > 0:
        red_flags.append(f"Has {req.bankruptcies} bankruptcy record(s)")

    enriched = EnrichedApplication(
        application            = loan_app,
        credit_score           = req.credit_score,
        open_accounts          = req.open_accounts,
        delinquencies_last_2yr = req.delinquencies_last_2yr,
        total_debt             = req.total_debt,
        monthly_debt_payments  = req.monthly_debt_payments,
        bankruptcies           = req.bankruptcies,
        oldest_account_years   = req.oldest_account_years,
        bureau_pull_date       = datetime.now().isoformat(),
        debt_to_income_ratio   = round(dti, 4),
        red_flags              = red_flags,
    )

    adm = ADMData(
        application_id    = req.application_id,
        employment_status = req.employment_status,
        employer_name     = "Provided via API",
        years_employed    = req.years_employed,
        is_homeowner      = req.is_homeowner,
        years_at_address  = 0.0,
        previous_loans    = req.previous_loans,
        previous_defaults = req.previous_defaults,
        found_in_db       = True,
    )

    return FullyEnrichedApplication(enriched_app=enriched, adm_data=adm)


# ─────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────

# ── GET /health ────────────────────────────────────────────────
@app.get("/health", tags=["System"])
def health_check():
    """Simple health check — confirms the API is running."""
    return {"status": "ok", "message": "Credit Decisioning API is running"}


# ── POST /decide ───────────────────────────────────────────────
@app.post("/decide", response_model=DecisionResponse, tags=["Decisioning"])
def decide(request: ApplicationRequest):
    """
    Submit ONE loan application and get a credit decision back.

    FastAPI automatically:
      - Validates all fields in the request
      - Returns a 422 error if required fields are missing
      - Returns a 200 with DecisionResponse if successful
    """
    # Build the enriched application from the request
    fully_enriched = _build_fully_enriched(request)

    # Score it with the risk model
    risk_scores = risk_model.score_all([fully_enriched])

    # Run the decision engine
    engine    = DecisionEngine()
    decisions = engine.decide([fully_enriched], risk_scores)
    final     = decisions[0]

    # Save to database
    db = DecisionDatabase()
    db.save(final)
    db.close()

    return DecisionResponse(**final.to_dict())


# ── GET /decision/{application_id} ─────────────────────────────
@app.get("/decision/{application_id}", response_model=DecisionResponse, tags=["Decisioning"])
def get_decision(application_id: int):
    """
    Look up a previously made decision by application ID.
    Returns 404 if not found.
    """
    db     = DecisionDatabase()
    result = db.get_by_id(application_id)
    db.close()

    if result is None:
        raise HTTPException(
            status_code = 404,
            detail      = f"No decision found for application_id {application_id}"
        )

    return result


# ── GET /decisions ─────────────────────────────────────────────
@app.get("/decisions", tags=["Decisioning"])
def list_decisions(
    decision_type: Optional[str] = None,
    limit:         int           = 50
):
    """
    List all decisions.
    Optionally filter by decision type: 'Auto Approved', 'Pending', 'Decline', 'Counter Offer'
    """
    db = DecisionDatabase()

    if decision_type:
        results = db.get_by_decision(decision_type)
    else:
        results = db.get_all(limit=limit)

    db.close()
    return {"count": len(results), "decisions": results}


# ── GET /stats ─────────────────────────────────────────────────
@app.get("/stats", tags=["Reports"])
def get_stats():
    """
    Returns summary statistics about all decisions in the database.
    Useful for dashboards and reports.
    """
    db    = DecisionDatabase()
    stats = db.get_stats()
    db.close()
    return stats