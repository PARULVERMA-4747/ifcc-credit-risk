"""
Step 8 (Data analysis) + Step 18 (simulate external dependencies)
-----------------------------------------------------------------
Generates a SYNTHETIC but realistic dataset of 25,000 personal-loan
applications for IFCC Bank. No real customer / PII data is used.

Replace this file with a loader for a real dataset (UCI German Credit,
Lending Club, Home Credit) that returns the same columns + `default_12m`
and the rest of the pipeline runs unchanged.
"""
import numpy as np
import pandas as pd
from pathlib import Path

SEED = 42
N = 25_000
ROOT = Path(__file__).resolve().parents[1]


def generate(n: int = N, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # ---- Applicant / demographics --------------------------------------
    age = rng.integers(21, 66, n)                                   # protected -> NOT used in model
    employment_type = rng.choice(["Salaried", "Self-Employed", "Contract", "Unemployed"],
                                 n, p=[0.62, 0.22, 0.12, 0.04])
    employment_years = np.clip(rng.gamma(2.0, 2.5, n), 0, 40).round(1)
    employment_years[employment_type == "Unemployed"] = 0
    home_ownership = rng.choice(["Own", "Mortgage", "Rent"], n, p=[0.25, 0.30, 0.45])

    base_inc = np.where(employment_type == "Salaried", 55_000,
               np.where(employment_type == "Self-Employed", 62_000,
               np.where(employment_type == "Contract", 42_000, 15_000)))
    annual_income = (base_inc * rng.lognormal(0, 0.45, n)).round(-2)

    # ---- Bureau history ------------------------------------------------
    credit_history_years = np.clip(rng.normal((age - 21) * 0.55, 3, n), 0, 45).round(1)
    num_open_accounts = rng.poisson(4, n)
    credit_utilization = np.clip(rng.beta(2, 3, n), 0, 1).round(3)
    num_inquiries_6m = rng.poisson(1.2, n)
    num_delinquencies_2y = rng.poisson(0.35, n)
    existing_monthly_debt = (annual_income / 12 * np.clip(rng.beta(2, 6, n), 0, 0.9)).round(0)

    # ---- Loan terms ----------------------------------------------------
    loan_purpose = rng.choice(["Debt Consolidation", "Home Improvement", "Medical",
                               "Education", "Wedding", "Travel", "Other"],
                              n, p=[0.35, 0.15, 0.10, 0.10, 0.10, 0.08, 0.12])
    loan_amount = np.clip(annual_income * rng.uniform(0.05, 0.6, n), 1_000, 50_000).round(-2)
    loan_term_months = rng.choice([12, 24, 36, 48, 60], n, p=[0.10, 0.20, 0.35, 0.20, 0.15])

    # ---- Derived features (financial analysis) --------------------------
    rate = 0.14 / 12
    new_emi = loan_amount * rate / (1 - (1 + rate) ** -loan_term_months)
    dti = np.clip((existing_monthly_debt + new_emi) / (annual_income / 12), 0, 2).round(3)
    loan_to_income = (loan_amount / annual_income).round(3)

    # ---- True (hidden) risk process -> 12-month default -----------------
    z = (-3.1
         + 2.6 * (dti - 0.35)
         + 1.9 * (credit_utilization - 0.4)
         + 0.55 * num_delinquencies_2y
         + 0.18 * num_inquiries_6m
         - 0.045 * credit_history_years
         - 0.05 * employment_years
         - 0.35 * np.log(annual_income / 50_000)
         + 0.9 * loan_to_income
         + np.select([employment_type == "Unemployed", employment_type == "Contract",
                      employment_type == "Self-Employed"], [1.3, 0.45, 0.2], 0)
         + np.select([home_ownership == "Rent", home_ownership == "Mortgage"], [0.3, 0.05], 0)
         + np.select([loan_purpose == "Travel", loan_purpose == "Wedding",
                      loan_purpose == "Debt Consolidation"], [0.35, 0.25, 0.15], 0)
         + 0.03 * loan_term_months / 12
         + rng.normal(0, 0.55, n))
    pd_true = 1 / (1 + np.exp(-z))
    default_12m = rng.binomial(1, pd_true)

    df = pd.DataFrame({
        "application_id": [f"IFCC-{i:06d}" for i in range(1, n + 1)],
        "age": age,
        "employment_type": employment_type,
        "employment_years": employment_years,
        "home_ownership": home_ownership,
        "annual_income": annual_income,
        "credit_history_years": credit_history_years,
        "num_open_accounts": num_open_accounts,
        "credit_utilization": credit_utilization,
        "num_inquiries_6m": num_inquiries_6m,
        "num_delinquencies_2y": num_delinquencies_2y,
        "existing_monthly_debt": existing_monthly_debt,
        "loan_purpose": loan_purpose,
        "loan_amount": loan_amount,
        "loan_term_months": loan_term_months,
        "dti": dti,
        "loan_to_income": loan_to_income,
        "default_12m": default_12m,
    })

    # Realistic data-quality issue: ~3% missing utilisation, ~2% missing emp years
    miss = rng.random(n)
    df.loc[miss < 0.03, "credit_utilization"] = np.nan
    df.loc[(miss >= 0.03) & (miss < 0.05), "employment_years"] = np.nan
    return df


if __name__ == "__main__":
    out = ROOT / "data" / "applications.csv"
    df = generate()
    df.to_csv(out, index=False)
    print(f"Saved {len(df):,} rows -> {out}  | default rate = {df.default_12m.mean():.2%}")
