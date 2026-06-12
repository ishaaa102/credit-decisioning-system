"""
src/database/db.py

WHAT THIS FILE DOES:
  Every decision we make gets SAVED to a SQLite database.
  This is important for:
    - Auditing (who decided what and when)
    - Data science team (they use past decisions to retrain the model)
    - Looking up a past decision by application ID
    - Running reports ("how many approved this month?")

  TABLES WE CREATE:
    1. decisions        — the main result for each application
    2. stipulations     — the stips attached to each decision (separate table)
    3. decline_reasons  — the reasons for each decline (separate table)

  WHY SEPARATE TABLES FOR STIPS AND DECLINES?
    One application can have MANY stipulations.
    Storing them as a list in one column is bad practice.
    Better to have a separate row per stipulation (this is called
    database normalization — a real SQL concept you'll use everywhere).

  NEW CONCEPTS IN THIS FILE:
    - SQL CREATE TABLE
    - SQL INSERT
    - SQL SELECT with WHERE, ORDER BY, LIMIT
    - SQL JOIN (linking two tables together)
    - Context manager (with statement for safe DB connections)
"""

import sqlite3
import json
import os
from datetime import datetime
from src.decision.decision_engine import FinalDecision


# ─────────────────────────────────────────────────────────────
# DATABASE MANAGER
# ─────────────────────────────────────────────────────────────
class DecisionDatabase:

    DB_PATH = "data/decisions.db"

    def __init__(self):
        os.makedirs("data", exist_ok=True)
        self.connection = sqlite3.connect(self.DB_PATH)
        # Makes rows come back as dict-like objects instead of tuples
        self.connection.row_factory = sqlite3.Row
        self._create_tables()

    # ── CREATE TABLES ──────────────────────────────────────────
    def _create_tables(self):
        """
        Creates all tables if they don't already exist.
        Run this every time — IF NOT EXISTS makes it safe.
        """
        self.connection.executescript("""

            -- Main decisions table: one row per application
            CREATE TABLE IF NOT EXISTS decisions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id  INTEGER NOT NULL UNIQUE,
                applicant_name  TEXT,
                dealer_id       TEXT,
                loan_type       TEXT,
                loan_requested  REAL,
                decision        TEXT    NOT NULL,
                tier            TEXT,
                bid_amount      REAL,
                interest_band   TEXT,
                risk_score      REAL,
                risk_label      TEXT,
                is_counter_offer INTEGER DEFAULT 0,
                decided_at      TEXT,
                created_at      TEXT    DEFAULT (datetime('now'))
            );

            -- Stipulations table: multiple rows per application
            CREATE TABLE IF NOT EXISTS stipulations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id  INTEGER NOT NULL,
                description     TEXT    NOT NULL,
                FOREIGN KEY (application_id) REFERENCES decisions(application_id)
            );

            -- Decline reasons table: multiple rows per application
            CREATE TABLE IF NOT EXISTS decline_reasons (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id  INTEGER NOT NULL,
                reason          TEXT    NOT NULL,
                FOREIGN KEY (application_id) REFERENCES decisions(application_id)
            );

        """)
        self.connection.commit()
        print(f"Decision database ready at '{self.DB_PATH}'")

    # ── SAVE ONE DECISION ──────────────────────────────────────
    def save(self, decision: FinalDecision):
        """
        Saves one FinalDecision to the database.
        Uses INSERT OR REPLACE so re-running doesn't cause duplicates.
        """
        # 1. Save main decision row
        self.connection.execute("""
            INSERT OR REPLACE INTO decisions
            (application_id, applicant_name, dealer_id, loan_type,
             loan_requested, decision, tier, bid_amount, interest_band,
             risk_score, risk_label, is_counter_offer, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision.application_id,
            decision.applicant_name,
            decision.dealer_id,
            decision.loan_type,
            decision.loan_requested,
            decision.decision,
            decision.tier,
            decision.bid_amount,
            decision.interest_band,
            decision.risk_score,
            decision.risk_label,
            int(decision.is_counter_offer),
            decision.decided_at,
        ))

        # 2. Delete old stips for this app (in case of re-run)
        self.connection.execute(
            "DELETE FROM stipulations WHERE application_id = ?",
            (decision.application_id,)
        )
        # Insert each stipulation as its own row
        for stip in decision.stipulations:
            self.connection.execute(
                "INSERT INTO stipulations (application_id, description) VALUES (?, ?)",
                (decision.application_id, stip)
            )

        # 3. Delete old decline reasons and re-insert
        self.connection.execute(
            "DELETE FROM decline_reasons WHERE application_id = ?",
            (decision.application_id,)
        )
        for reason in decision.decline_reasons:
            self.connection.execute(
                "INSERT INTO decline_reasons (application_id, reason) VALUES (?, ?)",
                (decision.application_id, reason)
            )

        self.connection.commit()

    # ── SAVE ALL DECISIONS ─────────────────────────────────────
    def save_all(self, decisions: list[FinalDecision]):
        for d in decisions:
            self.save(d)
        print(f"Saved {len(decisions)} decisions to database")

    # ── GET ONE DECISION BY APPLICATION ID ────────────────────
    def get_by_id(self, application_id: int) -> dict | None:
        """
        Fetches one decision and its stips/reasons from the database.
        Returns a plain dict, or None if not found.

        SQL concept: JOIN — linking the decisions table with the
        stipulations and decline_reasons tables.
        """
        # Fetch main decision
        row = self.connection.execute(
            "SELECT * FROM decisions WHERE application_id = ?",
            (application_id,)
        ).fetchone()

        if row is None:
            return None

        result = dict(row)

        # Fetch stipulations for this application
        stip_rows = self.connection.execute(
            "SELECT description FROM stipulations WHERE application_id = ?",
            (application_id,)
        ).fetchall()
        result["stipulations"] = [r["description"] for r in stip_rows]

        # Fetch decline reasons
        reason_rows = self.connection.execute(
            "SELECT reason FROM decline_reasons WHERE application_id = ?",
            (application_id,)
        ).fetchall()
        result["decline_reasons"] = [r["reason"] for r in reason_rows]

        return result

    # ── GET ALL DECISIONS ──────────────────────────────────────
    def get_all(self, limit: int = 100) -> list[dict]:
        """
        Returns all decisions, newest first.
        'limit' controls how many rows to return.
        """
        rows = self.connection.execute("""
            SELECT * FROM decisions
            ORDER BY decided_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return [dict(row) for row in rows]

    # ── GET DECISIONS BY OUTCOME ───────────────────────────────
    def get_by_decision(self, decision_type: str) -> list[dict]:
        """
        Filter by decision type.
        e.g. get_by_decision("Auto Approved")
        """
        rows = self.connection.execute(
            "SELECT * FROM decisions WHERE decision = ? ORDER BY decided_at DESC",
            (decision_type,)
        ).fetchall()
        return [dict(row) for row in rows]

    # ── SUMMARY STATS ──────────────────────────────────────────
    def get_stats(self) -> dict:
        """
        Returns summary statistics from the database.
        Uses SQL COUNT, AVG, GROUP BY — core SQL concepts.
        """
        # Count by decision type
        counts = self.connection.execute("""
            SELECT decision, COUNT(*) as count
            FROM decisions
            GROUP BY decision
            ORDER BY count DESC
        """).fetchall()

        # Average risk score and bid by tier
        by_tier = self.connection.execute("""
            SELECT
                tier,
                COUNT(*)       as count,
                AVG(risk_score) as avg_risk,
                AVG(bid_amount) as avg_bid
            FROM decisions
            WHERE tier != 'N/A'
            GROUP BY tier
            ORDER BY tier
        """).fetchall()

        return {
            "total":    sum(row["count"] for row in counts),
            "by_decision": {row["decision"]: row["count"] for row in counts},
            "by_tier":  [dict(row) for row in by_tier],
        }

    def close(self):
        self.connection.close()