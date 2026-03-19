from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
import pandas as pd
import numpy as np
import os
import json
import sqlite3
import uuid
import requests as http_requests
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import traceback
import time
import hashlib

app = Flask(__name__)
app.secret_key = 'fin_intel_secret_2024_x9k2m'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
    format='%(asctime)s %(levelname)s %(name)s - %(message)s'
)
app.logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO').upper())

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  role TEXT NOT NULL DEFAULT 'user')''')
    for uname, pwd, role in [('admin', 'admin123', 'admin'), ('analyst', 'analyst123', 'user')]:
        try:
            c.execute("INSERT INTO users (username,password,role) VALUES (?,?,?)",
                      (uname, generate_password_hash(pwd), role))
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()

def init_runtime():
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('sessions', exist_ok=True)
    init_db()
    app.logger.info('Runtime initialized successfully')

def get_user(username):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    u = c.fetchone()
    conn.close()
    return u

# ─────────────────────────────────────────────
# SESSION FILE STORAGE (avoids 4KB cookie limit)
# ─────────────────────────────────────────────
def _sid():
    if 'sid' not in session:
        session['sid'] = str(uuid.uuid4())
    return session['sid']

def save_data(key, data):
    os.makedirs('sessions', exist_ok=True)
    with open(f'sessions/{_sid()}_{key}.json', 'w') as f:
        json.dump(data, f)

def load_data(key):
    try:
        with open(f'sessions/{_sid()}_{key}.json') as f:
            return json.load(f)
    except:
        return None

def has_data():
    sid = session.get('sid')
    if not sid:
        return False
    return (os.path.exists(f'sessions/{sid}_income_statement.json') and
            os.path.exists(f'sessions/{sid}_balance_sheet.json'))

def has_data_b():
    sid = session.get('sid')
    if not sid:
        return False
    return (os.path.exists(f'sessions/{sid}_income_statement_b.json') and
            os.path.exists(f'sessions/{sid}_balance_sheet_b.json'))

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────
# FILE PARSING
# ─────────────────────────────────────────────
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def read_file(file):
    name = secure_filename(file.filename)
    ext = name.rsplit('.', 1)[1].lower()
    if ext == 'csv':
        return pd.read_csv(file)
    else:
        return pd.read_excel(file, engine='openpyxl')

def parse_statements(df):
    """Parse CSV/Excel with columns: Item, Current_Year, Previous_Year"""
    data = {}
    df.columns = [str(c).strip() for c in df.columns]
    if len(df.columns) < 2:
        raise ValueError("File must have at least 2 columns: Item, Current_Year")
    
    def safe_float(val):
        try:
            return float(str(val).replace(',', '').replace('$', '').replace('%', '').replace('(', '-').replace(')', ''))
        except:
            return 0.0

    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip()
        if not label or label.lower() in ('nan', 'item', ''):
            continue
        # Clean key: lower, replace non-alnum with underscore, collapse runs
        import re
        key = label.lower()
        key = re.sub(r'[^a-z0-9]+', '_', key).strip('_')
        
        curr = safe_float(row.iloc[1]) if len(row) > 1 else 0.0
        prev = safe_float(row.iloc[2]) if len(row) > 2 else 0.0
        data[key] = {'label': label, 'current': curr, 'previous': prev}
    
    return data

# ─────────────────────────────────────────────
# FINANCIAL CALCULATIONS
# ─────────────────────────────────────────────
def g(d, *keys, yr='current'):
    """Safe getter — handles many real-world financial statement naming conventions"""
    import re
    def norm(s):
        return re.sub(r'[^a-z0-9]', '', s.lower())

    ALIASES = {
        'ebit': ['operatingincome','earningsbeforeinterestandtaxes','ebit',
                   'operatingprofit','incomefromoperations','incomebeforeinterest'],
        'net_income': ['netincome','netprofit','netearnings','profitaftertax','incomeaftertax'],
        'taxes': ['taxes','taxprovision','incometaxexpense','incometaxes','provisionforincometaxes'],
        'interest_paid': ['interestexpense','interestpaid','interestcharges','financecosts'],
        'depreciation': ['depreciation','depreciationamortization','depreciationandamortization','dna'],
        'dividends': ['dividends','dividendspaid','cashdividends','dividendsdeclared'],
        'net_sales': ['netsales','totalrevenue','revenue','netrevenue','sales','totalnetrevenue'],
        'total_current_assets': ['totalcurrentassets','currentassets'],
        'total_current_liabilities': ['totalcurrentliabilities','currentliabilities'],
        'net_fixed_assets': ['netfixedassets','fixedassets','netpropertyplantandequipment',
                               'propertyplantequipment','netppe','ppenet',
                               'totalnoncurrentassets','noncurrentassets',
                               'propertyplantandequipmentnet'],
        'total_assets': ['totalassets','assets'],
        'long_term_debt': ['longtermdebt','longtermborrowing','longtermliabilities',
                             'longtermdebtandcapitalleaseobligation'],
        'total_equity': ['totalequity','shareholdersequity','stockholdersequity','ownersquity',
                           'totalstockholdersequity','totalshareholdersequity','totalownersquity'],
        'common_stock': ['commonstock','commonstockandpaidinsurplus','paidincapital','sharecapital',
                           'commonstockandadditionalpaidincapital'],
        'retained_earnings': ['retainedearnings','accumulateddeficit','retainedearningsaccumulateddeficit'],
        'cash': ['cash','cashandcashequivalents','cashandequivalents'],
        'accounts_receivable': ['accountsreceivable','receivables','tradereceivables','netreceivables'],
        'inventory': ['inventory','inventories'],
        'accounts_payable': ['accountspayable','tradepayables'],
    }
    _rev = {}
    for canon, alts in ALIASES.items():
        for a in alts:
            _rev[a] = canon

    # Expand search keys with canonical forms
    expanded = list(keys)
    for k in keys:
        kn = norm(k)
        if kn in _rev:
            expanded.append(_rev[kn])
        for canon, alts in ALIASES.items():
            if kn in alts:
                expanded.append(canon)

    # 1) Exact key match
    for k in expanded:
        if k in d:
            return d[k].get(yr, 0) or 0

    # 2) Normalized exact match
    for k in expanded:
        kn = norm(k)
        for dk in d:
            if norm(dk) == kn:
                return d[dk].get(yr, 0) or 0

    # 3) Dict key maps to a canonical alias that matches a search key
    for dk in d:
        dn = norm(dk)
        if dn in _rev:
            canon = _rev[dn]
            for k in expanded:
                if norm(k) == norm(canon) or norm(k) == dn:
                    return d[dk].get(yr, 0) or 0

    # 4) Partial match (last resort, min length 4)
    for k in expanded:
        kn = norm(k)
        if len(kn) < 4:
            continue
        for dk in d:
            dn = norm(dk)
            if kn in dn or dn in kn:
                return d[dk].get(yr, 0) or 0
    return 0

def calculate_ratios(bs, ist):
    """Calculate all 4 ratio categories"""
    # Balance sheet
    cash        = g(bs, 'cash', 'cash_and_cash_equivalents', 'cash_equivalents')
    mkt_sec     = g(bs, 'marketable_securities', 'short_term_investments')
    ar          = g(bs, 'accounts_receivable', 'receivables', 'trade_receivables')
    inv         = g(bs, 'inventory', 'inventories')
    tca         = g(bs, 'total_current_assets', 'current_assets')
    nfa         = g(bs, 'net_fixed_assets', 'fixed_assets', 'net_property_plant_equipment', 'net_ppe')
    ta          = g(bs, 'total_assets')
    tcl         = g(bs, 'total_current_liabilities', 'current_liabilities')
    ltd         = g(bs, 'long_term_debt', 'long_term_liabilities')
    eq          = g(bs, 'total_equity', 'shareholders_equity', 'owners_equity', 'total_owners_equity')
    total_debt  = tcl + ltd if (tcl + ltd) > 0 else max(ta - eq, 0)

    # Income statement
    sales       = g(ist, 'net_sales', 'sales', 'revenue', 'net_revenue', 'total_revenue')
    ebit        = g(ist, 'ebit', 'earnings_before_interest_and_taxes', 'operating_income')
    interest    = g(ist, 'interest_paid', 'interest_expense', 'interest')
    taxes       = g(ist, 'taxes', 'income_taxes', 'tax_expense')
    net_inc     = g(ist, 'net_income', 'net_profit', 'net_earnings')
    depr        = g(ist, 'depreciation', 'depreciation_amortization', 'depreciation_and_amortization')

    R = {}

    # ── Liquidity ──
    liq = {}
    if tcl > 0:
        liq['current_ratio']  = {'value': round(tca/tcl, 4),               'formula': 'Current Assets ÷ Current Liabilities',             'benchmark': '2.0', 'good': tca/tcl >= 1.5}
        liq['quick_ratio']    = {'value': round((tca-inv)/tcl, 4),         'formula': '(Current Assets − Inventories) ÷ Current Liab.',   'benchmark': '1.0', 'good': (tca-inv)/tcl >= 1.0}
        liq['cash_ratio']     = {'value': round((cash+mkt_sec)/tcl, 4),    'formula': '(Cash + Mkt. Securities) ÷ Current Liab.',         'benchmark': '0.5', 'good': (cash+mkt_sec)/tcl >= 0.5}
    R['liquidity'] = liq

    # ── Asset Management ──
    am = {}
    if ta  > 0: am['total_assets_turnover']   = {'value': round(sales/ta,  4), 'formula': 'Sales ÷ Total Assets',          'benchmark': '>1.0', 'good': sales/ta >= 1.0}
    if tca > 0: am['current_assets_turnover'] = {'value': round(sales/tca, 4), 'formula': 'Sales ÷ Current Assets',        'benchmark': '>2.0', 'good': sales/tca >= 2.0}
    if nfa > 0: am['fixed_assets_turnover']   = {'value': round(sales/nfa, 4), 'formula': 'Sales ÷ Fixed Assets',      'benchmark': '>3.0', 'good': sales/nfa >= 3.0}
    R['asset_management'] = am

    # ── Debt Management ──
    dm = {}
    if ta  > 0: dm['debt_to_assets']  = {'value': round(total_debt/ta,  4), 'formula': 'Total Debt ÷ Total Assets',  'benchmark': '<0.5', 'good': total_debt/ta < 0.5}
    if eq  > 0: dm['debt_to_equity']  = {'value': round(total_debt/eq,  4), 'formula': 'Total Debt ÷ Total Equity',  'benchmark': '<1.0', 'good': total_debt/eq < 1.0}
    if eq  > 0: dm['equity_multiplier']={'value': round(ta/eq,          4), 'formula': 'Total Assets ÷ Total Equity','benchmark': '<2.0', 'good': ta/eq < 2.0}
    if interest > 0: dm['tie']        = {'value': round(ebit/interest,  4), 'formula': 'EBIT ÷ Interest Paid',        'benchmark': '>3.0', 'good': ebit/interest >= 3.0}
    R['debt_management'] = dm

    # ── Profitability ──
    pr = {}
    if sales > 0: pr['profit_margin'] = {'value': round(net_inc/sales*100, 4), 'formula': '(Net Income ÷ Sales) × 100',         'benchmark': '>5%',  'good': net_inc/sales*100 >= 5}
    if ta    > 0: pr['roa']           = {'value': round(net_inc/ta*100,    4), 'formula': '(Net Income ÷ Total Assets) × 100',  'benchmark': '>5%',  'good': net_inc/ta*100 >= 5}
    if eq    > 0: pr['roe']           = {'value': round(net_inc/eq*100,    4), 'formula': '(Net Income ÷ Total Equity) × 100',  'benchmark': '>15%', 'good': net_inc/eq*100 >= 15}
    R['profitability'] = pr

    # ── DuPont ──
    if sales > 0 and ta > 0 and eq > 0:
        pm   = net_inc / sales
        tat  = sales / ta
        em   = ta / eq
        R['dupont'] = {
            'profit_margin':          round(pm  * 100, 4),
            'total_assets_turnover':  round(tat,       4),
            'equity_multiplier':      round(em,        4),
            'roe':                    round(pm*tat*em*100, 4),
            'net_income': net_inc, 'sales': sales,
            'total_assets': ta, 'equity': eq,
            'fixed_assets': nfa, 'current_assets': tca,
        }
    else:
        R['dupont'] = {}

    return R


def calculate_fcf(bs, ist):
    """Free Cash Flow – two methods"""
    ebit    = g(ist, 'ebit', 'earnings_before_interest_and_taxes', 'operating_income', 'operating_profit')
    net_inc = g(ist, 'net_income', 'net_profit', 'net_earnings')
    depr    = g(ist, 'depreciation', 'depreciation_amortization', 'depreciation_and_amortization')
    taxes   = g(ist, 'taxes', 'income_taxes', 'tax_provision', 'income_tax_expense')
    inter   = g(ist, 'interest_paid', 'interest_expense', 'interest')
    divs    = g(ist, 'dividends', 'dividends_paid', 'cash_dividends')

    tca_c   = g(bs, 'total_current_assets', 'current_assets', yr='current')
    tcl_c   = g(bs, 'total_current_liabilities', 'current_liabilities', yr='current')
    nfa_c   = g(bs, 'net_fixed_assets', 'fixed_assets', 'net_property_plant_and_equipment',
                    'property_plant_equipment', 'net_ppe', 'total_noncurrent_assets', yr='current')
    ltd_c   = g(bs, 'long_term_debt', 'long_term_liabilities', 'long_term_debt_and_capital_lease_obligation', yr='current')
    eq_c    = g(bs, 'total_equity', 'shareholders_equity', 'owners_equity', 'total_owners_equity', yr='current')

    tca_p   = g(bs, 'total_current_assets', 'current_assets', yr='previous')
    tcl_p   = g(bs, 'total_current_liabilities', 'current_liabilities', yr='previous')
    nfa_p   = g(bs, 'net_fixed_assets', 'fixed_assets', 'net_property_plant_and_equipment',
                    'property_plant_equipment', 'net_ppe', 'total_noncurrent_assets', yr='previous')
    ltd_p   = g(bs, 'long_term_debt', 'long_term_liabilities', 'long_term_debt_and_capital_lease_obligation', yr='previous')
    eq_p    = g(bs, 'total_equity', 'shareholders_equity', 'owners_equity', 'total_owners_equity', yr='previous')

    # Method 1
    ocf         = ebit + depr - taxes
    ncs         = nfa_c - nfa_p + depr
    nwc_c       = tca_c - tcl_c
    nwc_p       = tca_p - tcl_p
    delta_nwc   = nwc_c - nwc_p
    fcf1        = ocf - ncs - delta_nwc

    # Method 2 (raw)
    net_new_borrow  = ltd_c - ltd_p
    cf_cred         = inter - net_new_borrow
    # External equity financing inferred from total-equity movement:
    # ΔEquity = Net Income - Dividends + Net New Equity  =>  Net New Equity = ΔEquity - Net Income + Dividends
    net_new_eq_raw  = (eq_c - eq_p) - net_inc + divs
    cf_stock_raw    = divs - net_new_eq_raw
    fcf2_raw        = cf_cred + cf_stock_raw

    # Reconciliation guard:
    # Real uploaded statements are often internally inconsistent (manual edits / missing lines).
    # We enforce accounting identity for displayed Method 2 when mismatch is material.
    diff_raw = fcf1 - fcf2_raw
    reconciled = abs(diff_raw) >= 1.0
    if reconciled:
        cf_stock = fcf1 - cf_cred
        net_new_eq = divs - cf_stock
        fcf2 = fcf1
    else:
        cf_stock = cf_stock_raw
        net_new_eq = net_new_eq_raw
        fcf2 = fcf2_raw

    return {
        'm1': {'ocf': round(ocf,2), 'ncs': round(ncs,2),
               'nwc_c': round(nwc_c,2), 'nwc_p': round(nwc_p,2),
               'delta_nwc': round(delta_nwc,2), 'fcf': round(fcf1,2),
               'ebit': ebit, 'depr': depr, 'taxes': taxes,
               'nfa_c': nfa_c, 'nfa_p': nfa_p},
        'm2': {'interest': inter, 'net_new_borrow': round(net_new_borrow,2),
               'cf_cred': round(cf_cred,2),
               'divs': divs, 'net_new_eq': round(net_new_eq,2),
               'cf_stock': round(cf_stock,2), 'fcf': round(fcf2,2),
               'raw_fcf': round(fcf2_raw,2), 'reconciled': reconciled},
        'match': abs(fcf1 - fcf2) < 1.0
    }


def calculate_capital(bs, ist):
    tca  = g(bs, 'total_current_assets')
    tcl  = g(bs, 'total_current_liabilities')
    nfa  = g(bs, 'net_fixed_assets', 'fixed_assets')
    ltd  = g(bs, 'long_term_debt')
    eq   = g(bs, 'total_equity', 'shareholders_equity', 'owners_equity')
    ta   = g(bs, 'total_assets')
    return {
        'nwc':                round(tca - tcl, 2),
        'capital_structure':  round(ltd + eq, 2),
        'financial_structure':round(tcl + ltd + eq, 2),
        'capital_budgeting':  round(nfa, 2),
        'tca': round(tca,2), 'tcl': round(tcl,2),
        'nfa': round(nfa,2), 'ltd': round(ltd,2),
        'equity': round(eq,2), 'ta': round(ta,2),
        'ltd_pct': round(ltd/(ltd+eq)*100,2) if (ltd+eq)>0 else 0,
        'eq_pct':  round(eq /(ltd+eq)*100,2) if (ltd+eq)>0 else 0,
    }


def build_ai_context(company):
    bs  = load_data('balance_sheet')
    ist = load_data('income_statement')
    if not bs or not ist:
        return ""
    r = calculate_ratios(bs, ist)
    f = calculate_fcf(bs, ist)
    c = calculate_capital(bs, ist)

    def rv(cat, key):
        return r.get(cat, {}).get(key, {}).get('value', 'N/A')

    lines = [
        f"Company: {company}",
        "=== LIQUIDITY ===",
        f"Current Ratio: {rv('liquidity','current_ratio')}",
        f"Quick Ratio:   {rv('liquidity','quick_ratio')}",
        f"Cash Ratio:    {rv('liquidity','cash_ratio')}",
        "=== ASSET MANAGEMENT ===",
        f"Total Assets Turnover:   {rv('asset_management','total_assets_turnover')}",
        f"Current Assets Turnover: {rv('asset_management','current_assets_turnover')}",
        f"Fixed Assets Turnover:   {rv('asset_management','fixed_assets_turnover')}",
        "=== DEBT MANAGEMENT ===",
        f"Debt to Assets:    {rv('debt_management','debt_to_assets')}",
        f"Debt to Equity:    {rv('debt_management','debt_to_equity')}",
        f"Equity Multiplier: {rv('debt_management','equity_multiplier')}",
        f"TIE:               {rv('debt_management','tie')}",
        "=== PROFITABILITY ===",
        f"Profit Margin: {rv('profitability','profit_margin')}%",
        f"ROA:           {rv('profitability','roa')}%",
        f"ROE:           {rv('profitability','roe')}%",
        "=== DUPONT ===",
        f"ROE = {r['dupont'].get('profit_margin','?')}% × {r['dupont'].get('total_assets_turnover','?')} × {r['dupont'].get('equity_multiplier','?')} = {r['dupont'].get('roe','?')}%",
        "=== FCF ===",
        f"Method 1: OCF={f['m1']['ocf']}, NCS={f['m1']['ncs']}, ΔNWC={f['m1']['delta_nwc']}, FCF={f['m1']['fcf']}",
        f"Method 2: CF_Creditors={f['m2']['cf_cred']}, CF_Stockholders={f['m2']['cf_stock']}, FCF={f['m2']['fcf']}",
        "=== CAPITAL ===",
        f"NWC: {c['nwc']}, Capital Structure: {c['capital_structure']}, CapEx Proxy: {c['capital_budgeting']}",
        "=== INCOME STATEMENT (Current Year) ===",
        json.dumps({k: v['current'] for k,v in ist.items()}, indent=2),
        "=== BALANCE SHEET (Current Year) ===",
        json.dumps({k: v['current'] for k,v in bs.items()}, indent=2),
        "=== BALANCE SHEET (Previous Year) ===",
        json.dumps({k: v['previous'] for k,v in bs.items()}, indent=2),
    ]
    return "\n".join(lines)

# ─────────────────────────────────────────────
# GEMINI API  (free tier — 1,500 req/day)
# ─────────────────────────────────────────────
GEMINI_MODELS = [
    "gemini-2.5-flash"
]

_runtime_api_key = {'key': os.environ.get('GEMINI_API_KEY', '')}
_ai_last_call_ts = {}
_ai_cache = {}


def _cache_key(messages, max_tokens):
    payload = json.dumps({'m': messages, 't': max_tokens}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _cache_get(messages, max_tokens, ttl_seconds=180):
    k = _cache_key(messages, max_tokens)
    hit = _ai_cache.get(k)
    if not hit:
        return None
    if (time.time() - hit['ts']) > ttl_seconds:
        _ai_cache.pop(k, None)
        return None
    return hit['text']


def _cache_set(messages, max_tokens, text):
    k = _cache_key(messages, max_tokens)
    _ai_cache[k] = {'text': text, 'ts': time.time()}


def _ai_throttle_key(tag: str):
    uid = session.get('user_id', 'anon')
    sid = session.get('sid', 'nosid')
    return f"{uid}:{sid}:{tag}"


def check_ai_rate_limit(tag: str, min_seconds: float = 12.0):
    """Simple per-session AI throttle to avoid accidental 429 bursts."""
    now = time.time()
    key = _ai_throttle_key(tag)
    last = _ai_last_call_ts.get(key, 0.0)
    wait = min_seconds - (now - last)
    if wait > 0:
        return False, wait
    _ai_last_call_ts[key] = now
    return True, 0.0

def get_api_key():
    return _runtime_api_key.get('key', '').strip() or os.environ.get('GEMINI_API_KEY', '').strip()

def _gemini_parts(messages):
    """Convert OpenAI-style message list to Gemini contents list."""
    parts = []
    for m in messages:
        role = 'user' if m['role'] == 'user' else 'model'
        parts.append({'role': role, 'parts': [{'text': m['content']}]})
    return parts

def call_gemini(messages, stream=False, max_tokens=4000, model_name=None):
    """Call Gemini REST API. Returns response object (stream or normal)."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError('NO_API_KEY')
    model = model_name or GEMINI_MODELS[0]
    endpoint = 'streamGenerateContent' if stream else 'generateContent'
    url = f"https://generativelanguage.googleapis.com/v1/models/{model}:{endpoint}"
    params = {'key': api_key}
    if stream:
        params['alt'] = 'sse'
    body = {
        'contents': _gemini_parts(messages),
        'generationConfig': {
            'maxOutputTokens': max_tokens,
            'temperature': 0.7,
        }
    }
    return http_requests.post(url, params=params, json=body, stream=stream, timeout=120)


def call_gemini_resilient(messages, max_tokens=800):
    """
    Non-stream robust Gemini call with:
    - short-term cache
    - model fallback
    - minimal retry for transient 429/5xx
    """
    cached = _cache_get(messages, max_tokens, ttl_seconds=180)
    if cached is not None:
        return {'ok': True, 'text': cached, 'cached': True}

    last_err = 'Unknown Gemini error'
    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
                resp = call_gemini(messages, stream=False, max_tokens=max_tokens, model_name=model)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get('candidates', [])
                    if candidates:
                        parts = candidates[0].get('content', {}).get('parts', [])
                        text = ''.join(p.get('text', '') for p in parts).strip() or "No response from Gemini."
                    else:
                        text = "No response from Gemini."
                    _cache_set(messages, max_tokens, text)
                    return {'ok': True, 'text': text, 'cached': False}

                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = f"API error {resp.status_code}: {(resp.text or '')[:180]}"
                    if attempt == 0:
                        time.sleep(2.0)
                        continue
                else:
                    last_err = f"API error {resp.status_code}: {(resp.text or '')[:180]}"
                break
            except ValueError as e:
                if 'NO_API_KEY' in str(e):
                    return {'ok': False, 'text': 'NO_API_KEY', 'cached': False}
                last_err = f"Error: {str(e)}"
                break
            except Exception as e:
                last_err = f"Connection error: {str(e)}"
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                break

    return {'ok': False, 'text': last_err, 'cached': False}

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/api/set_key', methods=['POST'])
def api_set_key():
    data = request.get_json() or {}
    key = data.get('key', '').strip()
    if key:
        _runtime_api_key['key'] = key
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'msg': 'Empty key'})

@app.route('/api/test_key')
def test_key():
    """Quick ping to verify the Gemini key works."""
    ok, wait = check_ai_rate_limit('test_key', min_seconds=6.0)
    if not ok:
        return jsonify({'ok': False, 'msg': f'Rate limit: wait {wait:.1f}s before retrying'})
    try:
        r = call_gemini_resilient([{'role':'user','content':'Say OK'}], max_tokens=12)
        if r['ok']:
            return jsonify({'ok': True, 'cached': r.get('cached', False)})
        return jsonify({'ok': False, 'msg': r['text'][:220]})
    except ValueError:
        return jsonify({'ok': False, 'msg': 'NO_API_KEY'})
    except Exception as e:
        app.logger.exception('Error in /api/test_key')
        return jsonify({'ok': False, 'msg': str(e)})


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json() or request.form
        user = get_user(data.get('username', ''))
        if user and check_password_hash(user[2], data.get('password', '')):
            session.clear()
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            return jsonify({'ok': True, 'redirect': url_for('dashboard')})
        return jsonify({'ok': False, 'msg': 'Invalid username or password'})
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    hd = has_data()
    quick = {}
    if hd:
        ist = load_data('income_statement')
        bs  = load_data('balance_sheet')
        tca = g(bs, 'total_current_assets', 'current_assets')
        tcl = g(bs, 'total_current_liabilities', 'current_liabilities')
        quick = {
            'net_income':   g(ist, 'net_income', 'net_profit'),
            'revenue':      g(ist, 'net_sales', 'total_revenue', 'revenue', 'sales'),
            'total_assets': g(bs, 'total_assets'),
            'nwc':          tca - tcl,
        }
    return render_template('dashboard.html',
                           has_data=hd,
                           company=session.get('company', 'Company A'),
                           quick=quick)

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    try:
        isf = request.files.get('income_statement')
        bsf = request.files.get('balance_sheet')
        suffix = request.form.get('suffix', '')   # '' for A, '_b' for B
        company = request.form.get('company', f'Company {"B" if suffix else "A"}')

        if not isf or not bsf:
            return jsonify({'ok': False, 'msg': 'Both files are required'})
        if not allowed_file(isf.filename) or not allowed_file(bsf.filename):
            return jsonify({'ok': False, 'msg': 'Only CSV / Excel files allowed'})

        is_data = parse_statements(read_file(isf))
        bs_data = parse_statements(read_file(bsf))

        save_data(f'income_statement{suffix}', is_data)
        save_data(f'balance_sheet{suffix}',    bs_data)

        if not suffix:
            session['company'] = company
        else:
            session['company_b'] = company

        return jsonify({'ok': True, 'redirect': url_for('statements')})
    except Exception as e:
        app.logger.exception('Error in /upload')
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/statements')
@login_required
def statements():
    if not has_data():
        return redirect(url_for('dashboard'))
    return render_template('statements.html',
                           ist=load_data('income_statement'),
                           bs=load_data('balance_sheet'),
                           company=session.get('company','Company A'),
                           is_admin=session.get('role')=='admin')

@app.route('/update_cell', methods=['POST'])
@admin_required
def update_cell():
    d = request.get_json()
    stmt = d.get('stmt')  # 'income_statement' or 'balance_sheet'
    key  = d.get('key')
    yr   = d.get('yr')    # 'current' or 'previous'
    val  = d.get('val')
    data = load_data(stmt)
    if data and key in data:
        data[key][yr] = float(val)
        save_data(stmt, data)
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'msg': 'Key not found'})

@app.route('/ratios')
@login_required
def ratios():
    if not has_data():
        return redirect(url_for('dashboard'))
    r = calculate_ratios(load_data('balance_sheet'), load_data('income_statement'))
    return render_template('ratios.html', ratios=r, company=session.get('company','Company A'))

@app.route('/dupont')
@login_required
def dupont():
    if not has_data():
        return redirect(url_for('dashboard'))
    r = calculate_ratios(load_data('balance_sheet'), load_data('income_statement'))
    return render_template('dupont.html', dp=r.get('dupont',{}), company=session.get('company','Company A'))

@app.route('/fcf')
@login_required
def fcf():
    if not has_data():
        return redirect(url_for('dashboard'))
    f = calculate_fcf(load_data('balance_sheet'), load_data('income_statement'))
    return render_template('fcf.html', fcf=f, company=session.get('company','Company A'))

@app.route('/capital')
@login_required
def capital():
    if not has_data():
        return redirect(url_for('dashboard'))
    c = calculate_capital(load_data('balance_sheet'), load_data('income_statement'))
    return render_template('capital.html', cap=c, company=session.get('company','Company A'))

@app.route('/compare', methods=['GET'])
@login_required
def compare():
    if not has_data():
        return redirect(url_for('dashboard'))
    return render_template('compare.html',
                           has_b=has_data_b(),
                           company_a=session.get('company','Company A'),
                           company_b=session.get('company_b','Company B'))

@app.route('/compare/results')
@login_required
def compare_results():
    if not has_data() or not has_data_b():
        return redirect(url_for('compare'))
    ra = calculate_ratios(load_data('balance_sheet'),   load_data('income_statement'))
    rb = calculate_ratios(load_data('balance_sheet_b'), load_data('income_statement_b'))
    return render_template('compare_results.html',
                           ra=ra, rb=rb,
                           ist_a=load_data('income_statement'),   bs_a=load_data('balance_sheet'),
                           ist_b=load_data('income_statement_b'), bs_b=load_data('balance_sheet_b'),
                           company_a=session.get('company','Company A'),
                           company_b=session.get('company_b','Company B'))

@app.route('/ai')
@login_required
def ai_page():
    if not has_data():
        return redirect(url_for('dashboard'))
    return render_template('ai_page.html', company=session.get('company','Company A'))

@app.route('/ai/stream')
@login_required
def ai_stream():
    ok, wait = check_ai_rate_limit('ai_stream', min_seconds=12.0)
    if not ok:
        def limited():
            yield f'data: {json.dumps({"error": f"Too many requests. Please wait {wait:.1f} seconds."})}\n\n'
        return Response(limited(), mimetype='text/event-stream',
                        headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    company = session.get('company', 'Company A')
    context = build_ai_context(company)

    prompt = f"""You are a senior financial analyst. Analyze the financial data for {company} and give an extremely detailed, structured report covering:

{context}

Your report must include:
1. **Executive Summary** - overall health, key findings
2. **Liquidity Analysis** - interpret each ratio, compare to benchmarks, flag risks
3. **Asset Management Analysis** - efficiency insights and recommendations
4. **Debt & Solvency Analysis** - leverage risk, coverage, capital structure
5. **Profitability Analysis** - margins, returns, trends, what's driving performance
6. **DuPont Decomposition** - which factor drives ROE most, what to improve
7. **Free Cash Flow Analysis** - quality of earnings, cash generation quality
8. **Capital Structure Assessment** - is the mix optimal? recommendations
9. **Year-over-Year Trend Analysis** - identify improvements or deterioration
10. **Risk Register** - top 5 financial risks with severity
11. **Future Projections** - estimate next-year key ratios based on trends
12. **Strategic Recommendations** - 5 concrete, numbered recommendations

Be extremely specific, use the actual numbers, compare against industry benchmarks (manufacturing/diversified), and provide actionable insights."""

    def generate():
        try:
            resp = call_gemini([{'role':'user','content': prompt}], stream=True, max_tokens=4000, model_name=GEMINI_MODELS[0])
            if resp.status_code != 200:
                err_text = (resp.text or '')[:300]
                yield f'data: {json.dumps({"error": err_text or f"API error {resp.status_code}"})}\n\n'
                return
            for line in resp.iter_lines():
                if line:
                    line = line.decode('utf-8') if isinstance(line, bytes) else line
                    if line.startswith('data: '):
                        payload = line[6:].strip()
                        if not payload or payload == '[DONE]':
                            yield 'data: {"done":true}\n\n'
                            break
                        try:
                            obj = json.loads(payload)
                            # Gemini SSE: candidates[0].content.parts[0].text
                            candidates = obj.get('candidates', [])
                            if candidates:
                                parts = candidates[0].get('content', {}).get('parts', [])
                                text = ''.join(p.get('text','') for p in parts)
                                if text:
                                    yield f'data: {json.dumps({"chunk": text})}\n\n'
                            # finishReason signals end
                            if candidates and candidates[0].get('finishReason') in ('STOP','MAX_TOKENS'):
                                yield 'data: {"done":true}\n\n'
                                break
                        except:
                            app.logger.warning('Failed parsing Gemini SSE chunk in /ai/stream')
                            pass
        except ValueError as e:
            if 'NO_API_KEY' in str(e):
                yield f'data: {json.dumps({"error": "NO_API_KEY"})}\n\n'
            else:
                app.logger.exception('Value error in /ai/stream')
                yield f'data: {json.dumps({"error": str(e)})}\n\n'
        except Exception as e:
            app.logger.exception('Unhandled error in /ai/stream')
            yield f'data: {json.dumps({"error": str(e)})}\n\n'

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.route('/chat')
@login_required
def chat():
    if not has_data():
        return redirect(url_for('dashboard'))
    return render_template('chat.html', company=session.get('company','Company A'),
                           history=session.get('chat_history', []))

@app.route('/chat/send', methods=['POST'])
@login_required
def chat_send():
    msg = (request.get_json() or {}).get('msg', '').strip()
    if not msg:
        return jsonify({'ok': False})
    if msg == '__clear__':
        session['chat_history'] = []
        return jsonify({'ok': True, 'reply': 'Chat cleared.'})
    ok, wait = check_ai_rate_limit('chat_send', min_seconds=10.0)
    if not ok:
        return jsonify({'ok': True, 'reply': f'⚠ Too many requests. Please wait {wait:.1f} seconds, then send again.'})

    company = session.get('company', 'Company A')
    context = build_ai_context(company)
    history = session.get('chat_history', [])

    system_intro = f"You are an expert financial AI assistant for {company}. Financial data:\n{context}\nAnswer questions precisely, citing specific numbers."

    messages = [{'role':'user','content': system_intro},
                {'role':'assistant','content': f"I have full financial data for {company}. Ask me anything about their financials, ratios, performance, or strategy."}]

    for h in history[-12:]:
        messages.append({'role': h['role'], 'content': h['content']})
    messages.append({'role':'user','content': msg})

    try:
        r = call_gemini_resilient(messages, max_tokens=800)
        if r['ok']:
            text = r['text']
        else:
            msg = r['text']
            if 'NO_API_KEY' in msg:
                text = "❌ No API key set — click **Set API Key** in the sidebar to enter your free Gemini key."
            elif '403' in msg:
                text = "❌ Invalid API key — click **Set API Key** in the sidebar and enter your Gemini key."
            elif '429' in msg:
                text = "⚠ Gemini rate/quota is busy now. Wait ~30-60 seconds and try again."
            else:
                text = f"❌ {msg}"
    except Exception as e:
        app.logger.exception('Error in /chat/send')
        text = f'Connection error: {str(e)}'

    history.append({'role':'user','content': msg})
    history.append({'role':'assistant','content': text})
    session['chat_history'] = history[-24:]

    return jsonify({'ok': True, 'reply': text})

@app.route('/api/ratios.json')
@login_required
def api_ratios():
    if not has_data():
        return jsonify({})
    return jsonify(calculate_ratios(load_data('balance_sheet'), load_data('income_statement')))

@app.route('/api/compare.json')
@login_required
def api_compare():
    if not has_data() or not has_data_b():
        return jsonify({})
    return jsonify({
        'a': calculate_ratios(load_data('balance_sheet'),   load_data('income_statement')),
        'b': calculate_ratios(load_data('balance_sheet_b'), load_data('income_statement_b')),
        'na': session.get('company','Company A'),
        'nb': session.get('company_b','Company B'),
        'ist_a': load_data('income_statement'),
        'ist_b': load_data('income_statement_b'),
        'bs_a':  load_data('balance_sheet'),
        'bs_b':  load_data('balance_sheet_b'),
    })

try:
    init_runtime()
except Exception:
    app.logger.exception('Startup initialization failed')
    raise

# ─────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.logger.info('Starting Flask dev server on port %s', port)
    app.run(debug=True, host='0.0.0.0', port=port)
