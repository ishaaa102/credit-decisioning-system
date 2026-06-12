# credit-decisioning-system
Automated loan application credit decisioning engine built in Python — ML risk scoring, rules engine, REST API, and SQLite audit trail.

# Credit Decisioning System — V1

## What Is This Project?

Foundation Finance uses a third-party vendor called **GDS (GDSLink)** to
auto-decide loan applications. That means vendor lock-in, licensing costs,
no control over the logic, and no internal data storage.

This project is **Athena V1** — our own credit decisioning engine built
from scratch in Python. It does everything GDS does:

- Takes a loan application as input
- Pulls credit bureau data
- Scores the applicant with a Machine Learning model
- Applies layered business rules (prescreen → dealer → decision)
- Checks homeownership via TLO API
- Flags stipulations (conditions before funding)
- Returns a final decision — **Approve / Decline / Pending / Counter Offer**
- Saves every decision to a database with full audit trail
- Exposes everything via a REST API

The end goal is to replace the GDS endpoint in DL4 with this system's
`POST /decide` endpoint.

---

## Project Structure
credit_decisioning/

│

├── data/                          # Auto-generated data files (gitignore the .db files)

│   ├── applications.csv           # 50 dummy loan applications

│   ├── credit_bureau.csv          # Dummy TransUnion credit data

│   ├── dealer_rules.json          # Per-dealer rule thresholds (edit without code change)

│   ├── decisions.db               # SQLite — every decision stored here

│   ├── adm_lookup.db              # SQLite — customer history

│   └── risk_model.joblib          # Trained ML model saved to disk

│

├── src/

│   ├── ingestion/

│   │   └── application_ingestor.py    # Phase 1: Validate and parse applications

│   │

│   ├── credit_bureau/

│   │   └── bureau_parser.py           # Phase 1: Parse credit data, calc DTI, red flags

│   │

│   ├── adm_lookup/

│   │   └── adm_lookup.py              # Phase 2: SQLite customer history lookup

│   │

│   ├── models/

│   │   └── risk_model.py              # Phase 2: Train/load logistic regression model

│   │

│   ├── rules_engine/

│   │   ├── prescreen_rules.py         # Phase 3: Quick knockout checks

│   │   ├── dealer_rules.py            # Phase 3: Per-dealer thresholds from JSON

│   │   └── decision_rules.py          # Phase 3: Assign tier A-D and bid amount

│   │

│   ├── tlo/

│   │   └── tlo_service.py             # Phase 3: Homeownership check (mocked in V1)

│   │

│   ├── stipulations/

│   │   └── stipulations_engine.py     # Phase 3: Conditions attached to approvals

│   │

│   ├── decision/

│   │   └── decision_engine.py         # Phase 4: Orchestrates all phases → FinalDecision

│   │

│   └── database/

│       └── db.py                      # Phase 4: Save/query decisions in SQLite

│

├── api/

│   └── app.py                         # Phase 4: FastAPI — 5 REST endpoints

│

├── generate_data.py                   # Run once to create dummy CSV data

├── main.py                            # Run the full pipeline end to end

└── requirements.txt                   # All Python dependencies

---

## How To Run

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Generate dummy data (run once)
```bash
python generate_data.py
```

### 3. Run the full pipeline
```bash
python main.py
```

### 4. Start the REST API
```bash
uvicorn api.app:app --reload --port 8000
```

### 5. Open interactive API docs
http://localhost:8000/docs

---

## The Decision Flow
Loan Application

↓

Phase 1 — Ingestion & Credit Bureau

→ Validate all fields

→ Parse TransUnion credit data

→ Calculate DTI ratio

→ Flag red flags (low score, bankruptcy)

↓

Phase 2 — ADM Lookup & ML Scoring

→ Look up customer history in SQLite

→ Score with Logistic Regression model (12 features)

→ Output risk score 0.0–1.0 and ACA (max safe loan amount)

↓

Phase 3 — Rules Engine

→ Prescreen: state restrictions, income/amount limits

→ Dealer Rules: per-dealer thresholds loaded from JSON

