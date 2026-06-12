"""
src/ingestion/application_ingestor.py

WHAT THIS FILE DOES:
  - Reads loan applications from the CSV file
  - Validates that all required fields are present
  - Cleans up messy data (whitespace, wrong types, etc.)
  - Returns clean Application objects ready for decisioning

THINK OF IT AS: The front door of the system.
Every application must pass through here first.
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# DATA CLASS  — This is the "shape" of one loan application
# A dataclass is just a clean way to define an object with fields
# ─────────────────────────────────────────────────────────────
@dataclass
class LoanApplication:
    application_id:     int
    first_name:         str
    last_name:          str
    email:              str
    phone:              str
    annual_income:      float
    loan_amount:        float
    loan_type:          str
    dealer_id:          str
    has_coapplicant:    bool
    state:              str
    zip_code:           str
    submitted_at:       datetime
    coapplicant_name:   Optional[str]   = None
    coapplicant_income: Optional[float] = None

    # ── Derived fields (calculated automatically) ──────────────
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def monthly_income(self) -> float:
        """Annual income divided into monthly figure."""
        return round(self.annual_income / 12, 2)

    @property
    def loan_to_income_ratio(self) -> float:
        """How big is the loan compared to annual income?"""
        if self.annual_income == 0:
            return 999.0   # guard against division by zero
        return round(self.loan_amount / self.annual_income, 4)


# ─────────────────────────────────────────────────────────────
# VALIDATOR — Checks one row of data before we create an object
# ─────────────────────────────────────────────────────────────
class ApplicationValidator:

    REQUIRED_FIELDS = [
        "application_id", "first_name", "last_name",
        "annual_income", "loan_amount", "loan_type", "dealer_id",
    ]

    VALID_LOAN_TYPES = [
        "Home Improvement Loan",
        "Personal Loan",
        "Auto Loan",
    ]

    def validate(self, row: dict) -> list[str]:
        """
        Returns a list of error messages.
        Empty list means the row is clean and valid.
        """
        errors = []

        # 1. Check required fields exist and are not empty/NaN
        for field_name in self.REQUIRED_FIELDS:
            value = row.get(field_name)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                errors.append(f"Missing required field: '{field_name}'")

        # 2. Income must be positive
        income = row.get("annual_income", 0)
        if not pd.isna(income) and float(income) <= 0:
            errors.append("annual_income must be greater than 0")

        # 3. Loan amount must be positive
        loan_amt = row.get("loan_amount", 0)
        if not pd.isna(loan_amt) and float(loan_amt) <= 0:
            errors.append("loan_amount must be greater than 0")

        # 4. Loan type must be recognised
        loan_type = row.get("loan_type", "")
        if loan_type not in self.VALID_LOAN_TYPES:
            errors.append(
                f"loan_type '{loan_type}' is not valid. "
                f"Must be one of: {self.VALID_LOAN_TYPES}"
            )

        return errors


# ─────────────────────────────────────────────────────────────
# INGESTOR — Main class that reads CSV and produces clean objects
# ─────────────────────────────────────────────────────────────
class ApplicationIngestor:

    def __init__(self, filepath: str):
        """
        filepath: path to the applications CSV file
        """
        self.filepath  = filepath
        self.validator = ApplicationValidator()

        # These lists track what happened during loading
        self.valid_applications:   list[LoanApplication] = []
        self.rejected_rows:        list[dict]            = []

    # ── STEP 1: Load raw CSV ───────────────────────────────────
    def _load_csv(self) -> pd.DataFrame:
        df = pd.read_csv(self.filepath)

        # Strip whitespace from all string columns
        str_cols = df.select_dtypes(include="object").columns
        df[str_cols] = df[str_cols].apply(lambda col: col.str.strip())

        print(f" Loaded {len(df)} rows from '{self.filepath}'")
        return df

    # ── STEP 2: Convert one dataframe row → LoanApplication ───
    def _parse_row(self, row: dict) -> LoanApplication:
        return LoanApplication(
            application_id     = int(row["application_id"]),
            first_name         = str(row["first_name"]),
            last_name          = str(row["last_name"]),
            email              = str(row.get("email", "")),
            phone              = str(row.get("phone", "")),
            annual_income      = float(row["annual_income"]),
            loan_amount        = float(row["loan_amount"]),
            loan_type          = str(row["loan_type"]),
            dealer_id          = str(row["dealer_id"]),
            has_coapplicant    = str(row.get("has_coapplicant", "False")).lower() == "true",
            state              = str(row.get("state", "")),
            zip_code           = str(row.get("zip_code", "")),
            submitted_at       = pd.to_datetime(row.get("submitted_at", datetime.now())),
            coapplicant_name   = row.get("coapplicant_name") if not pd.isna(row.get("coapplicant_name", float("nan"))) else None,
            coapplicant_income = float(row["coapplicant_income"]) if not pd.isna(row.get("coapplicant_income", float("nan"))) else None,
        )

    # ── STEP 3: Main method — run the whole ingestion ──────────
    def run(self) -> list[LoanApplication]:
        df = self._load_csv()

        for _, row in df.iterrows():
            row_dict = row.to_dict()

            # Validate first
            errors = self.validator.validate(row_dict)

            if errors:
                # Log the bad row with its errors and skip it
                row_dict["_errors"] = errors
                self.rejected_rows.append(row_dict)
            else:
                # Parse into a clean object
                app = self._parse_row(row_dict)
                self.valid_applications.append(app)

        self._print_summary()
        return self.valid_applications

    # ── STEP 4: Print a nice summary after loading ─────────────
    def _print_summary(self):
        total    = len(self.valid_applications) + len(self.rejected_rows)
        accepted = len(self.valid_applications)
        rejected = len(self.rejected_rows)

        print("\n" + "=" * 50)
        print("  APPLICATION INGESTION SUMMARY")
        print("=" * 50)
        print(f"  Total rows read   : {total}")
        print(f"  Valid           : {accepted}")
        print(f"  Rejected        : {rejected}")
        print("=" * 50)

        if self.rejected_rows:
            print("\n  Rejected rows and reasons:")
            for row in self.rejected_rows:
                print(f"    App ID {row.get('application_id', '?')} → {row['_errors']}")