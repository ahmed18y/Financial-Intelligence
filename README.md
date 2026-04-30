# Financial Intelligence Platform 🏦

A professional dark-luxury Flask web application for advanced financial statement analysis.

---

## Features
- **Login System** — Admin (edit values) & User roles
- **Upload** — CSV / Excel Income Statement + Balance Sheet with loading bars
- **Formatted Statements** — Professional financial statement display
- **Ratio Analysis** — Liquidity, Asset Management, Debt, Profitability with charts
- **DuPont Structure** — Visual tree: ROE = PM × TAT × EM
- **Free Cash Flow** — Two methods, verified match
- **Capital Metrics** — NWC, Capital Structure, CapEx with donut charts
- **Company Comparison** — Side-by-side with selectable items & charts
- **AI Deep Analysis** — 12-section streaming report (future projections, risk register)
- **AI Chat** — Conversational assistant with full financial context

---

## Quick Start

### 1. Install dependencies
```bash
pip install flask pandas openpyxl werkzeug numpy
```

### 2. Set your Anthropic API key (for AI features)
```bash
export ANTHROPIC_API_KEY=your_key_here
```

### 3. Run
```bash
cd financial_app
python app.py
```

### 4. Open in browser
```
http://localhost:5000
```

---

## Demo Accounts
| Username | Password | Role       |
|----------|----------|------------|
| admin    | admin123 | Admin (can edit values) |
| analyst  | analyst123 | User |

---

## CSV Format
Each CSV file must follow this format:
```
Item, Current_Year, Previous_Year
Net Sales, 1509000, 1350000
Cost of Goods Sold, 750000, 672000
...
```

Sample files are included in `static/samples/` for Company A and B.

---

## Formulas Used

### Liquidity Ratios
- Current Ratio = Current Assets ÷ Current Liabilities
- Quick Ratio = (Current Assets − Inventory) ÷ Current Liabilities
- Cash Ratio = (Cash + Marketable Securities) ÷ Current Liabilities

### Asset Management Ratios
- Total Assets Turnover = Sales ÷ Total Assets
- Current Assets Turnover = Sales ÷ Current Assets
- Fixed Assets Turnover = Sales ÷ Net Fixed Assets

### Debt Management Ratios
- Debt to Assets = Total Debt ÷ Total Assets
- Debt to Equity = Total Debt ÷ Total Equity
- Equity Multiplier = Total Assets ÷ Total Equity
- TIE = EBIT ÷ Interest Paid

### Profitability Ratios
- Profit Margin = (Net Income ÷ Sales) × 100
- ROA = (Net Income ÷ Total Assets) × 100
- ROE = (Net Income ÷ Total Equity) × 100

### DuPont Identity
ROE = Profit Margin × Total Assets Turnover × Equity Multiplier

### Free Cash Flow — Method 1
- OCF = EBIT + Depreciation − Taxes
- NCS = Ending Net Fixed Assets − Beginning NFA + Depreciation
- ΔNWC = Ending NWC − Beginning NWC
- FCF = OCF − NCS − ΔNWC

### Free Cash Flow — Method 2
- CF to Creditors = Interest Paid − Net New Borrowing
- CF to Stockholders = Dividends Paid − Net New Equity
- FCF = CF to Creditors + CF to Stockholders

### Capital Metrics
- Net Working Capital = Current Assets − Current Liabilities
- Capital Structure = Long-Term Debt + Equity
- Capital Budgeting ≈ Net Fixed Assets
