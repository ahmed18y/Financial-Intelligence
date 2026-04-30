import json
from pathlib import Path

import app
import pandas as pd


BASE = Path(__file__).resolve().parent / "static" / "samples"


def _parse(prefix: str):
    ist_path = BASE / f"{prefix}_income.csv"
    bs_path = BASE / f"{prefix}_balance.csv"

    # Samples are CSV files; read them directly and feed parse_statements()
    ist_df = pd.read_csv(ist_path)
    bs_df = pd.read_csv(bs_path)

    ist = app.parse_statements(ist_df)
    bs = app.parse_statements(bs_df)
    return ist, bs


def check_company(prefix: str):
    ist, bs = _parse(prefix)

    ratios = app.calculate_ratios(bs, ist)
    fcf = app.calculate_fcf(bs, ist)
    cap = app.calculate_capital(bs, ist)

    return {
        "company": prefix,
        "ratios": ratios,
        "dupont": ratios.get("dupont", {}),
        "fcf": fcf,
        "capital": cap,
    }


def main():
    out = []
    for prefix in ["company_a", "company_b"]:
        out.append(check_company(prefix))

    # ensure_ascii=True avoids Windows console encoding issues
    print(json.dumps(out, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()

