"""
src/adm_lookup/adm_lookup.py

WHAT THIS FILE DOES:
  - Creates a SQLite database (a simple file-based database, no server needed)
  - Populates it with dummy historical customer data
  - Given an applicant ID, looks up their extra info from the database
  - Merges that info into the EnrichedApplication

THINK OF IT AS: A customer history file.
Before decisioning, we check if we've seen this customer before
and pull any extra data we have on them (employment, homeownership etc.)

WHY SQLite?
  - It's built into Python — no installation needed
  - Creates a single file: adm_lookup.db
  - Perfect for learning SQL before moving to PostgreSQL later
"""

import sqlite3
import os
import random
from dataclasses import dataclass
from typing import Optional

from src.credit_bureau.bureau_parser import EnrichedApplication


# ─────────────────────────────────────────────────────────────
# DATA CLASS — Extra customer info from ADM database
# ─────────────────────────────────────────────────────────────
@dataclass
class ADMData:
    application_id:     int
    employment_status:  str       # Employed, Self-Employed, Unemployed, Retired
    employer_name:      str
    years_employed:     float
    is_homeowner:       bool
    years_at_address:   float
    previous_loans:     int       # how many loans they've had with us before
    previous_defaults:  int       # how many times they defaulted
    found_in_db:        bool      # False if this is a brand new customer


# ─────────────────────────────────────────────────────────────
# DATA CLASS — Fully enriched application (Application + Bureau + ADM)
# This is the FINAL object passed to the Rules Engine
# ─────────────────────────────────────────────────────────────
@dataclass
class FullyEnrichedApplication:
    enriched_app:   EnrichedApplication   # has application + bureau data
    adm_data:       ADMData               # has historical customer data

    @property
    def application_id(self) -> int:
        return self.enriched_app.application_id

    @property
    def full_name(self) -> str:
        return self.enriched_app.full_name

    def summary(self) -> str:
        return (
            f"[App {self.application_id}] {self.full_name} | "
            f"Score: {self.enriched_app.credit_score} | "
            f"DTI: {self.enriched_app.debt_to_income_ratio:.1%} | "
            f"Homeowner: {self.adm_data.is_homeowner} | "
            f"Employment: {self.adm_data.employment_status} | "
            f"Prior Loans: {self.adm_data.previous_loans}"
        )


# ─────────────────────────────────────────────────────────────
# ADM LOOKUP — Creates DB, seeds data, and handles lookups
# ─────────────────────────────────────────────────────────────
class ADMLookup:

    DB_PATH = "data/adm_lookup.db"

    EMPLOYMENT_STATUSES = ["Employed", "Employed", "Employed",   # weighted towards Employed
                           "Self-Employed", "Retired", "Unemployed"]

    EMPLOYERS = ["Walmart", "Amazon", "Hospital", "School District",
                 "Tech Corp", "Construction Co", "Self", "Federal Govt",
                 "Retail Store", "Manufacturing Plant"]

    def __init__(self):
        # Create the data folder if it doesn't exist
        os.makedirs("data", exist_ok=True)
        self.connection = sqlite3.connect(self.DB_PATH)
        self._create_table()

    # ── STEP 1: Create the table if it doesn't exist ───────────
    def _create_table(self):
        """
        SQL CREATE TABLE — defines the structure of our database table.
        IF NOT EXISTS means it won't crash if we run this twice.
        """
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS adm_customers (
                application_id      INTEGER PRIMARY KEY,
                employment_status   TEXT    NOT NULL,
                employer_name       TEXT,
                years_employed      REAL    DEFAULT 0,
                is_homeowner        INTEGER DEFAULT 0,
                years_at_address    REAL    DEFAULT 0,
                previous_loans      INTEGER DEFAULT 0,
                previous_defaults   INTEGER DEFAULT 0
            )
        """)
        self.connection.commit()
        print(f"ADM database ready at '{self.DB_PATH}'")

    # ── STEP 2: Seed dummy data for all application IDs ────────
    def seed_data(self, application_ids: list[int]):
        """
        Inserts dummy historical data for each application ID.
        In real life this data comes from internal systems.
        We use INSERT OR IGNORE so we don't duplicate if run twice.
        """
        random.seed(42)   # same seed = same data every run

        rows = []
        for app_id in application_ids:
            employment  = random.choice(self.EMPLOYMENT_STATUSES)
            employer    = random.choice(self.EMPLOYERS)
            yrs_emp     = round(random.uniform(0, 30), 1)
            homeowner   = random.choice([0, 0, 1])         # 33% homeowners
            yrs_addr    = round(random.uniform(0, 20), 1)
            prev_loans  = random.randint(0, 5)
            prev_def    = random.choices([0, 1, 2], weights=[85, 12, 3])[0]

            rows.append((
                app_id, employment, employer, yrs_emp,
                homeowner, yrs_addr, prev_loans, prev_def
            ))

        self.connection.executemany("""
            INSERT OR IGNORE INTO adm_customers
            (application_id, employment_status, employer_name, years_employed,
             is_homeowner, years_at_address, previous_loans, previous_defaults)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self.connection.commit()
        print(f"Seeded ADM data for {len(rows)} applicants")

    # ── STEP 3: Look up one applicant by ID ────────────────────
    def lookup(self, application_id: int) -> ADMData:
        """
        Runs a SQL SELECT query to find this applicant.
        Returns an ADMData object. If not found, returns safe defaults.
        """
        cursor = self.connection.execute("""
            SELECT
                application_id,
                employment_status,
                employer_name,
                years_employed,
                is_homeowner,
                years_at_address,
                previous_loans,
                previous_defaults
            FROM adm_customers
            WHERE application_id = ?
        """, (application_id,))

        row = cursor.fetchone()   # fetchone() returns one row or None

        if row is None:
            # Brand new customer — return safe defaults
            return ADMData(
                application_id    = application_id,
                employment_status = "Unknown",
                employer_name     = "Unknown",
                years_employed    = 0.0,
                is_homeowner      = False,
                years_at_address  = 0.0,
                previous_loans    = 0,
                previous_defaults = 0,
                found_in_db       = False,
            )

        return ADMData(
            application_id    = row[0],
            employment_status = row[1],
            employer_name     = row[2],
            years_employed    = row[3],
            is_homeowner      = bool(row[4]),
            years_at_address  = row[5],
            previous_loans    = row[6],
            previous_defaults = row[7],
            found_in_db       = True,
        )

    # ── STEP 4: Enrich all applications with ADM data ──────────
    def enrich_all(self, enriched_apps: list[EnrichedApplication]) -> list[FullyEnrichedApplication]:
        """
        Takes the list of EnrichedApplications from Phase 1.
        Looks up ADM data for each one.
        Returns FullyEnrichedApplications — the complete picture.
        """
        results = []
        for app in enriched_apps:
            adm_data = self.lookup(app.application_id)
            fully_enriched = FullyEnrichedApplication(
                enriched_app = app,
                adm_data     = adm_data,
            )
            results.append(fully_enriched)

        print(f"\nADM lookup complete for {len(results)} applications")
        return results

    # ── Close the database connection when done ────────────────
    def close(self):
        self.connection.close()