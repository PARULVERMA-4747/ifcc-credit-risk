"""
Central, version-controlled configuration (Steps 7, 10, 13, 38).
Every business number the credit committee governs lives here, so a
policy change = a reviewed code change with a new MODEL_VERSION.
"""
MODEL_VERSION = "ifcc-pl-scorecard-v1.0.0"
SEED = 42

TARGET = "default_12m"
ID_COL = "application_id"

# age is a protected attribute -> never used as a model input (fair lending)
EXCLUDED_FEATURES = ["age"]
CATEGORICAL = ["employment_type", "home_ownership", "loan_purpose"]

# Feature selection thresholds on Information Value
IV_MIN = 0.02
IV_SUSPICIOUS = 0.5

# Scorecard scaling: 600 points = odds 50:1 (good:bad), every 20 points doubles odds
PDO = 20
BASE_SCORE = 600
BASE_ODDS = 50
SCORE_MIN, SCORE_MAX = 300, 900

# Risk grades (lower bound of score, inclusive)
# Calibrated to this portfolio's score distribution (bad rate ~10.6% -> centre ~550)
GRADES = [("A", 590), ("B", 570), ("C", 550), ("D", 530), ("E", 300)]

# Decision strategy (configurable cutoff) - chosen from reports/cutoff_strategy.csv
APPROVE_CUTOFF = 550     # score >= this -> auto-approve (if no policy rule fires)
REFER_CUTOFF = 530       # REFER_CUTOFF <= score < APPROVE_CUTOFF -> human review
                         # score < REFER_CUTOFF -> decline

# Expected Loss assumptions for unsecured personal loans
LGD = 0.65               # loss given default
EAD_FACTOR = 1.0         # exposure at default = loan amount * factor

# Hard policy rules (Step 7) - applied BEFORE / ON TOP OF the model
POLICY = {
    "min_annual_income": 12_000,       # below -> decline (affordability)
    "max_dti_decline": 0.80,           # DTI above -> decline
    "max_dti_refer": 0.60,             # DTI above -> refer
    "max_delinquencies_refer": 3,      # >= -> refer
    "max_loan_amount_auto": 40_000,    # above -> refer (approval limit)
    "fraud_inquiries": 6,              # many recent inquiries + high LTI -> fraud flag
    "fraud_lti": 0.5,
}

NUM_REASON_CODES = 4
