"""
src/credit_bureau/bureau_parser.py

WHAT THIS FILE DOES:
  - Reads raw credit bureau data from CSV
  - Cleans it (handles missing values, bad types)
  - Calculates derived metrics like Debt-to-Income ratio
  - Merges credit data WITH application data into one combined record
  - Flags obvious red flags (bankruptcies, very low scores etc.)

THINK OF IT AS: The credit check step.
Before decisioning, we need to know the applicant's credit history.
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional
from src.ingestion.application_ingestor import LoanApplication


# ─────────────────────────────────────────────────────────────
# DATA CLASS — Shape of one credit bureau record
# ─────────────────────────────────────────────────────────────
@dataclass
class CreditBureauRecord:
    application_id:          int
    credit_score:            int
    open_accounts:           int
    delinquencies_last_2yr:  int
    total_debt:              float
    monthly_debt_payments:   float
    bankruptcies:            int
    oldest_account_years:    float
    bureau_pull_date:        str


# ─────────────────────────────────────────────────────────────
# DATA CLASS — Application + Credit data merged into one object
# This is what gets passed to the rules engine
# ─────────────────────────────────────────────────────────────
@dataclass
class EnrichedApplication:
    # ── Original application fields ───────────────────────────
    application:    LoanApplication

    # ── Credit bureau fields ──────────────────────────────────
    credit_score:           int
    open_accounts:          int
    delinquencies_last_2yr: int
    total_debt:             float
    monthly_debt_payments:  float
    bankruptcies:           int
    oldest_account_years:   float
    bureau_pull_date:       str

    # ── Calculated / derived fields ───────────────────────────
    debt_to_income_ratio:   float   # monthly debt ÷ monthly income
    red_flags:              list    # list of warning strings

    @property
    def application_id(self) -> int:
        return self.application.application_id

    @property
    def full_name(self) -> str:
        return self.application.full_name

    def summary(self) -> str:
        """Prints a readable one-line summary of this enriched record."""
        return (
            f"[App {self.application_id}] {self.full_name} | "
            f"Score: {self.credit_score} | "
            f"DTI: {self.debt_to_income_ratio:.1%} | "
            f"Loan: ${self.application.loan_amount:,.0f} | "
            f"Red Flags: {len(self.red_flags)}"
        )


# ─────────────────────────────────────────────────────────────
# BUREAU PARSER — Reads bureau CSV, cleans it, merges it
# ─────────────────────────────────────────────────────────────
class BureauParser:

    # Default value when credit score is completely missing
    DEFAULT_CREDIT_SCORE = 300   # worst possible — forces a decline

    def __init__(self, bureau_filepath: str):
        self.bureau_filepath = bureau_filepath

    # ── STEP 1: Load and clean raw bureau CSV ──────────────────
    def _load_bureau_data(self) -> pd.DataFrame:
        df = pd.read_csv(self.bureau_filepath)

        print(f"Loaded {len(df)} credit bureau records from '{self.bureau_filepath}'")

        # ── Handle missing values with sensible defaults ───────
        # If credit score is missing, default to worst score (safe choice)
        df["credit_score"] = df["credit_score"].fillna(self.DEFAULT_CREDIT_SCORE).astype(int)

        # Clamp credit score between 300 and 850 (valid FICO range)
        df["credit_score"] = df["credit_score"].clip(lower=300, upper=850)

        # Missing delinquencies / bankruptcies = assume 0
        df["delinquencies_last_2yr"] = df["delinquencies_last_2yr"].fillna(0).astype(int)
        df["bankruptcies"]           = df["bankruptcies"].fillna(0).astype(int)

        # Missing debt values = assume 0
        df["total_debt"]            = df["total_debt"].fillna(0.0)
        df["monthly_debt_payments"] = df["monthly_debt_payments"].fillna(0.0)

        # Missing open accounts = 0
        df["open_accounts"] = df["open_accounts"].fillna(0).astype(int)

        # Missing account age = 0 years (newest / unknown)
        df["oldest_account_years"] = df["oldest_account_years"].fillna(0.0)

        return df

    # ── STEP 2: Calculate Debt-to-Income ratio ─────────────────
    @staticmethod
    def _calculate_dti(monthly_debt: float, monthly_income: float) -> float:
        """
        DTI = monthly debt payments ÷ monthly income
        Example: $500 debt / $3000 income = 0.167 = 16.7% DTI

        Lower is better. Above 0.43 (43%) is usually a warning sign.
        """
        if monthly_income <= 0:
            return 1.0  # 100% DTI — worst case guard
        return round(monthly_debt / monthly_income, 4)

    # ── STEP 3: Detect red flags for this applicant ────────────
    @staticmethod
    def _detect_red_flags(credit_score: int,
                          dti: float,
                          bankruptcies: int,
                          delinquencies: int) -> list[str]:
        """
        Returns a list of human-readable warning strings.
        These don't auto-decline — they inform the rules engine.
        """
        flags = []

        if credit_score < 580:
            flags.append(f"Very low credit score: {credit_score}")

        if dti > 0.43:
            flags.append(f"High DTI ratio: {dti:.1%}")

        if bankruptcies > 0:
            flags.append(f"Has {bankruptcies} bankruptcy record(s)")

        if delinquencies >= 2:
            flags.append(f"Multiple recent delinquencies: {delinquencies} in last 2 years")

        return flags

    # ── STEP 4: Merge one application with its bureau record ───
    def _enrich_one(self,
                    app: LoanApplication,
                    bureau_row: Optional[pd.Series]) -> EnrichedApplication:
        """
        Combines a LoanApplication + bureau row into an EnrichedApplication.
        If no bureau data found for this app, uses worst-case defaults.
        """
        if bureau_row is None:
            # No credit data found — use safe defaults
            credit_score          = self.DEFAULT_CREDIT_SCORE
            open_accounts         = 0
            delinquencies         = 0
            total_debt            = 0.0
            monthly_debt_payments = 0.0
            bankruptcies          = 0
            oldest_account_years  = 0.0
            bureau_pull_date      = "N/A"
        else:
            credit_score          = int(bureau_row["credit_score"])
            open_accounts         = int(bureau_row["open_accounts"])
            delinquencies         = int(bureau_row["delinquencies_last_2yr"])
            total_debt            = float(bureau_row["total_debt"])
            monthly_debt_payments = float(bureau_row["monthly_debt_payments"])
            bankruptcies          = int(bureau_row["bankruptcies"])
            oldest_account_years  = float(bureau_row["oldest_account_years"])
            bureau_pull_date      = str(bureau_row["bureau_pull_date"])

        # Calculate DTI
        dti = self._calculate_dti(monthly_debt_payments, app.monthly_income)

        # Detect red flags
        red_flags = self._detect_red_flags(credit_score, dti, bankruptcies, delinquencies)

        return EnrichedApplication(
            application            = app,
            credit_score           = credit_score,
            open_accounts          = open_accounts,
            delinquencies_last_2yr = delinquencies,
            total_debt             = total_debt,
            monthly_debt_payments  = monthly_debt_payments,
            bankruptcies           = bankruptcies,
            oldest_account_years   = oldest_account_years,
            bureau_pull_date       = bureau_pull_date,
            debt_to_income_ratio   = dti,
            red_flags              = red_flags,
        )

    # ── STEP 5: Main method — merge all applications ───────────
    def enrich(self, applications: list[LoanApplication]) -> list[EnrichedApplication]:
        """
        Takes a list of LoanApplications.
        Merges each with bureau data.
        Returns a list of EnrichedApplications.
        """
        bureau_df = self._load_bureau_data()

        # Index bureau data by application_id for fast lookup
        bureau_index = bureau_df.set_index("application_id")

        enriched = []
        for app in applications:
            if app.application_id in bureau_index.index:
                bureau_row = bureau_index.loc[app.application_id]
            else:
                print(f"No bureau data for App ID {app.application_id} — using defaults")
                bureau_row = None

            enriched_app = self._enrich_one(app, bureau_row)
            enriched.append(enriched_app)

        print(f"\nEnriched {len(enriched)} applications with credit bureau data")
        return enriched