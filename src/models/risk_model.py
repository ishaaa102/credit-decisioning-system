"""
src/models/risk_model.py

WHAT THIS FILE DOES:
  - Generates dummy historical loan data to train on
  - Trains a Logistic Regression model using scikit-learn
  - Saves the trained model to a file so we don't retrain every time
  - Loads the model and scores new applications
  - Returns a risk score between 0.0 and 1.0

WHAT IS A RISK SCORE?
  0.0 = Very safe applicant (low risk of default)
  1.0 = Very risky applicant (high risk of default)

  Score < 0.3  → likely Approve
  Score 0.3–0.6 → likely Pending (needs review)
  Score > 0.6  → likely Decline

WHAT IS LOGISTIC REGRESSION?
  A simple ML model that takes numbers as input
  and outputs a probability between 0 and 1.
  Perfect for yes/no decisions like "will this person default?"
"""

import os
import numpy as np
import pandas as pd
import joblib
from dataclasses import dataclass

from sklearn.linear_model    import LogisticRegression
from sklearn.preprocessing   import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics         import accuracy_score, classification_report
from sklearn.pipeline        import Pipeline

from src.adm_lookup.adm_lookup import FullyEnrichedApplication


# ─────────────────────────────────────────────────────────────
# DATA CLASS — Result of scoring one application
# ─────────────────────────────────────────────────────────────
@dataclass
class RiskScore:
    application_id: int
    risk_score:     float   # 0.0 to 1.0
    risk_label:     str     # "Low Risk", "Medium Risk", "High Risk"
    aca:            float   # Available Credit Amount (max we'd lend them)

    def summary(self) -> str:
        return (
            f"[App {self.application_id}] "
            f"Risk Score: {self.risk_score:.3f} | "
            f"Label: {self.risk_label} | "
            f"ACA: ${self.aca:,.0f}"
        )


