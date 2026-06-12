"""
Script to generate dummy data for the credit decisioning system.
Run this ONCE to create your sample data files.
"""

import pandas as pd
import numpy as np
from faker import Faker
import os

fake = Faker()
np.random.seed(42)  # So everyone gets the same dummy data

# ─────────────────────────────────────────────
# 1. GENERATE LOAN APPLICATIONS
# ─────────────────────────────────────────────
def generate_applications(n=50):
    loan_types    = ["Home Improvement Loan", "Personal Loan", "Auto Loan"]
    dealer_ids    = ["D001", "D002", "D003", "D004"]

    records = []
    for i in range(1, n + 1):
        income        = round(np.random.uniform(20000, 150000), 2)
        loan_amount   = round(np.random.uniform(1000, 50000), 2)
        has_coapplicant = np.random.choice([True, False], p=[0.3, 0.7])

        records.append({
            "application_id"   : i,
            "first_name"       : fake.first_name(),
            "last_name"        : fake.last_name(),
            "email"            : fake.email(),
            "phone"            : fake.phone_number(),
            "annual_income"    : income,
            "loan_amount"      : loan_amount,
            "loan_type"        : np.random.choice(loan_types),
            "dealer_id"        : np.random.choice(dealer_ids),
            "has_coapplicant"  : has_coapplicant,
            "coapplicant_name" : fake.name() if has_coapplicant else None,
            "coapplicant_income": round(np.random.uniform(15000, 80000), 2) if has_coapplicant else None,
            "state"            : fake.state_abbr(),
            "zip_code"         : fake.zipcode(),
            "submitted_at"     : fake.date_time_between(start_date="-1y", end_date="now").isoformat(),
        })

    return pd.DataFrame(records)


# ─────────────────────────────────────────────
# 2. GENERATE DUMMY CREDIT BUREAU DATA
# ─────────────────────────────────────────────
def generate_credit_bureau(application_ids):
    records = []
    for app_id in application_ids:
        credit_score      = int(np.random.normal(loc=680, scale=80))
        credit_score      = max(300, min(850, credit_score))   # clamp between 300-850
        open_accounts     = np.random.randint(1, 15)
        delinquencies     = np.random.choice([0, 0, 0, 1, 2, 3], p=[0.5, 0.2, 0.1, 0.1, 0.05, 0.05])
        total_debt        = round(np.random.uniform(0, 80000), 2)
        monthly_debt_payments = round(total_debt * 0.02, 2)   # rough 2% of total debt
        bankruptcies      = np.random.choice([0, 1], p=[0.92, 0.08])
        oldest_account_years = round(np.random.uniform(0.5, 25), 1)

        records.append({
            "application_id"        : app_id,
            "credit_score"          : credit_score,
            "open_accounts"         : open_accounts,
            "delinquencies_last_2yr": delinquencies,
            "total_debt"            : total_debt,
            "monthly_debt_payments" : monthly_debt_payments,
            "bankruptcies"          : bankruptcies,
            "oldest_account_years"  : oldest_account_years,
            "bureau_pull_date"      : fake.date_between(start_date="-30d", end_date="today").isoformat(),
        })

    return pd.DataFrame(records)


# ─────────────────────────────────────────────
# 3. GENERATE DEALER RULES (each dealer has different thresholds)
# ─────────────────────────────────────────────
def generate_dealer_rules():
    records = [
        {"dealer_id": "D001", "min_credit_score": 620, "max_loan_amount": 40000, "max_dti_ratio": 0.45, "tier": "Standard"},
        {"dealer_id": "D002", "min_credit_score": 660, "max_loan_amount": 35000, "max_dti_ratio": 0.40, "tier": "Prime"},
        {"dealer_id": "D003", "min_credit_score": 580, "max_loan_amount": 25000, "max_dti_ratio": 0.50, "tier": "SubPrime"},
        {"dealer_id": "D004", "min_credit_score": 700, "max_loan_amount": 50000, "max_dti_ratio": 0.38, "tier": "Super Prime"},
    ]
    return pd.DataFrame(records)


# ─────────────────────────────────────────────
# RUN IT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)

    apps = generate_applications(50)
    apps.to_csv("data/applications.csv", index=False)
    print(f" Generated {len(apps)} applications  →  data/applications.csv")

    bureau = generate_credit_bureau(apps["application_id"].tolist())
    bureau.to_csv("data/credit_bureau.csv", index=False)
    print(f" Generated {len(bureau)} credit bureau records  →  data/credit_bureau.csv")

    rules = generate_dealer_rules()
    rules.to_csv("data/dealer_rules.csv", index=False)
    print(f" Generated dealer rules  →  data/dealer_rules.csv")

    print("\n All data files created inside the  data/  folder.")