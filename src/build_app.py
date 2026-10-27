"""
Rebuilds app/underwriting_desk.html from app/template.html + the latest trained artifacts.
Run after every `python src/train.py` so the web desk uses the same scorecard as the API.
"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

t = (ROOT / "app" / "template.html").read_text(encoding="utf-8")
out = (t.replace("__SCORECARD__", (ROOT / "artifacts" / "scorecard.json").read_text())
        .replace("__META__", (ROOT / "artifacts" / "metadata.json").read_text())
        .replace("__CUTS__", json.dumps(pd.read_csv(ROOT / "reports" / "cutoff_strategy.csv").to_dict("records")))
        .replace("__GRADES__", json.dumps(pd.read_csv(ROOT / "reports" / "grade_table.csv").to_dict("records"))))
(ROOT / "app" / "underwriting_desk.html").write_text(out, encoding="utf-8")
print("Built app/underwriting_desk.html")