# ─────────────────────────────────────────────────────────────
# RISK MODEL — Train, save, load, predict
# ─────────────────────────────────────────────────────────────
class RiskModel:

    MODEL_PATH = "data/risk_model.joblib"

    # Features we use to train and predict
    # These must be numbers — no text allowed in ML models
    FEATURE_COLUMNS = [
        "credit_score",
        "annual_income",
        "loan_amount",
        "debt_to_income_ratio",
        "delinquencies_last_2yr",
        "bankruptcies",
        "loan_to_income_ratio",
        "is_homeowner",
        "previous_defaults",
        "years_employed",
        "open_accounts",
        "oldest_account_years",
    ]

    def __init__(self):
        self.pipeline = None   # will hold the trained model

    # ── STEP 1: Generate dummy training data ───────────────────
    def _generate_training_data(self, n_samples: int = 2000) -> pd.DataFrame:
        """
        Creates fake historical loan outcomes to train on.
        In real life you'd use actual past approved/declined loan data.

        The logic below creates REALISTIC patterns:
          - Low credit score  → more likely to default (label=1)
          - High DTI          → more likely to default
          - Bankruptcy        → very likely to default
          - High income       → less likely to default
        """
        np.random.seed(42)

        credit_scores     = np.random.normal(680, 80, n_samples).clip(300, 850).astype(int)
        annual_incomes    = np.random.uniform(20000, 150000, n_samples)
        loan_amounts      = np.random.uniform(1000, 50000, n_samples)
        dti_ratios        = np.random.uniform(0.05, 0.70, n_samples)
        delinquencies     = np.random.choice([0,0,0,1,2,3], n_samples)
        bankruptcies      = np.random.choice([0,1], n_samples, p=[0.92, 0.08])
        loan_to_income    = loan_amounts / annual_incomes
        is_homeowner      = np.random.choice([0,1], n_samples, p=[0.67, 0.33])
        previous_defaults = np.random.choice([0,1,2], n_samples, p=[0.85, 0.12, 0.03])
        years_employed    = np.random.uniform(0, 30, n_samples)
        open_accounts     = np.random.randint(1, 15, n_samples)
        oldest_account    = np.random.uniform(0.5, 25, n_samples)

        # ── Build the target variable (did they default?) ──────
        # We compute a "default probability" based on the features
        # then randomly assign outcomes based on that probability.
        # This creates realistic correlations in the training data.
        default_prob = (
            (850 - credit_scores) / 850 * 0.35   # low score = higher default
            + dti_ratios * 0.25                   # high DTI = higher default
            + bankruptcies * 0.20                 # bankruptcy = much higher
            + delinquencies * 0.08                # delinquencies add risk
            + previous_defaults * 0.10            # prior defaults add risk
            - is_homeowner * 0.05                 # homeowner = slightly safer
            - (annual_incomes / 150000) * 0.10    # higher income = safer
        ).clip(0, 1)

        # Randomly assign 0 (paid back) or 1 (defaulted) based on probability
        defaulted = np.array([
            np.random.choice([0, 1], p=[1 - p, p])
            for p in default_prob
        ])

        df = pd.DataFrame({
            "credit_score":           credit_scores,
            "annual_income":          annual_incomes,
            "loan_amount":            loan_amounts,
            "debt_to_income_ratio":   dti_ratios,
            "delinquencies_last_2yr": delinquencies,
            "bankruptcies":           bankruptcies,
            "loan_to_income_ratio":   loan_to_income,
            "is_homeowner":           is_homeowner,
            "previous_defaults":      previous_defaults,
            "years_employed":         years_employed,
            "open_accounts":          open_accounts,
            "oldest_account_years":   oldest_account,
            "defaulted":              defaulted,
        })

        return df

    # ── STEP 2: Train the model ────────────────────────────────
    def train(self):
        """
        Generates training data, trains a Logistic Regression model,
        prints accuracy, and saves it to a file.
        """
        print("\n  Training Risk Scoring Model...")

        df = self._generate_training_data(2000)

        X = df[self.FEATURE_COLUMNS]   # features (inputs)
        y = df["defaulted"]            # target  (what we're predicting)

        # Split into 80% training, 20% testing
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # ── Pipeline: Scale numbers → then train model ─────────
        # StandardScaler normalizes all numbers to the same range
        # This is important because credit_score (300-850) and
        # annual_income (20k-150k) are very different scales
        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("model",  LogisticRegression(random_state=42, max_iter=1000))
        ])

        self.pipeline.fit(X_train, y_train)

        # ── Evaluate the model ─────────────────────────────────
        y_pred = self.pipeline.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        print(f"Model trained on {len(X_train)} samples")
        print(f"Test accuracy: {accuracy:.1%}")
        print(f"\n  Classification Report:")
        print(classification_report(y_test, y_pred,
                                    target_names=["Paid Back", "Defaulted"]))

        # Save model to file so we don't retrain every run
        os.makedirs("data", exist_ok=True)
        joblib.dump(self.pipeline, self.MODEL_PATH)
        print(f"  💾  Model saved to '{self.MODEL_PATH}'")

    # ── STEP 3: Load saved model from file ────────────────────
    def load(self):
        """
        Loads the previously trained model from disk.
        Call this instead of train() once the model is already trained.
        """
        if not os.path.exists(self.MODEL_PATH):
            raise FileNotFoundError(
                f"No model found at '{self.MODEL_PATH}'. Run train() first."
            )
        self.pipeline = joblib.load(self.MODEL_PATH)
        print(f"Risk model loaded from '{self.MODEL_PATH}'")

    # ── STEP 4: Calculate ACA (Available Credit Amount) ────────
    @staticmethod
    def _calculate_aca(annual_income: float,
                       credit_score: int,
                       dti: float,
                       risk_score: float) -> float:
        """
        ACA = how much we're willing to lend this person.

        Logic:
          - Base: 30% of annual income
          - Adjusted up for high credit scores
          - Adjusted down for high risk scores and high DTI
          - Clamped between $1,000 and $50,000
        """
        base = annual_income * 0.30

        # Credit score multiplier: 850 score = 1.2x, 300 score = 0.5x
        score_mult = 0.5 + ((credit_score - 300) / (850 - 300)) * 0.7

        # Risk multiplier: 0 risk = 1.0x, 1.0 risk = 0.2x
        risk_mult = 1.0 - (risk_score * 0.8)

        # DTI multiplier: 0 DTI = 1.0x, 0.5 DTI = 0.5x
        dti_mult = max(0.2, 1.0 - dti)

        aca = base * score_mult * risk_mult * dti_mult
        return round(max(1000, min(50000, aca)), 2)

    # ── STEP 5: Score one application ─────────────────────────
    def _score_one(self, app: FullyEnrichedApplication) -> RiskScore:
        e = app.enriched_app   # shortcut

        # Build feature row — must match FEATURE_COLUMNS exactly
        features = pd.DataFrame([{
            "credit_score":           e.credit_score,
            "annual_income":          e.application.annual_income,
            "loan_amount":            e.application.loan_amount,
            "debt_to_income_ratio":   e.debt_to_income_ratio,
            "delinquencies_last_2yr": e.delinquencies_last_2yr,
            "bankruptcies":           e.bankruptcies,
            "loan_to_income_ratio":   e.application.loan_to_income_ratio,
            "is_homeowner":           int(app.adm_data.is_homeowner),
            "previous_defaults":      app.adm_data.previous_defaults,
            "years_employed":         app.adm_data.years_employed,
            "open_accounts":          e.open_accounts,
            "oldest_account_years":   e.oldest_account_years,
        }])

        # predict_proba returns [[prob_no_default, prob_default]]
        # We take the second value: probability of defaulting
        risk_score = float(self.pipeline.predict_proba(features)[0][1])

        # Label based on score
        if risk_score < 0.30:
            label = "Low Risk"
        elif risk_score < 0.60:
            label = "Medium Risk"
        else:
            label = "High Risk"

        aca = self._calculate_aca(
            e.application.annual_income,
            e.credit_score,
            e.debt_to_income_ratio,
            risk_score,
        )

        return RiskScore(
            application_id = app.application_id,
            risk_score     = round(risk_score, 4),
            risk_label     = label,
            aca            = aca,
        )

    # ── STEP 6: Score all applications ────────────────────────
    def score_all(self, apps: list[FullyEnrichedApplication]) -> list[RiskScore]:
        """
        Scores every application and returns a list of RiskScore objects.
        """
        if self.pipeline is None:
            raise RuntimeError("Model not loaded. Call train() or load() first.")

        scores = [self._score_one(app) for app in apps]
        print(f"\nScored {len(scores)} applications")
        return scores