→ Decision Rules: assign Tier A/B/C/D, calculate bid amount

→ TLO: homeownership check (mocked)

→ Stipulations: income proof, ID, homeownership proof

↓

Phase 4 — Decision + Storage + API

→ Combine all results into one FinalDecision

→ Save to SQLite with full audit trail

→ Return JSON via REST API

↓

OUTCOME: Auto Approved / Counter Offer / Pending / Decline

---

## API Endpoints

| Method | Endpoint | What it does |
|--------|----------|--------------|
| POST | `/decide` | Submit one application → get decision JSON |
| GET | `/decision/{id}` | Look up a past decision by application ID |
| GET | `/decisions` | List all decisions (filter by outcome type) |
| GET | `/stats` | Summary stats — count by outcome and tier |
| GET | `/health` | Health check — confirms API is running |

### Sample Request — POST /decide
```json
{
  "application_id": 101,
  "first_name": "John",
  "last_name": "Smith",
  "email": "john@example.com",
  "phone": "555-1234",
  "annual_income": 65000,
  "loan_amount": 15000,
  "loan_type": "Personal Loan",
  "dealer_id": "D001",
  "state": "WI",
  "credit_score": 710,
  "employment_status": "Employed",
  "years_employed": 5
}
```

### Sample Response
```json
{
  "application_id": 101,
  "applicant_name": "John Smith",
  "decision": "Auto Approved",
  "tier": "B",
  "bid_amount": 13500.00,
  "interest_band": "Medium",
  "risk_score": 0.082,
  "risk_label": "Low Risk",
  "is_counter_offer": false,
  "stipulations": [],
  "decline_reasons": [],
  "decided_at": "2025-04-19T10:32:44"
}
```

---

## Tech Stack

| Library | Purpose |
|---------|---------|
| `pandas` | Read and clean CSV data |
| `scikit-learn` | Logistic Regression risk model |
| `joblib` | Save and load trained model to disk |
| `sqlite3` | ADM lookup and decisions database |
| `fastapi` | REST API with 5 endpoints |
| `pydantic` | Request and response data validation |
| `uvicorn` | ASGI server to run the API |
| `faker` | Generate realistic dummy data |

---

## Key Design Decisions

**Why Logistic Regression?**
Credit decisioning needs an explainable model. Regulators require that
every decline has a clear reason. Logistic regression shows exactly which
features drove the score. A neural network is a black box — not acceptable
in a regulated financial product.

**Why SQLite and not PostgreSQL?**
SQLite is zero-config for V1. The schema and queries are identical to
PostgreSQL. When moving to production, only the connection string changes.
The rest of the code is untouched. PostgreSQL migration is in V2 roadmap.

**Why dealer rules in JSON and not Python code?**
Business rules change frequently. Storing thresholds in `dealer_rules.json`
means a business analyst can update a minimum credit score without a code
change, a pull request, or a deployment. Config-driven logic is a core
principle of maintainable systems.

**Why mock TLO?**
We don't have real TLO credentials in development. The mock simulates
realistic behavior — 35% homeownership, 2% failure rate, network latency.
To go live, change `use_mock=False` in `TLOService`. The interface stays
identical.

---

## V1 Results (50 dummy applications)

| Outcome | Count | % |
|---------|-------|---|
| Auto Approved | 1 | 2% |
| Pending | 10 | 20% |
| Declined | 39 | 78% |
| ML Model Accuracy | 81.5% | — |

High decline rate is expected — test data is random and many applications
fall outside specific dealer thresholds. Real production data would reflect
actual business approval rates.

## Learning Notes (Why This Was Built)

This project was built as a hands-on Python learning project replicating
the real Athena credit decisioning system at Foundation Finance. Each phase
introduced new concepts:

- **Phase 1** → Python classes, pandas, dataclasses, data validation
- **Phase 2** → SQLite, scikit-learn, ML pipelines, joblib
- **Phase 3** → Config-driven rules, JSON, layered business logic, mocking
- **Phase 4** → FastAPI, Pydantic, REST APIs, database schema design
