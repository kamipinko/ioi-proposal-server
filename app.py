import json
import os
import re
import base64
import urllib.parse
import datetime
import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from flask import Flask, Response, abort, request, jsonify

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENCIES_PATH = os.path.join(BASE_DIR, 'agencies.json')
BOOKINGS_PATH = os.path.join(BASE_DIR, 'bookings.json')
PORT = int(os.environ.get('PORT', 5050))

COMPANY = 'Proles Home Healthcare Consultants'
COMPANY_URL = 'www.prolesconsulting.com'
GMAIL_USER = os.environ.get('GMAIL_USER', 'amthuku@gmail.com')
RAILWAY_URL = 'https://ioi-proposal-server-production.up.railway.app'
EXAMPLE_DISPLAY = 'https://delightful-glacier-0971dfb0f.1.azurestaticapps.net'
EXAMPLE_HREF = 'https://delightful-glacier-0971dfb0f.1.azurestaticapps.net'


def _load_ioi_template(filename):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'ioi_templates', filename)
    path = os.path.normpath(path)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f'<html><body><h1>{filename} not found</h1></body></html>'

_IOI_INDEX    = _load_ioi_template('index.html')
_IOI_SERVICES = _load_ioi_template('services.html')
_IOI_ABOUT    = _load_ioi_template('about.html')
_IOI_CONTACT  = _load_ioi_template('contact.html')


GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/calendar',
]

_agencies_cache = None

# ── Data ───────────────────────────────────────────────────────────────────────

def load_agencies():
    global _agencies_cache
    if _agencies_cache is not None:
        return _agencies_cache
    with open(AGENCIES_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    result = {}
    for a in data:
        num = a.get('num')
        if num is not None:
            result[int(num)] = a
    _agencies_cache = result
    return result


def type_phrase(agency_type):
    if not agency_type:
        return 'As a licensed Maryland care provider,'
    t = agency_type.lower()
    if 'home health' in t:
        return 'As a licensed Home Health Agency,'
    if 'residential' in t or 'rsa' in t:
        return 'As a Residential Service Agency,'
    if 'day care' in t or 'adult medical' in t or 'adult day' in t:
        return 'As a licensed Adult Day Care provider,'
    return 'As a licensed Maryland care provider,'


def slugify(name):
    s = name.lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_-]+', '_', s)
    return s.strip('_')


# ── Google API auth ────────────────────────────────────────────────────────────

def _build_creds():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        token_path = os.path.join(BASE_DIR, 'token.json')
        client_id = os.environ.get('GMAIL_CLIENT_ID')
        client_secret = os.environ.get('GMAIL_CLIENT_SECRET')
        refresh_token = os.environ.get('GMAIL_REFRESH_TOKEN')

        if client_id and client_secret and refresh_token:
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_id,
                client_secret=client_secret,
                scopes=GMAIL_SCOPES,
            )
        elif os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)
        else:
            return None

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds
    except Exception as e:
        print(f'[creds] {e}')
        return None


def get_gmail_service():
    try:
        from googleapiclient.discovery import build
        creds = _build_creds()
        if not creds:
            return None
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        print(f'[gmail] {e}')
        return None


def get_calendar_service():
    try:
        from googleapiclient.discovery import build
        creds = _build_creds()
        if not creds:
            return None
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f'[calendar] {e}')
        return None


# ── CSS ────────────────────────────────────────────────────────────────────────
# Color palette extracted from stopandconnect.com:
#   bg #111111, bg2 #1a1a1a, bg3 #2a2a2a
#   gold #ECAA27, gold-light #ffc84d
#   red #8a0a0a, red-light #e05252
#   text #f5f0e8, text2 #888888

_VARS = """
  :root {
    --bg:   #111111;
    --bg2:  #1a1a1a;
    --bg3:  #2a2a2a;
    --gold: #ECAA27;
    --gold-light: #ffc84d;
    --red:  #8a0a0a;
    --red-light: #e05252;
    --text: #f5f0e8;
    --text2:#888888;
    --text3:#444444;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
"""

PROPOSAL_CSS = _VARS + """
  @page { size: Letter; margin: 0.5in 0.6in; }
  @media print {
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .action-bar { display: none !important; }
  }
  body {
    font-family: Arial, Helvetica, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh; display: flex; flex-direction: column; align-items: center;
  }
  .action-bar {
    background: var(--bg2); border-bottom: 3px solid var(--gold);
    padding: 12px 24px; display: flex; justify-content: space-between;
    align-items: center; position: sticky; top: 0; z-index: 100; width: 100%;
  }
  .action-left { display: flex; flex-direction: column; gap: 2px; }
  .action-name { color: var(--text); font-weight: 900; font-size: 16px; letter-spacing: 0.3px; }
  .action-type { color: var(--text2); font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; }
  .action-right { display: flex; gap: 10px; }
  .action-btn {
    background: var(--gold); color: #111; padding: 8px 18px; border-radius: 0;
    font-size: 11px; font-weight: 900; text-decoration: none; border: none; cursor: pointer;
    text-transform: uppercase; letter-spacing: 1.5px; font-family: Arial, sans-serif;
    clip-path: polygon(0 0,calc(100% - 7px) 0,100% 7px,100% 100%,7px 100%,0 calc(100% - 7px));
  }
  .action-btn:hover { background: var(--gold-light); }
  .action-btn-red { background: var(--red); color: var(--text); }
  .action-btn-red:hover { background: var(--red-light); color: var(--text); }
  .page {
    width: 100%; max-width: 7.3in; background: var(--bg);
    display: flex; flex-direction: column; padding: 0.5in 0.6in;
  }
  .header {
    border-bottom: 3px solid var(--gold); padding-bottom: 14px; margin-bottom: 20px;
    display: flex; justify-content: space-between; align-items: flex-end; position: relative;
  }
  .header::before {
    content: ''; position: absolute; bottom: -3px; left: 0;
    width: 50px; height: 3px; background: var(--red);
  }
  .header-title {
    font-size: 30px; font-weight: 900; color: var(--text);
    letter-spacing: -0.5px; line-height: 1.05; text-transform: uppercase;
  }
  .header-title em { font-style: normal; color: var(--gold); }
  .header-sub { font-size: 12px; color: var(--text2); margin-top: 6px; letter-spacing: 2px; text-transform: uppercase; }
  .header-right { text-align: right; }
  .brand-name { font-size: 12px; font-weight: 900; color: var(--gold); letter-spacing: 2px; text-transform: uppercase; }
  .brand-tagline { font-size: 9px; color: var(--text2); letter-spacing: 1px; margin-top: 4px; text-transform: uppercase; }
  .section-label {
    display: inline-block; font-size: 9px; font-weight: 900; letter-spacing: 2px;
    text-transform: uppercase; padding: 3px 12px; margin-bottom: 10px;
    clip-path: polygon(0 0,calc(100% - 6px) 0,100% 6px,100% 100%,6px 100%,0 calc(100% - 6px));
  }
  .label-gold { background: var(--gold); color: #111; }
  .label-red  { background: var(--red);  color: var(--text); }
  .section { margin-bottom: 18px; }
  .problem-text { font-size: 15px; line-height: 1.6; color: var(--text); }
  .problem-text strong { color: var(--gold); font-weight: 900; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 18px; }
  .deliver-list { list-style: none; padding: 0; margin: 0; }
  .deliver-list li {
    font-size: 13px; line-height: 1.5; color: var(--text);
    padding: 7px 0 7px 20px; border-bottom: 1px solid var(--bg3); position: relative;
  }
  .deliver-list li:last-child { border-bottom: none; }
  .deliver-list li::before { content: '►'; color: var(--gold); position: absolute; left: 0; font-size: 9px; top: 10px; }
  .deliver-list li strong { color: var(--gold); }
  .example-box {
    background: var(--bg2); border: 2px solid var(--gold); padding: 14px 16px;
    clip-path: polygon(0 0,calc(100% - 10px) 0,100% 10px,100% 100%,10px 100%,0 calc(100% - 10px));
  }
  .example-url { font-size: 14px; font-weight: 900; color: var(--gold); text-decoration: none; display: block; margin-bottom: 6px; }
  .example-desc { font-size: 12px; color: var(--text2); line-height: 1.5; }
  .example-badge {
    display: inline-block; background: var(--red); color: var(--text);
    font-size: 9px; font-weight: 900; padding: 3px 10px; margin-top: 8px;
    letter-spacing: 1.5px; text-transform: uppercase;
  }
  .why-text { font-size: 13px; line-height: 1.7; color: var(--text); }
  .why-text strong { color: var(--gold); font-weight: 900; }
  .cta-box {
    background: var(--bg2); border: 2px solid var(--gold); padding: 18px 24px;
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 18px; gap: 20px;
    clip-path: polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px));
  }
  .cta-headline { font-size: 20px; font-weight: 900; color: var(--text); line-height: 1.15; text-transform: uppercase; }
  .cta-headline em { font-style: normal; color: var(--gold); }
  .cta-contact { text-align: right; font-size: 13px; color: var(--text2); line-height: 2; white-space: nowrap; }
  .cta-contact a { color: var(--gold); text-decoration: none; font-weight: 900; }
  .footer {
    border-top: 1px solid var(--bg3); padding-top: 10px;
    display: flex; justify-content: space-between; align-items: center;
  }
  .footer-left { font-size: 11px; color: var(--text3); }
  .footer-right { font-size: 11px; color: var(--text3); text-align: right; }
  .footer-right a { color: var(--gold); text-decoration: none; font-weight: bold; }
  .toast {
    display: none; position: fixed; bottom: 30px; right: 30px;
    background: var(--gold); color: #111; font-weight: 900;
    padding: 14px 24px; font-size: 13px; z-index: 9999;
    clip-path: polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));
  }
  .toast.show { display: block; animation: fadeout 0.3s 3.7s forwards; }
  @keyframes fadeout { to { opacity: 0; } }
"""

INDEX_CSS = _VARS + """
  @keyframes slideInLeft  { from { opacity:0; transform: translateX(-40px); } to { opacity:1; transform: translateX(0); } }
  @keyframes slideInRight { from { opacity:0; transform: translateX(40px);  } to { opacity:1; transform: translateX(0); } }
  @keyframes fadeUp       { from { opacity:0; transform: translateY(20px);  } to { opacity:1; transform: translateY(0); } }
  @keyframes bannerWipe   { from { clip-path: polygon(0 0,0 0,0 100%,0 100%); } to { clip-path: polygon(0 0,100% 0,100% 100%,0 100%); } }
  @keyframes scanline     { 0%,100% { opacity:0.03; } 50% { opacity:0.07; } }
  @keyframes rowIn        { from { opacity:0; transform: translateX(-12px); } to { opacity:1; transform: translateX(0); } }
  @keyframes pulse-gold   { 0%,100% { box-shadow:0 0 0 0 rgba(236,170,39,0); } 50% { box-shadow:0 0 0 6px rgba(236,170,39,0.15); } }

  body {
    font-family: Arial, sans-serif; background: var(--bg); color: var(--text);
    padding: 0; min-height: 100vh; overflow-x: hidden;
  }

  /* ── Top Banner ── */
  .top-banner {
    background: var(--bg2); border-bottom: 3px solid var(--gold);
    padding: 0 32px; display: flex; justify-content: space-between;
    align-items: stretch; position: relative; overflow: hidden;
    animation: slideInLeft 0.5s cubic-bezier(.16,1,.3,1) both;
  }
  .top-banner::before {
    content: ''; position: absolute; inset: 0;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,0.015) 2px, rgba(255,255,255,0.015) 4px);
    animation: scanline 3s ease-in-out infinite; pointer-events: none;
  }
  .banner-left {
    display: flex; flex-direction: column; justify-content: center;
    padding: 20px 0; gap: 4px;
  }
  .banner-eyebrow {
    font-size: 9px; font-weight: 900; color: var(--gold);
    letter-spacing: 3px; text-transform: uppercase;
  }
  .banner-title {
    font-size: 32px; font-weight: 900; color: var(--text);
    text-transform: uppercase; letter-spacing: -1px; line-height: 1;
  }
  .banner-title span { color: var(--gold); }
  .banner-sub {
    font-size: 10px; color: var(--text2); letter-spacing: 2px;
    text-transform: uppercase; margin-top: 2px;
  }
  .banner-right {
    display: flex; align-items: center; gap: 0;
    border-left: 1px solid var(--bg3); padding-left: 32px; margin-left: 32px;
  }
  .banner-logo { height: 72px; width: auto; }
  .banner-stat {
    display: flex; flex-direction: column; align-items: center;
    padding: 0 20px; border-right: 1px solid var(--bg3);
  }
  .banner-stat:last-of-type { border-right: none; }
  .stat-num { font-size: 28px; font-weight: 900; color: var(--gold); line-height: 1; }
  .stat-label { font-size: 8px; color: var(--text2); letter-spacing: 1.5px; text-transform: uppercase; margin-top: 3px; }

  /* ── Diagonal accent bar ── */
  .accent-bar {
    height: 4px;
    background: linear-gradient(90deg, var(--red) 0%, var(--red) 30%, var(--gold) 30%, var(--gold) 60%, var(--bg3) 60%);
    animation: bannerWipe 0.6s 0.3s cubic-bezier(.16,1,.3,1) both;
  }

  /* ── Content ── */
  .content { padding: 28px 32px; animation: fadeUp 0.5s 0.2s cubic-bezier(.16,1,.3,1) both; }

  /* ── Table ── */
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th {
    background: var(--bg2); color: var(--gold); padding: 10px 12px; text-align: left;
    font-size: 9px; letter-spacing: 2px; text-transform: uppercase; border-bottom: 2px solid var(--gold);
    position: sticky; top: 0; z-index: 10;
  }
  tbody tr {
    animation: rowIn 0.3s both;
    transition: background 0.15s ease;
  }
  tbody tr:nth-child(n) { animation-delay: calc(n * 0.02s); }
  td {
    padding: 9px 12px; border-bottom: 1px solid var(--bg3);
    color: var(--text); vertical-align: middle;
    transition: background 0.15s ease, padding-left 0.15s ease;
  }
  tbody tr:hover td { background: var(--bg2); padding-left: 16px; }
  tbody tr:hover td:first-child { border-left: 3px solid var(--gold); padding-left: 13px; }

  /* ── Buttons ── */
  .btn {
    display: inline-block; padding: 5px 14px; font-size: 10px; font-weight: 900;
    text-decoration: none; margin-right: 4px; text-transform: uppercase; letter-spacing: 1px;
    clip-path: polygon(0 0,calc(100% - 5px) 0,100% 5px,100% 100%,5px 100%,0 calc(100% - 5px));
    cursor: pointer; border: none; font-family: Arial, sans-serif;
    transition: transform 0.1s ease, filter 0.1s ease;
  }
  .btn:hover { transform: translateY(-1px); filter: brightness(1.15); }
  .btn:active { transform: translateY(1px); filter: brightness(0.9); }
  .btn-gold { background: var(--gold); color: #111; }
  .btn-red  { background: var(--red);  color: var(--text); }

  /* ── P5 Modal ── */
  .modal-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,0.85); z-index: 1000;
    align-items: center; justify-content: center;
    backdrop-filter: blur(3px);
  }
  .modal-overlay.open { display: flex; animation: fadeUp 0.2s cubic-bezier(.16,1,.3,1) both; }
  .modal-box {
    background: var(--bg2); border: 2px solid var(--gold); width: 480px; max-width: 95vw;
    clip-path: polygon(0 0,calc(100% - 16px) 0,100% 16px,100% 100%,16px 100%,0 calc(100% - 16px));
    animation: slideInRight 0.25s cubic-bezier(.16,1,.3,1) both;
    overflow: hidden;
  }
  .modal-header {
    background: var(--bg); border-bottom: 2px solid var(--gold); padding: 16px 22px;
    display: flex; justify-content: space-between; align-items: flex-start;
  }
  .modal-agency { font-size: 16px; font-weight: 900; color: var(--text); text-transform: uppercase; }
  .modal-type   { font-size: 9px; color: var(--text2); letter-spacing: 2px; text-transform: uppercase; margin-top: 3px; }
  .modal-close  {
    background: none; border: none; color: var(--text2); font-size: 20px;
    cursor: pointer; line-height: 1; padding: 0; transition: color 0.15s;
  }
  .modal-close:hover { color: var(--gold); }
  .modal-body { padding: 20px 22px; display: flex; flex-direction: column; gap: 10px; }
  .modal-stat  { font-size: 12px; color: var(--text2); }
  .modal-stat strong { color: var(--text); }
  .modal-sdat  {
    display: inline-block; font-size: 9px; font-weight: 900; padding: 3px 10px;
    text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px;
  }
  .modal-actions { display: flex; gap: 8px; padding: 16px 22px; border-top: 1px solid var(--bg3); flex-wrap: wrap; }
  .modal-btn {
    flex: 1; padding: 12px; font-size: 10px; font-weight: 900; text-align: center;
    text-decoration: none; text-transform: uppercase; letter-spacing: 1.5px; cursor: pointer;
    border: none; font-family: Arial, sans-serif;
    clip-path: polygon(0 0,calc(100% - 6px) 0,100% 6px,100% 100%,6px 100%,0 calc(100% - 6px));
    transition: filter 0.15s ease, transform 0.1s ease;
  }
  .modal-btn:hover { filter: brightness(1.2); transform: translateY(-1px); }
  .modal-btn-gold { background: var(--gold); color: #111; }
  .modal-btn-red  { background: var(--red);  color: var(--text); }
  .modal-btn-dim  { background: var(--bg3);  color: var(--text2); }
  .btn-demo { background: transparent; border: 2px solid #ECAA27; color: #ECAA27; }
  .btn-demo:hover { background: #ECAA27; color: #111; }
"""

EMAIL_CSS = _VARS + """
  body { font-family: Arial, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; padding: 30px 20px; }
  .container { max-width: 760px; margin: 0 auto; }
  .page-title { font-size: 24px; color: var(--text); font-weight: 900; text-transform: uppercase; margin-bottom: 4px; }
  .subtitle { font-size: 11px; color: var(--text2); margin-bottom: 24px; letter-spacing: 1.5px; text-transform: uppercase; }
  .subtitle a { color: var(--gold); text-decoration: none; }
  .subject-box { background: var(--bg2); border-left: 4px solid var(--gold); padding: 16px 20px; margin-bottom: 24px; }
  .subject-label { font-size: 9px; font-weight: 900; letter-spacing: 2px; text-transform: uppercase; color: var(--text2); margin-bottom: 8px; }
  .subject-line { font-size: 15px; color: var(--text); font-weight: 900; }
  .email-card { background: #fff; color: #1a1a1a; overflow: hidden; margin-bottom: 24px; border: 2px solid var(--gold); }
  .email-card-header {
    background: #111111; padding: 16px 24px; display: flex;
    justify-content: space-between; align-items: center; border-bottom: 3px solid var(--gold);
  }
  .email-brand { color: var(--text); font-weight: 900; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; }
  .email-brand span { color: var(--gold); }
  .email-body { padding: 32px 36px; font-size: 14px; line-height: 1.8; color: #1a1a1a; }
  .email-body p { margin-bottom: 16px; white-space: pre-wrap; }
  .mailto-bar {
    background: var(--bg2); border: 2px solid var(--gold); padding: 16px 20px;
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
  }
  .mailto-info { font-size: 13px; color: var(--text2); line-height: 1.8; }
  .mailto-info strong { color: var(--text); }
  .btn-row { display: flex; gap: 10px; flex-shrink: 0; flex-wrap: wrap; }
  .btn {
    display: inline-block; padding: 10px 20px; font-size: 11px; font-weight: 900;
    text-decoration: none; cursor: pointer; border: none; font-family: Arial, sans-serif;
    text-transform: uppercase; letter-spacing: 1px;
    clip-path: polygon(0 0,calc(100% - 6px) 0,100% 6px,100% 100%,6px 100%,0 calc(100% - 6px));
  }
  .btn-gold { background: var(--gold); color: #111; }
  .btn-red  { background: var(--red);  color: var(--text); }
  .no-email-note { font-size: 14px; color: var(--gold); font-weight: 900; }
  .toast {
    display: none; position: fixed; bottom: 30px; right: 30px;
    background: var(--gold); color: #111; font-weight: 900;
    padding: 14px 24px; font-size: 13px; z-index: 9999;
    clip-path: polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));
  }
  .toast.show { display: block; animation: fadeout 0.3s 3.7s forwards; }
  @keyframes fadeout { to { opacity: 0; } }
"""

BOOK_CSS = _VARS + """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 40px 16px;
  }

  .card {
    width: 100%; max-width: 480px;
    background: var(--bg2);
    clip-path: polygon(0 0, calc(100% - 20px) 0, 100% 20px, 100% 100%, 20px 100%, 0 calc(100% - 20px));
    padding: 36px 32px 40px;
  }

  .card-eyebrow {
    font-size: 9px; font-weight: 900; letter-spacing: 3px;
    text-transform: uppercase; color: var(--gold); margin-bottom: 10px;
  }
  .card-title {
    font-size: 22px; font-weight: 900; text-transform: uppercase;
    color: var(--text); line-height: 1.1; margin-bottom: 6px;
  }
  .card-title span { color: var(--gold); }
  .card-sub { font-size: 11px; color: var(--text2); margin-bottom: 24px; letter-spacing: 0.5px; }
  .divider {
    height: 2px;
    background: linear-gradient(90deg, var(--gold) 0%, var(--red) 50%, transparent 100%);
    margin-bottom: 24px;
  }

  .field-label {
    font-size: 9px; font-weight: 900; letter-spacing: 2px;
    text-transform: uppercase; color: var(--text2); display: block; margin-bottom: 6px;
  }
  .field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }
  .field-row.single { grid-template-columns: 1fr; }
  .field-row.three { grid-template-columns: 1fr 1fr 1fr; }

  input[type=text], input[type=email], input[type=tel], select {
    width: 100%; background: var(--bg); border: 1px solid var(--bg3);
    color: var(--text); padding: 10px 12px; font-size: 13px; outline: none;
    clip-path: polygon(0 0, calc(100% - 7px) 0, 100% 7px, 100% 100%, 7px 100%, 0 calc(100% - 7px));
    transition: border-color 0.15s; appearance: none; -webkit-appearance: none;
    font-family: inherit;
  }
  input:focus, select:focus { border-color: var(--gold); }
  select {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 5 5-5' stroke='%23ECAA27' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 12px center; cursor: pointer;
  }
  select option { background: var(--bg2); color: var(--text); }
  select option:disabled { color: #444; }
  select option.unavailable { color: #444; }

  .meet-row { display: flex; gap: 10px; margin-bottom: 20px; }
  .meet-pill {
    flex: 1; padding: 10px 8px; border: 1px solid var(--bg3); background: var(--bg);
    cursor: pointer; text-align: center; font-size: 11px; font-weight: 900;
    letter-spacing: 1px; text-transform: uppercase; color: var(--text2);
    clip-path: polygon(0 0, calc(100% - 7px) 0, 100% 7px, 100% 100%, 7px 100%, 0 calc(100% - 7px));
    transition: all 0.15s; user-select: none;
  }
  .meet-pill:hover { border-color: var(--gold); color: var(--gold); }
  .meet-pill.active { border-color: var(--gold); background: var(--gold); color: #111; }

  .slot-row { margin-bottom: 20px; animation: fadeUp 0.2s ease; }
  @keyframes fadeUp { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }

  .submit-btn {
    width: 100%; padding: 14px; background: var(--gold); color: #111;
    font-size: 12px; font-weight: 900; letter-spacing: 2.5px; text-transform: uppercase;
    border: none; cursor: pointer; margin-top: 6px;
    clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 12px 100%, 0 calc(100% - 12px));
    transition: background 0.15s;
  }
  .submit-btn:hover { background: #ffc84d; }
  .submit-btn:disabled { background: var(--bg3); color: var(--text3); cursor: not-allowed; }

  .success-card {
    display: none; text-align: center; padding: 20px 0;
  }
  .success-icon { font-size: 40px; color: var(--gold); margin-bottom: 14px; }
  .success-card h2 { font-size: 18px; font-weight: 900; text-transform: uppercase; margin-bottom: 10px; }
  .success-card p { color: var(--text2); font-size: 12px; line-height: 1.7; }
"""

# ── SDAT badge data ────────────────────────────────────────────────────────────

SDAT_BADGE = {
    'ACTIVE':       ('#22c55e', '#fff'),
    'REVIVED':      ('#14b8a6', '#fff'),
    'INCORPORATED': ('#3b82f6', '#fff'),
    'FORFEITED':    ('#ef4444', '#fff'),
    'NOT FOUND':    ('#6b7280', '#fff'),
}
SDAT_TARGETABLE = {'ACTIVE', 'REVIVED', 'INCORPORATED'}

# ── Email body builders ────────────────────────────────────────────────────────

def build_email_html(agency, n):
    name = agency.get('name') or 'Agency'
    atype = agency.get('type') or 'home health agency'
    city = agency.get('city') or 'Maryland'
    phrase = type_phrase(atype)
    book_url = f"{RAILWAY_URL}/book/{n}"

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f0e8;margin:0;padding:20px;">
<div style="max-width:600px;margin:0 auto;background:#fff;border:2px solid #ECAA27;">

  <div style="background:#111111;padding:20px 28px;border-bottom:3px solid #ECAA27;display:flex;justify-content:space-between;align-items:center;">
    <div>
      <div style="font-size:10px;font-weight:900;color:#ECAA27;letter-spacing:2px;text-transform:uppercase;">
        PROLES HOME HEALTHCARE CONSULTANTS
      </div>
      <div style="font-size:22px;font-weight:900;color:#f5f0e8;margin-top:6px;">{name}</div>
    </div>
    <img src="https://ioi-proposal-server-production.up.railway.app/static/logo.png" alt="Proles" style="height:80px;width:auto;">
  </div>

  <div style="padding:28px 32px;color:#1a1a1a;font-size:14px;line-height:1.8;">
    <p style="margin-bottom:16px;">Hi there,</p>

    <p style="margin-bottom:16px;">{phrase} in <strong>{city}</strong>, we know you&rsquo;re doing important work for families in your community. But without a digital presence, families searching online for services in {city} simply can&rsquo;t find you &mdash; even though you&rsquo;re fully licensed and operating.</p>

    <p style="margin-bottom:10px;"><strong>Here&rsquo;s what we build for agencies like {name}:</strong></p>
    <ul style="padding-left:20px;margin-bottom:20px;">
      <li style="margin-bottom:8px;"><strong>A professional, branded website</strong> &mdash; mobile-friendly, fast, and built for healthcare providers</li>
      <li style="margin-bottom:8px;"><strong>Staff &amp; employee portal</strong> &mdash; internal tools your team can actually use</li>
      <li style="margin-bottom:8px;"><strong>Appointment &amp; contact forms</strong> &mdash; so families and referral partners can reach you directly</li>
    </ul>

    <p style="margin-bottom:16px;">We built a personalized demo site just for <strong>{name}</strong>. See it live:
    <a href="{RAILWAY_URL}/demo/{n}" style="color:#8a0a0a;font-weight:bold;">{RAILWAY_URL}/demo/{n}</a> &mdash;
    a branded homepage, service pages, and contact forms &mdash; exactly what your agency&rsquo;s site will look like.</p>

    <p style="margin-bottom:16px;">Beyond the website itself, every site we build includes <strong>local SEO setup</strong> &mdash; Google Business Profile configuration, location-based keyword targeting for {city}, and on-page metadata &mdash; so families in your area can find you when they search. Most agencies without a web presence are losing clients to competitors simply because they can&rsquo;t be found online.</p>

    <div style="background:#f5f0e8;border-left:4px solid #ECAA27;padding:14px 18px;margin:20px 0;font-size:13px;">
      <strong>Attached:</strong> See the one-page proposal PDF for full details and pricing tailored to {name}.
    </div>

    <p style="font-size:12px;color:#888888;margin-bottom:20px;">
      <strong>Proles Home Healthcare Consultants</strong> |
      <a href="https://{COMPANY_URL}" style="color:#8a0a0a;">{COMPANY_URL}</a>
    </p>

    <div style="text-align:center;margin:28px 0;">
      <a href="{book_url}" style="display:inline-block;background:#111111;color:#ECAA27;padding:16px 36px;
         font-size:12px;font-weight:900;text-decoration:none;text-transform:uppercase;
         letter-spacing:2px;border:2px solid #ECAA27;">
        &#128197; Schedule a Free 15-Minute Call
      </a>
    </div>
  </div>

  <div style="background:#111111;border-top:3px solid #ECAA27;padding:16px 28px;">
    <div style="font-size:10px;font-weight:900;color:#ECAA27;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px;">WHAT YOU GET &mdash; AT A GLANCE</div>
    <table style="width:100%;border-collapse:separate;border-spacing:4px;margin-bottom:12px;">
      <tr>
        <td style="text-align:center;padding:6px 8px;background:#1a1a1a;">
          <div style="font-size:20px;font-weight:900;color:#ECAA27;line-height:1;">$1,800</div>
          <div style="font-size:9px;color:rgba(255,255,255,0.7);text-transform:uppercase;letter-spacing:1px;margin-top:2px;">All-In Investment</div>
        </td>
        <td style="text-align:center;padding:6px 8px;background:#1a1a1a;">
          <div style="font-size:20px;font-weight:900;color:#ECAA27;line-height:1;">3 Wks</div>
          <div style="font-size:9px;color:rgba(255,255,255,0.7);text-transform:uppercase;letter-spacing:1px;margin-top:2px;">Live Website</div>
        </td>
        <td style="text-align:center;padding:6px 8px;background:#1a1a1a;">
          <div style="font-size:20px;font-weight:900;color:#ECAA27;line-height:1;">$13,200</div>
          <div style="font-size:9px;color:rgba(255,255,255,0.7);text-transform:uppercase;letter-spacing:1px;margin-top:2px;">Est. Year 1 Return</div>
        </td>
        <td style="text-align:center;padding:6px 8px;background:#1a1a1a;">
          <div style="font-size:20px;font-weight:900;color:#ECAA27;line-height:1;">7.3&times;</div>
          <div style="font-size:9px;color:rgba(255,255,255,0.7);text-transform:uppercase;letter-spacing:1px;margin-top:2px;">ROI</div>
        </td>
      </tr>
    </table>
    <div style="font-size:12px;color:#f5f0e8;line-height:2.0;margin-bottom:10px;">
      &#10003; Professional website branded for <strong style="color:#ECAA27;">{name}</strong><br>
      &#10003; Local SEO &mdash; families in <strong style="color:#ECAA27;">{city}</strong> find you on Google<br>
      &#10003; Staff portal + contact forms &mdash; operational from day one
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,0.55);">
      Full one-page overview: <a href="{RAILWAY_URL}/overview/{n}" style="color:#ECAA27;">{RAILWAY_URL}/overview/{n}</a>
    </div>
  </div>

  <div style="background:#111111;padding:16px 28px;border-top:1px solid #2a2a2a;">
    <div style="font-size:12px;color:#888888;line-height:1.7;">
      <strong style="color:#f5f0e8;">Alex Thuku</strong><br>
      Proles Home Healthcare Consultants<br>
      <a href="https://{COMPANY_URL}" style="color:#ECAA27;">{COMPANY_URL}</a> |
      amthuku@gmail.com | (434) 429-9296 | Baltimore, MD
    </div>
  </div>
</div>
</body></html>"""


def build_email_text(agency, n):
    name = agency.get('name') or 'Agency'
    atype = agency.get('type') or 'home health agency'
    city = agency.get('city') or 'Maryland'
    phrase = type_phrase(atype)
    book_url = f"{RAILWAY_URL}/book/{n}"
    return (
        f"Hi there,\n\n"
        f"{phrase} in {city}, families searching online simply can't find you — "
        f"even though you're fully licensed and operating.\n\n"
        f"Here's what we build for agencies like {name}:\n"
        f"  • A professional, branded website — mobile-friendly and fast\n"
        f"  • Staff & employee portal — internal tools your team can use\n"
        f"  • Appointment & contact forms — so families can reach you directly\n\n"
        f"See your personalized demo site: {RAILWAY_URL}/demo/{n}\n\n"
        f"Beyond the website itself, every site we build includes local SEO setup — Google Business Profile configuration, location-based keyword targeting for your area, and on-page metadata — so families can find you when they search online.\n\n"
        f"See the attached one-page proposal PDF for full details and pricing.\n\n"
        f"Schedule a free 15-minute call: {book_url}\n\n"
        f"Proles Home Healthcare Consultants | {COMPANY_URL}\n\n"
        f"Best regards,\n"
        f"Alex Thuku\n"
        f"Proles Home Healthcare Consultants | {COMPANY_URL}\n"
        f"amthuku@gmail.com | (434) 429-9296 | Baltimore, MD"
    )


# ── Overview One-Pager ────────────────────────────────────────────────────────

OVERVIEW_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #d0d0d0; font-family: Arial, sans-serif; font-size: 0.72rem; color: #111111; }
  .page { width: 8.5in; background: #f5f0e8; margin: 20px auto; box-shadow: 0 4px 32px rgba(0,0,0,0.25); position: relative; }
  .top-stripe { height: 6px; background: linear-gradient(to right, #8a0a0a 0%, #111111 50%, #ECAA27 100%); }
  .page-inner { padding: 8px 22px; }
  .no-print { position: absolute; top: 14px; right: 22px; }
  .print-btn { background: #8a0a0a; color: #fff; font-family: Arial, sans-serif; font-size: 0.65rem; font-weight: 700; letter-spacing: 0.08em; border: none; cursor: pointer; padding: 5px 14px; clip-path: polygon(8px 0%, 100% 0%, calc(100% - 8px) 100%, 0% 100%); text-transform: uppercase; }
  .print-btn:hover { background: #6a0808; }
  .ovr-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 3px; padding-right: 90px; }
  .ovr-header-left h1 { font-family: Arial, sans-serif; font-size: 1.0rem; font-weight: 900; color: #111111; line-height: 1.1; letter-spacing: 0.02em; }
  .ovr-header-left h1 span { color: #ECAA27; }
  .ovr-sub { font-size: 0.68rem; color: #444444; margin-top: 1px; }
  .ovr-header-right { display: flex; flex-direction: column; align-items: flex-end; }
  .ovr-header-right img { height: 58px; width: auto; }
  .ovr-meta { font-size: 0.6rem; color: #8a0a0a; letter-spacing: 0.09em; text-transform: uppercase; text-align: right; }
  .divider { height: 2px; background: linear-gradient(to right, #8a0a0a, #111111, #ECAA27); margin: 3px 0; }
  .section-label { font-size: 0.6rem; font-weight: 900; letter-spacing: 0.13em; text-transform: uppercase; color: #8a0a0a; margin-bottom: 2px; }
  .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 4px; }
  .stat-box { background: #111111; color: #fff; clip-path: polygon(8px 0%, 100% 0%, calc(100% - 8px) 100%, 0% 100%); padding: 4px 12px; text-align: center; }
  .stat-val { font-size: 1.05rem; font-weight: 900; color: #ECAA27; line-height: 1; }
  .stat-lbl { font-size: 0.6rem; color: rgba(255,255,255,0.75); margin-top: 2px; text-transform: uppercase; letter-spacing: 0.07em; }
  .snapshot-bar { background: #1a1a1a; color: #fff; display: flex; gap: 0; padding: 3px 10px; margin-bottom: 4px; align-items: flex-start; clip-path: polygon(0 0, 100% 0, calc(100% - 6px) 100%, 6px 100%); }
  .snap-item { flex: 1; padding: 0 10px; border-right: 1px solid rgba(255,255,255,0.18); }
  .snap-item:last-child { border-right: none; }
  .snap-lbl { font-size: 0.55rem; color: #ECAA27; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 700; }
  .snap-val { font-size: 0.68rem; color: #fff; line-height: 1.3; margin-top: 1px; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
  .three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
  .four-col { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 6px; }
  .col-panel { background: #fff; border: 1px solid rgba(17,17,17,0.12); overflow: hidden; }
  .data-table { width: 100%; border-collapse: collapse; font-size: 0.7rem; }
  .data-table th { font-size: 0.6rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; background: #111111; color: #ECAA27; padding: 3px 8px; text-align: left; }
  .data-table td { padding: 2px 6px; border-bottom: 1px solid rgba(17,17,17,0.1); vertical-align: middle; }
  .data-table tr:last-child td { border-bottom: none; }
  .data-table .total-row td { background: #111111; color: #ECAA27; font-weight: 700; font-size: 0.68rem; }
  .badge-none { background: #8a0a0a; color: #fff; font-size: 0.55rem; padding: 1px 5px; font-weight: 700; letter-spacing: 0.06em; }
  .phase-card { background: #111111; color: #fff; padding: 5px 10px; clip-path: polygon(8px 0%, 100% 0%, calc(100% - 8px) 100%, 0% 100%); }
  .phase-num { font-size: 0.6rem; color: #ECAA27; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 700; }
  .phase-title { font-size: 0.85rem; font-weight: 900; color: #fff; line-height: 1.1; margin: 2px 0; }
  .phase-date { font-size: 0.6rem; color: #ECAA27; margin-bottom: 3px; }
  .phase-bullets { list-style: none; padding: 0; }
  .phase-bullets li { font-size: 0.65rem; color: rgba(255,255,255,0.8); padding: 1px 0 1px 10px; position: relative; }
  .phase-bullets li::before { content: '›'; position: absolute; left: 0; color: #ECAA27; }
  .metric-box { background: #f5f0e8; border: 2px solid #111111; text-align: center; padding: 6px; clip-path: polygon(8px 0%, 100% 0%, calc(100% - 8px) 100%, 0% 100%); }
  .metric-val { font-size: 1.1rem; font-weight: 900; color: #ECAA27; line-height: 1; text-shadow: 1px 1px 0 #111111; }
  .metric-lbl { font-size: 0.58rem; color: #111111; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 2px; }
  .target-card { background: #fff; border: 1px solid rgba(17,17,17,0.15); border-top: 3px solid #111111; padding: 3px 8px; }
  .target-title { font-size: 0.68rem; font-weight: 900; color: #111111; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 2px; }
  .target-bullets { list-style: none; padding: 0; }
  .target-bullets li { font-size: 0.65rem; color: #444444; padding: 1px 0 1px 9px; position: relative; }
  .target-bullets li::before { content: '▸'; position: absolute; left: 0; color: #ECAA27; font-size: 0.55rem; }
  .closing-box { background: #111111; color: #fff; padding: 6px 14px; margin-top: 4px; clip-path: polygon(6px 0%, 100% 0%, calc(100% - 6px) 100%, 0% 100%); }
  .closing-title { font-size: 0.72rem; font-weight: 900; color: #ECAA27; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 2px; }
  .closing-box p { font-size: 0.7rem; color: rgba(255,255,255,0.9); line-height: 1.35; margin-bottom: 2px; }
  .closing-box strong { color: #ECAA27; }
  .closing-contact { font-size: 0.63rem; color: rgba(255,255,255,0.6); margin-top: 3px; }
  .section-wrap { margin-bottom: 4px; }
  @media print {
    @page { size: letter portrait; margin: 0.15in 0.25in; }
    body { background: none; }
    .page { box-shadow: none; margin: 0; width: 100%; }
    .page-inner { padding: 6px 10px; }
    .no-print { display: none !important; }
  }
"""


def build_overview(agency, n):
    name = agency.get('name') or 'Agency'
    city = agency.get('city') or 'Maryland'
    atype = agency.get('type') or 'Home Health Agency'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Digital Presence Overview &mdash; {name}</title>
<style>{OVERVIEW_CSS}</style>
</head>
<body>
<div class="page">
  <div class="top-stripe"></div>
  <div class="page-inner">

    <div class="no-print">
      <button class="print-btn" onclick="window.print()">Print / Export PDF</button>
    </div>

    <div class="ovr-header">
      <div class="ovr-header-left">
        <h1>DIGITAL PRESENCE PACKAGE <span>|</span> {name}</h1>
        <div class="ovr-sub">{city}, Maryland &nbsp;&middot;&nbsp; Digitalization Outreach Overview</div>
      </div>
      <div class="ovr-header-right">
        <img src="/static/logo.png" alt="Proles Home Healthcare Consultants">
        <div class="ovr-meta">Executive Overview &nbsp;&middot;&nbsp; May 2026 &nbsp;&middot;&nbsp; Confidential</div>
      </div>
    </div>

    <div class="divider"></div>

    <div class="stats-row">
      <div class="stat-box">
        <div class="stat-val">65%</div>
        <div class="stat-lbl">Families Search Online Before Choosing a Provider</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">3 Wks</div>
        <div class="stat-lbl">Average Time to Launch</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">50+</div>
        <div class="stat-lbl">MD Agencies Ready to Compete Online</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">$1,800</div>
        <div class="stat-lbl">Total Investment &mdash; All-In</div>
      </div>
    </div>

    <div class="snapshot-bar">
      <div class="snap-item">
        <div class="snap-lbl">Agency</div>
        <div class="snap-val">{name}</div>
      </div>
      <div class="snap-item">
        <div class="snap-lbl">Location</div>
        <div class="snap-val">{city}, Maryland</div>
      </div>
      <div class="snap-item">
        <div class="snap-lbl">Type</div>
        <div class="snap-val">{atype}</div>
      </div>
      <div class="snap-item" style="flex:2;">
        <div class="snap-lbl">Service</div>
        <div class="snap-val">Digital Presence Package &mdash; Website + SEO + Staff Portal</div>
      </div>
    </div>

    <div class="section-wrap">
      <div class="section-label">Current Capability Gaps &amp; Cost of Inaction</div>
      <div class="two-col">
        <div class="col-panel">
          <table class="data-table">
            <thead><tr><th>Capability</th><th>Status</th></tr></thead>
            <tbody>
              <tr><td>Professional Website</td><td><span class="badge-none">NONE</span></td></tr>
              <tr><td>Local SEO (Google)</td><td><span class="badge-none">NONE</span></td></tr>
              <tr><td>Staff / Employee Portal</td><td><span class="badge-none">NONE</span></td></tr>
              <tr><td>Online Contact &amp; Booking</td><td><span class="badge-none">NONE</span></td></tr>
            </tbody>
          </table>
        </div>
        <div class="col-panel">
          <table class="data-table">
            <thead><tr><th>Cost of Inaction</th><th style="text-align:right;">Per Year</th></tr></thead>
            <tbody>
              <tr><td>Families finding competitor online</td><td style="text-align:right;">~$24,000</td></tr>
              <tr><td>Lost referral partner trust</td><td style="text-align:right;">~$18,000</td></tr>
              <tr><td>Manual phone inquiry overhead</td><td style="text-align:right;">~$8,000</td></tr>
              <tr><td>No after-hours client capture</td><td style="text-align:right;">~$12,000</td></tr>
              <tr class="total-row"><td>TOTAL ANNUAL EXPOSURE</td><td style="text-align:right;">~$62,000/yr</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="section-wrap">
      <div class="section-label">3-Phase Delivery Plan</div>
      <div class="three-col">
        <div class="phase-card">
          <div class="phase-num">Phase 01</div>
          <div class="phase-title">Audit &amp; Brand</div>
          <div class="phase-date">Weeks 1&ndash;2</div>
          <ul class="phase-bullets">
            <li>Discovery call &amp; readiness audit</li>
            <li>Brand identity &amp; color system</li>
            <li>Site architecture &amp; content plan</li>
            <li>Domain &amp; hosting setup</li>
          </ul>
        </div>
        <div class="phase-card">
          <div class="phase-num">Phase 02</div>
          <div class="phase-title">Build &amp; Launch</div>
          <div class="phase-date">Weeks 2&ndash;4</div>
          <ul class="phase-bullets">
            <li>Mobile-first website</li>
            <li>Staff &amp; employee portal</li>
            <li>Appointment &amp; contact forms</li>
            <li>Live deployment &amp; QA</li>
          </ul>
        </div>
        <div class="phase-card" style="background:#8a0a0a;">
          <div class="phase-num">Phase 03</div>
          <div class="phase-title">SEO &amp; Optimize</div>
          <div class="phase-date">Days 30&ndash;60</div>
          <ul class="phase-bullets">
            <li>Google Business Profile setup</li>
            <li>Local keyword targeting for {city}</li>
            <li>On-page metadata &amp; schema</li>
            <li>GA4 analytics &amp; monthly report</li>
          </ul>
        </div>
      </div>
    </div>

    <div class="section-wrap">
      <div class="section-label">Financial Summary</div>
      <div class="two-col">
        <div class="col-panel">
          <table class="data-table">
            <thead><tr><th>Investment Breakdown</th><th style="text-align:right;">Amount</th></tr></thead>
            <tbody>
              <tr><td>Website Design &amp; Development</td><td style="text-align:right;">$1,200</td></tr>
              <tr><td>Staff / Employee Portal</td><td style="text-align:right;">$400</td></tr>
              <tr><td>Local SEO Setup</td><td style="text-align:right;">$200</td></tr>
              <tr class="total-row"><td>TOTAL INVESTMENT</td><td style="text-align:right;">$1,800</td></tr>
            </tbody>
          </table>
        </div>
        <div class="col-panel">
          <table class="data-table">
            <thead><tr><th>Year 1 Return Estimate</th><th style="text-align:right;">Value</th></tr></thead>
            <tbody>
              <tr><td>New clients via search (est. 3&ndash;5)</td><td style="text-align:right;">+$8,400</td></tr>
              <tr><td>Referral partner credibility</td><td style="text-align:right;">+$3,600</td></tr>
              <tr><td>Reduced phone inquiry overhead</td><td style="text-align:right;">+$1,200</td></tr>
              <tr class="total-row"><td>TOTAL YEAR 1 RETURN</td><td style="text-align:right;">+$13,200</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="four-col section-wrap">
      <div class="metric-box">
        <div class="metric-val">7.3&times;</div>
        <div class="metric-lbl">ROI &mdash; Year 1</div>
      </div>
      <div class="metric-box">
        <div class="metric-val">3 Wks</div>
        <div class="metric-lbl">Time to Launch</div>
      </div>
      <div class="metric-box">
        <div class="metric-val">60 Days</div>
        <div class="metric-lbl">SEO Ranking Window</div>
      </div>
      <div class="metric-box">
        <div class="metric-val">$11,400</div>
        <div class="metric-lbl">Net Year 1 Benefit</div>
      </div>
    </div>

    <div class="section-wrap">
      <div class="section-label">Success Targets &mdash; 90 Days Post-Launch</div>
      <div class="three-col">
        <div class="target-card">
          <div class="target-title">Website</div>
          <ul class="target-bullets">
            <li>500+ visitors / month</li>
            <li>80%+ mobile traffic</li>
            <li>50+ contact form submissions / month</li>
          </ul>
        </div>
        <div class="target-card">
          <div class="target-title">Local SEO &mdash; {city}</div>
          <ul class="target-bullets">
            <li>Top 10 Google for &ldquo;{city} home health&rdquo;</li>
            <li>Google Business Profile live &amp; verified</li>
            <li>100+ monthly local search impressions</li>
          </ul>
        </div>
        <div class="target-card">
          <div class="target-title">Client Growth</div>
          <ul class="target-bullets">
            <li>3&ndash;5 new clients from search (Year 1)</li>
            <li>24-hour inquiry response standard</li>
            <li>Referral partner onboarding (Year 1)</li>
          </ul>
        </div>
      </div>
    </div>

    <div class="closing-box">
      <div class="closing-title">Recommendation</div>
      <p>Authorize the Digital Presence Package for <strong>{name}</strong>. Schedule your free 15-minute discovery call to begin. Launch within 3 weeks of kickoff.</p>
      <p>Investment: <strong>$1,800 total</strong> &nbsp;&middot;&nbsp; Estimated Year 1 Return: <strong>$13,200</strong> &nbsp;&middot;&nbsp; Net Year 1 Benefit: <strong>$11,400</strong></p>
      <div class="closing-contact">amthuku@gmail.com &nbsp;&middot;&nbsp; (434) 429-9296 &nbsp;&middot;&nbsp; Alexander Thuku &nbsp;&middot;&nbsp; Proles Home Healthcare Consultants</div>
    </div>

  </div>
</div>
</body>
</html>"""


# ── Proposal HTML ─────────────────────────────────────────────────────────────

def build_proposal(agency, n):
    name = agency.get('name') or 'Agency'
    atype = agency.get('type') or ''
    city = agency.get('city') or 'Maryland'
    phrase = type_phrase(atype)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Digital Presence Package &mdash; {name}</title>
<style>{PROPOSAL_CSS}</style>
</head>
<body>
<div class="action-bar">
  <div class="action-left">
    <span class="action-name">{name}</span>
    <span class="action-type">{atype}</span>
  </div>
  <div class="action-right">
    <a href="/email/{n}" target="_blank" class="action-btn">Preview Email</a>
    <button onclick="generateDraft()" class="action-btn action-btn-red">Generate Email</button>
    <button onclick="window.print()" class="action-btn">Print Proposal</button>
  </div>
</div>
<div class="toast" id="toast"></div>
<div class="page">

  <div class="header">
    <div class="header-left">
      <div class="header-title">Digital <em>Presence</em> Package</div>
      <div class="header-sub">For {name}</div>
    </div>
    <div class="header-right">
      <img src="/static/logo.png" alt="Proles Home Healthcare Consultants" style="height:100px;width:auto;display:block;">
    </div>
  </div>

  <div class="section">
    <div class="section-label label-gold">The Problem</div>
    <div class="problem-text">
      <strong>65% of families search online before choosing a care provider.</strong>
      {phrase} if you have no website, they find your competitor instead &mdash; even if your care is better.
      You&rsquo;re licensed, operating, and serving real families. But you&rsquo;re invisible to everyone searching online right now.
    </div>
  </div>

  <div class="two-col">
    <div>
      <div class="section-label label-red">What We Deliver</div>
      <ul class="deliver-list">
        <li><strong>Professional website</strong> &mdash; branded, mobile-friendly, fast</li>
        <li><strong>Staff &amp; employee portal</strong> &mdash; internal tools for your team</li>
        <li><strong>Appointment &amp; contact forms</strong> &mdash; clients reach you directly</li>
        <li><strong>Deployed in under 3 weeks</strong> &mdash; no months-long delays</li>
      </ul>
    </div>
    <div>
      <div class="section-label label-gold">Your Demo Site</div>
      <div class="example-box">
        <a class="example-url" href="{RAILWAY_URL}/demo/{n}" target="_blank">{RAILWAY_URL}/demo/{n}</a>
        <div class="example-desc">
          This personalized demo was built specifically for <strong style="color:#ECAA27">{name}</strong> &mdash; a branded homepage, service pages, and contact forms. Exactly what your live site will look like.
        </div>
        <span class="example-badge">PERSONALIZED FOR YOU</span>
      </div>
    </div>
  </div>

  <div class="section">
    <span class="section-label label-gold">WHY SEO MATTERS</span>
    <div class="why-text">
      <strong>83% of families search online before choosing a care provider.</strong> Without a website, {name} is invisible to every one of them. We build every site with SEO fundamentals baked in from day one: local schema markup, Google Business Profile integration, keyword-optimized service pages for <strong>{city}</strong>, and structured metadata that tells search engines exactly who you are and what you do.
      <br><br>
      Within 60 days of launch, families searching <em>"home health agency in {city}"</em> will find you &mdash; not your competitors. A website without SEO is a brochure locked in a drawer. Ours are built to be found.
    </div>
  </div>

  <div class="section">
    <div class="section-label label-red">Why Proles HHC</div>
    <div class="why-text">
      <strong>Maryland-based. Healthcare-focused.</strong> We understand DDA and home health compliance, OHCQ licensing requirements, and what Maryland families actually need to trust a provider enough to call.
      We don&rsquo;t build generic websites &mdash; we build platforms that make licensed agencies look as professional as they are.
    </div>
  </div>

  <div class="cta-box">
    <div>
      <div class="cta-headline">Ready to be found?<br><em>Let&rsquo;s talk.</em></div>
    </div>
    <div class="cta-contact">
      <a href="mailto:amthuku@gmail.com">amthuku@gmail.com</a><br>
      (434) 429-9296<br>
      Alexander Thuku
    </div>
  </div>

  <div class="footer">
    <div class="footer-left">Proles Home Healthcare Consultants &nbsp;&bull;&nbsp; Baltimore, MD</div>
    <div class="footer-right">
      <a href="https://{COMPANY_URL}">{COMPANY_URL}</a>
      &nbsp;&bull;&nbsp; Project Management &amp; Digital Solutions &nbsp;&bull;&nbsp; April 2026
    </div>
  </div>

</div>
<script>
async function generateDraft() {{
  const btn = document.querySelector('.action-btn-red');
  btn.textContent = 'Generating...';
  btn.disabled = true;
  try {{
    const res = await fetch('/generate-draft/{n}');
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    showToast('Draft created in Gmail — PDF attached');
    setTimeout(() => window.open(data.gmail_url, '_blank'), 500);
  }} catch(e) {{
    showToast('Error: ' + e.message);
  }} finally {{
    btn.textContent = 'Generate Email';
    btn.disabled = false;
  }}
}}
function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 4000);
}}
</script>
</body>
</html>"""


_CSS_VAR_MAP = [
    ('var(--gold-light)', '#ffc84d'),
    ('var(--red-light)',  '#e05252'),
    ('var(--text3)',      '#444444'),
    ('var(--text2)',      '#888888'),
    ('var(--text)',       '#f5f0e8'),
    ('var(--bg3)',        '#2a2a2a'),
    ('var(--bg2)',        '#1a1a1a'),
    ('var(--bg)',         '#111111'),
    ('var(--gold)',       '#ECAA27'),
    ('var(--red)',        '#8a0a0a'),
]


def build_proposal_for_pdf(agency, n):
    html = build_proposal(agency, n)
    for var, val in _CSS_VAR_MAP:
        html = html.replace(var, val)
    return html


def demo_services(agency_type):
    t = (agency_type or '').lower()
    if 'home health' in t:
        return [
            ('Skilled Nursing', 'Registered nurses providing medical care in the comfort of home.'),
            ('Physical Therapy', 'Rehabilitation to restore strength, mobility, and independence.'),
            ('Home Health Aide', 'Assistance with daily activities, hygiene, and personal care.'),
            ('Medication Management', 'Ensuring medications are taken correctly and on schedule.'),
        ]
    if 'dda' in t or 'residential' in t or 'rsa' in t:
        return [
            ('Community Support', 'Helping individuals integrate and thrive in their communities.'),
            ('Residential Services', 'Safe, supportive living environments tailored to each person.'),
            ('Skills Training', 'Building independence through life skills and vocational support.'),
            ('Care Planning', 'Individualized care plans developed with clients and families.'),
        ]
    return [
        ('Personal Care', 'Compassionate assistance with daily living activities.'),
        ('Companion Services', 'Friendly support and social engagement for seniors and adults.'),
        ('Care Coordination', 'Connecting clients to the right services and community resources.'),
        ('Family Support', 'Guidance and respite resources for family caregivers.'),
    ]


def build_client_site(page_html, agency, n):
    name  = (agency.get('name') or 'Your Agency').strip()
    city  = (agency.get('city') or 'Your City').strip()
    phone = (agency.get('phone') or '+1 (434) 429-9296').strip()
    base  = f'/client-site/{n}'

    h = page_html

    NEW_TEAM_GRID = """<div class="team-grid">
  <div class="team-card">
    <img class="team-avatar" src="https://randomuser.me/api/portraits/women/44.jpg" alt="Team member" style="object-fit:cover;">
    <h4>Dr. Angela Brooks</h4>
    <p class="team-role">Founder &amp; Executive Director</p>
    <p>With over 18 years in disability and behavioral health services, Dr. Brooks founded this agency to bring person-centered care to Maryland&rsquo;s most underserved communities. She leads strategic direction, community partnerships, and the mission of every client we serve.</p>
  </div>
  <div class="team-card">
    <img class="team-avatar" src="https://randomuser.me/api/portraits/men/32.jpg" alt="Team member" style="object-fit:cover;">
    <h4>James Carter, LCSW</h4>
    <p class="team-role">Director of Clinical Services</p>
    <p>A licensed clinical social worker with 14 years in behavioral health, James oversees care planning, clinical quality, and staff training. He specializes in trauma-informed care and positive behavioral support for individuals with intellectual disabilities.</p>
  </div>
  <div class="team-card">
    <img class="team-avatar" src="https://randomuser.me/api/portraits/women/68.jpg" alt="Team member" style="object-fit:cover;">
    <h4>Patricia Moore, RN</h4>
    <p class="team-role">Care Coordination Supervisor</p>
    <p>A registered nurse and certified DDA support specialist, Patricia manages client intake, assessments, and ongoing care coordination. Every individual&rsquo;s care plan is current, compliant, and built around their personal goals.</p>
  </div>
  <div class="team-card">
    <img class="team-avatar" src="https://randomuser.me/api/portraits/men/75.jpg" alt="Team member" style="object-fit:cover;">
    <h4>Robert Davis</h4>
    <p class="team-role">Compliance &amp; Training Manager</p>
    <p>Robert leads staff credentialing, DDA compliance, and HIPAA policy. He oversees the DSP training program and ensures all staff meet Maryland&rsquo;s certification requirements before they begin serving clients.</p>
  </div>
</div>"""
    h = re.sub(r'<div class="team-grid">.*?</div>\s*</div>\s*</div>\s*</section>',
               NEW_TEAM_GRID + '</div></section>', h, flags=re.DOTALL)

    OLD_HISTORY = """          <p>Inspired Options Inc was founded in 2014 by Dr. Patricia Ametepi, a social work professional with two decades of experience in disability and behavioral health services. After years working within institutional settings, she saw the same gap over and over: individuals with cognitive and developmental disabilities who were capable of living rich, connected lives — but lacked the community-based support to do so.</p>
          <p>She founded Inspired Options Inc with a simple belief: that every person deserves a real choice in how they live, where they live, and who supports them. Starting with a small team and three clients in Baltimore City, the organization grew steadily by earning the trust of families, referral partners, and the individuals we serve.</p>
          <p>Today, Inspired Options Inc is an approved Maryland DDA provider serving individuals and families across Baltimore City, Baltimore County, Anne Arundel County, and Howard County. Our team of trained care professionals is united by one mission — to help every person we serve live fully in their community.</p>"""
    NEW_HISTORY = """          <p>This agency was founded by a healthcare professional with decades of experience in disability and behavioral health services. After years working within institutional settings, the founder saw the same gap over and over: individuals with cognitive and developmental disabilities who were capable of living rich, connected lives — but lacked the community-based support to do so.</p>
          <p>The agency was built on a simple belief: that every person deserves a real choice in how they live, where they live, and who supports them.</p>
          <p>Today, this agency is an approved Maryland DDA provider serving individuals and families across the region. Our team of trained care professionals is united by one mission — to help every person we serve live fully in their community.</p>"""
    h = h.replace(OLD_HISTORY, NEW_HISTORY)
    h = h.replace('Dr. Patricia Ametepi', 'Dr. Angela Brooks')
    h = h.replace('Dr. Ametepi', 'Dr. Brooks')
    h = h.replace('Marcus Johnson, LCSW', 'James Carter, LCSW')
    h = h.replace('Marcus Johnson', 'James Carter')
    h = h.replace('Tamara Reeves, RN', 'Patricia Moore, RN')
    h = h.replace('Tamara Reeves', 'Patricia Moore')
    h = h.replace('David Williams', 'Robert Davis')

    h = h.replace('Inspired Options Inc', name)
    h = h.replace('Inspired Options Care', name)
    h = h.replace('Inspired Options', name)
    h = h.replace('Current IOI clients', 'Current clients')
    h = h.replace('+1 (434) 429-9296', phone)
    h = h.replace('+1 (443) 374-2931', phone)
    h = h.replace('(443) 374-2931', phone)
    h = h.replace('443-374-2931', phone)
    h = h.replace('(434) 429-9296', phone)
    h = h.replace('434-429-9296', phone)
    h = h.replace('Baltimore, MD', f'{city}, MD')
    h = h.replace('Baltimore, Maryland', f'{city}, Maryland')
    h = h.replace('href="index.html"',    f'href="{base}/"')
    h = h.replace('href="services.html"', f'href="{base}/services"')
    h = h.replace('href="about.html"',    f'href="{base}/about"')
    h = h.replace('href="contact.html"',  f'href="{base}/contact"')
    h = h.replace('href="who-we-serve.html"', f'href="{base}/"')
    h = h.replace('href="faq.html"',      f'href="{base}/"')
    h = h.replace('href="careers.html"',  f'href="{base}/"')
    h = h.replace('href="employment.html"', f'href="{base}/"')
    h = h.replace('href="cims.html"',     f'href="{base}/"')
    h = h.replace('href="style.css"', 'href="/client-site/style.css"')
    h = h.replace("href='style.css'", "href='/client-site/style.css'")
    h = h.replace('https://inspiredoptionscare.com', f'/client-site/{n}')
    h = h.replace('http://inspiredoptionscare.com',  f'/client-site/{n}')

    # Email address
    email = (agency.get('email') or '').strip()
    agency_email = email if email else f'info@{slugify(name)}.com'
    h = h.replace('mailto:info@inspiredoptionscare.com', f'mailto:{agency_email}')
    h = h.replace('info@inspiredoptionscare.com', agency_email)
    h = h.replace('inspiredoptionscare.com', f'{slugify(name)}.com')

    # tel: href with agency phone digits
    phone_digits = re.sub(r'\D', '', phone)
    if len(phone_digits) >= 10:
        tel_phone = f'+1{phone_digits[-10:]}'
        h = h.replace('tel:+14344299296', f'tel:{tel_phone}')
        h = h.replace('tel:+14433742931', f'tel:{tel_phone}')

    # Instagram handle
    h = h.replace('https://www.instagram.com/InspiredOptionsCare', '#')
    h = h.replace('@InspiredOptionsCare on Instagram', f'@{name}')
    h = h.replace('InspiredOptionsCare', name.replace(' ', ''))

    return h


def build_demo(agency, n):
    name     = agency.get('name')  or 'Agency'
    atype    = agency.get('type')  or ''
    city     = agency.get('city')  or 'Maryland'
    phone    = agency.get('phone') or ''
    email    = agency.get('email') or ''
    phrase   = type_phrase(atype)
    services = demo_services(atype)

    t = atype.lower()
    if 'home health' in t:
        svc_type     = 'home health'
        mission_text = (
            f'At {name}, we believe that healing happens best at home. Our licensed clinicians and '
            f'compassionate home health aides deliver skilled nursing, therapy, and personal care '
            f'directly to our clients across {city} and surrounding Maryland communities. '
            f'We build individualized care plans that treat the whole person &mdash; not just the diagnosis.'
        )
        who_serve = [
            ('Seniors &amp; Older Adults',           'Helping seniors maintain independence and dignity in their own homes.'),
            ('Post-Surgical Patients',               'Supporting safe recovery after hospitalization or surgery.'),
            ('Individuals with Chronic Conditions',  'Ongoing skilled care for diabetes, cardiac conditions, and more.'),
            ('Families Seeking Respite',             'Professional home care that gives family caregivers a well-deserved break.'),
        ]
    elif 'dda' in t or 'residential' in t or 'rsa' in t:
        svc_type     = 'residential care'
        mission_text = (
            f'At {name}, we are committed to helping individuals with developmental disabilities '
            f'live full, self-directed lives in their communities. Our certified support staff provide '
            f'residential care, skills training, and community integration services tailored to each '
            f"person&rsquo;s unique goals and needs across {city}, Maryland."
        )
        who_serve = [
            ('Individuals with Developmental Disabilities', 'Person-centered support for adults with intellectual and developmental disabilities.'),
            ('Families Seeking Supported Living',           'Residential and in-home supports that keep families informed and involved.'),
            ('Those Transitioning from Institutional Care', 'Community-based alternatives for individuals moving from group homes or facilities.'),
            ('Youth &amp; Young Adults',                    'Early intervention and skills-building for youth with autism and intellectual disabilities.'),
        ]
    elif 'day care' in t or 'adult day' in t or 'adult medical' in t:
        svc_type     = 'adult day care'
        mission_text = (
            f'At {name}, we provide a warm, structured daytime environment for adults who need '
            f'supervision, socialization, and skilled care. Our licensed adult day programs in {city} '
            f'support independence and quality of life while giving family caregivers the reliable '
            f'respite they need to thrive.'
        )
        who_serve = [
            ('Seniors with Memory Conditions',   "Safe, structured programming for individuals with dementia and Alzheimer&rsquo;s."),
            ('Adults with Physical Disabilities', 'Accessible day programs with therapy, activities, and skilled nursing.'),
            ('Caregivers Needing Daily Respite',  'Reliable daytime care so family members can work and recharge.'),
            ('Individuals Seeking Engagement',    'Community connection and meaningful activities for isolated adults.'),
        ]
    else:
        svc_type     = 'care'
        mission_text = (
            f'At {name}, our mission is simple: provide exceptional, compassionate care that empowers '
            f'every client to live with dignity, independence, and purpose. Serving {city} and the '
            f'surrounding Maryland area, we offer a full continuum of care services coordinated around '
            f"each individual&rsquo;s unique needs and goals."
        )
        who_serve = [
            ('Older Adults &amp; Seniors',           'Personalized care and support to help seniors remain in their communities.'),
            ('Individuals with Disabilities',        'Tailored support services for adults with physical and cognitive disabilities.'),
            ('Post-Hospitalization Clients',         'Transitional care and home support after hospital discharge.'),
            ('Families Seeking Care Coordination',   'Connecting families to the right services and community resources.'),
        ]

    # Service cards
    cards_html = ''
    for idx, (svc_name, svc_desc) in enumerate(services):
        num_str = f'0{idx + 1}'
        cards_html += (
            f'<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-top:3px solid #ECAA27;padding:32px;">'
            f'<div style="font-size:13px;font-weight:900;color:#ECAA27;letter-spacing:3px;margin-bottom:14px;'
            f"font-family:'Arial Black',Arial,sans-serif;\">{num_str}</div>"
            f'<div style="font-size:18px;font-weight:900;color:#f5f0e8;margin-bottom:10px;'
            f"font-family:'Arial Black',Arial,sans-serif;\">{svc_name}</div>"
            f'<div style="font-size:14px;color:#888888;line-height:1.7;">{svc_desc}</div>'
            f'</div>'
        )

    # Who we serve cards
    who_html = ''
    for (group, desc) in who_serve:
        who_html += (
            f'<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-left:4px solid #ECAA27;padding:24px 28px;">'
            f'<div style="font-size:16px;font-weight:900;color:#f5f0e8;margin-bottom:8px;'
            f"font-family:'Arial Black',Arial,sans-serif;\">{group}</div>"
            f'<div style="font-size:14px;color:#888888;line-height:1.6;">{desc}</div>'
            f'</div>'
        )

    # Phone + email
    phone_html = ''
    if phone and phone != '—':
        phone_html = (
            f'<div style="font-size:40px;font-weight:900;color:#ECAA27;margin:20px 0;'
            f"letter-spacing:1px;font-family:'Arial Black',Arial,sans-serif;\">{phone}</div>"
        )
    email_html = ''
    if email and email != '—':
        email_html = (
            f'<div style="font-size:15px;color:#888888;margin-bottom:8px;">'
            f'<a href="mailto:{email}" style="color:#ECAA27;text-decoration:none;">{email}</a>'
            f'</div>'
        )

    accent_bar = '<div style="height:4px;background:linear-gradient(90deg,#8a0a0a,#ECAA27);"></div>'
    name_upper = name.upper()
    phrase_clean = phrase.rstrip(',')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{name} &mdash; Professional {svc_type.title()} Services</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Arial, Helvetica, sans-serif; background: #111111; color: #f5f0e8; }}
a {{ text-decoration: none; }}
html {{ scroll-behavior: smooth; }}
</style>
</head>
<body>

<!-- DEMO BANNER -->
<div style="background:#ECAA27;color:#111111;font-size:10px;font-weight:900;text-transform:uppercase;
     letter-spacing:2px;text-align:center;padding:0 20px;position:fixed;top:0;left:0;right:0;
     z-index:9999;height:38px;display:flex;align-items:center;justify-content:center;">
  <span>DEMO PREVIEW &mdash; BUILT FOR {name} BY PROLES HHC &mdash; NOT A LIVE WEBSITE</span>
  <a href="{RAILWAY_URL}/proposal/{n}" target="_blank"
     style="position:absolute;right:20px;color:#8a0a0a;font-size:9px;font-weight:900;
            letter-spacing:1px;text-transform:uppercase;">
    VIEW PROPOSAL &rarr;
  </a>
</div>

<!-- STICKY NAV -->
<nav style="background:#111111;border-bottom:2px solid #ECAA27;position:sticky;top:38px;z-index:998;
     height:60px;display:flex;align-items:center;justify-content:space-between;padding:0 60px;">
  <div style="font-size:16px;font-weight:900;color:#ECAA27;
       font-family:'Arial Black',Arial,sans-serif;letter-spacing:-0.5px;">{name}</div>
  <div style="display:flex;align-items:center;gap:28px;">
    <a href="#services" style="color:#f5f0e8;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;"
       onmouseover="this.style.color='#ECAA27'" onmouseout="this.style.color='#f5f0e8'">Services</a>
    <a href="#about" style="color:#f5f0e8;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;"
       onmouseover="this.style.color='#ECAA27'" onmouseout="this.style.color='#f5f0e8'">About</a>
    <a href="#who-we-serve" style="color:#f5f0e8;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;"
       onmouseover="this.style.color='#ECAA27'" onmouseout="this.style.color='#f5f0e8'">Who We Serve</a>
    <a href="#careers" style="color:#f5f0e8;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;"
       onmouseover="this.style.color='#ECAA27'" onmouseout="this.style.color='#f5f0e8'">Careers</a>
    <a href="#contact"
       style="background:#ECAA27;color:#111111;padding:9px 20px;font-size:12px;font-weight:900;
              text-transform:uppercase;letter-spacing:2px;
              clip-path:polygon(0 0,calc(100% - 6px) 0,100% 6px,100% 100%,6px 100%,0 calc(100% - 6px));">
      Contact Us
    </a>
  </div>
</nav>

<!-- HERO -->
<section style="min-height:100vh;background:#111111;padding:120px 60px 180px;position:relative;
     clip-path:polygon(0 0,100% 0,100% calc(100% - 60px),0 100%);overflow:hidden;">
  <div style="position:absolute;top:0;right:10%;width:3px;height:100%;
       background:linear-gradient(180deg,transparent,#8a0a0a,transparent);opacity:0.4;transform:skewX(-20deg);"></div>
  <div style="position:absolute;top:0;right:15%;width:1px;height:100%;
       background:linear-gradient(180deg,transparent,#ECAA27,transparent);opacity:0.2;transform:skewX(-20deg);"></div>
  <div style="display:flex;align-items:center;justify-content:space-between;max-width:1200px;gap:60px;">
    <div style="flex:1;max-width:680px;">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:24px;">
        <div style="width:4px;height:32px;background:#ECAA27;flex-shrink:0;"></div>
        <span style="font-size:12px;font-weight:900;color:#ECAA27;letter-spacing:3px;text-transform:uppercase;">// {name}</span>
      </div>
      <div style="font-size:12px;font-weight:900;color:#888888;text-transform:uppercase;
           letter-spacing:3px;margin-bottom:20px;">{city}, Maryland &middot; {phrase_clean}</div>
      <h1 style="font-size:68px;font-weight:900;color:#f5f0e8;line-height:1.0;margin-bottom:24px;
           letter-spacing:-2px;font-family:'Arial Black',Arial,sans-serif;">{name}</h1>
      <p style="font-size:19px;color:#888888;line-height:1.6;margin-bottom:40px;">
        Caring for your whole life &mdash; professional {svc_type} services for Maryland families.
      </p>
      <div style="display:flex;gap:16px;flex-wrap:wrap;">
        <a href="#contact"
           style="background:#ECAA27;color:#111111;padding:16px 36px;font-size:12px;font-weight:900;
                  text-transform:uppercase;letter-spacing:2px;display:inline-block;
                  clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));
                  font-family:'Arial Black',Arial,sans-serif;">
          Request Services &rarr;
        </a>
        <a href="#services"
           style="background:transparent;border:2px solid #ECAA27;color:#ECAA27;padding:16px 36px;
                  font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:2px;
                  display:inline-block;font-family:'Arial Black',Arial,sans-serif;">
          Learn More
        </a>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:16px;min-width:220px;">
      <div style="background:#1a1a1a;border:1px solid #2a2a2a;border-top:3px solid #ECAA27;padding:24px 28px;">
        <div style="font-size:10px;font-weight:900;color:#ECAA27;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">STATUS</div>
        <div style="font-size:16px;font-weight:900;color:#f5f0e8;font-family:'Arial Black',Arial,sans-serif;">Maryland Licensed</div>
        <div style="font-size:12px;color:#888888;margin-top:4px;">OHCQ Certified Provider</div>
      </div>
      <div style="background:#1a1a1a;border:1px solid #2a2a2a;border-top:3px solid #8a0a0a;padding:24px 28px;">
        <div style="font-size:10px;font-weight:900;color:#ECAA27;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">LOCATION</div>
        <div style="font-size:16px;font-weight:900;color:#f5f0e8;font-family:'Arial Black',Arial,sans-serif;">Serving {city}</div>
        <div style="font-size:12px;color:#888888;margin-top:4px;">Maryland &amp; Surrounding Areas</div>
      </div>
      <div style="background:#1a1a1a;border:1px solid #2a2a2a;border-top:3px solid #ECAA27;padding:24px 28px;">
        <div style="font-size:10px;font-weight:900;color:#ECAA27;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;">COMPLIANCE</div>
        <div style="font-size:16px;font-weight:900;color:#f5f0e8;font-family:'Arial Black',Arial,sans-serif;">OHCQ Compliant</div>
        <div style="font-size:12px;color:#888888;margin-top:4px;">State Regulated &amp; Inspected</div>
      </div>
    </div>
  </div>
</section>

<!-- ACCENT BAR -->
{accent_bar}

<!-- MISSION -->
<section id="about" style="background:#1a1a1a;padding:80px 60px;">
  <div style="max-width:1200px;">
    <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
         letter-spacing:3px;margin-bottom:16px;font-family:'Arial Black',Arial,sans-serif;">OUR MISSION</div>
    <h2 style="font-size:42px;font-weight:900;color:#f5f0e8;margin-bottom:48px;
         font-family:'Arial Black',Arial,sans-serif;">Care That Puts You First</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:60px;align-items:start;">
      <div>
        <p style="font-size:16px;color:#888888;line-height:1.8;margin-bottom:24px;">{mission_text}</p>
        <p style="font-size:15px;color:#666666;line-height:1.8;">
          We work closely with families, care coordinators, and Maryland&rsquo;s DDA and OHCQ systems to
          ensure every client receives the highest standard of care &mdash; delivered with respect and dignity.
        </p>
      </div>
      <div style="background:#111111;border:1px solid #2a2a2a;border-left:4px solid #ECAA27;padding:36px;">
        <div style="font-size:10px;font-weight:900;color:#ECAA27;letter-spacing:3px;text-transform:uppercase;
             margin-bottom:20px;font-family:'Arial Black',Arial,sans-serif;">OUR PROMISE</div>
        <blockquote style="font-size:22px;font-weight:900;color:#f5f0e8;line-height:1.4;margin-bottom:20px;
             font-family:'Arial Black',Arial,sans-serif;">
          &ldquo;Every person we serve deserves to live fully in their community.&rdquo;
        </blockquote>
        <div style="height:2px;background:linear-gradient(90deg,#8a0a0a,#ECAA27);margin-bottom:20px;"></div>
        <div style="font-size:13px;color:#888888;">Licensed by Maryland OHCQ &middot; {city}, MD</div>
      </div>
    </div>
  </div>
</section>

<!-- ACCENT BAR -->
{accent_bar}

<!-- SERVICES -->
<section id="services" style="background:#111111;padding:80px 60px;">
  <div style="max-width:1200px;">
    <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
         letter-spacing:3px;margin-bottom:16px;font-family:'Arial Black',Arial,sans-serif;">WHAT WE OFFER</div>
    <h2 style="font-size:42px;font-weight:900;color:#f5f0e8;margin-bottom:48px;
         font-family:'Arial Black',Arial,sans-serif;">Our Services</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">{cards_html}</div>
  </div>
</section>

<!-- WHY CHOOSE US -->
<section style="background:#1a1a1a;padding:80px 60px;">
  <div style="max-width:1200px;">
    <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
         letter-spacing:3px;margin-bottom:16px;font-family:'Arial Black',Arial,sans-serif;">WHY {name_upper}</div>
    <h2 style="font-size:42px;font-weight:900;color:#f5f0e8;margin-bottom:48px;
         font-family:'Arial Black',Arial,sans-serif;">Our Commitment to You</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:28px;">
      <div style="background:#111111;border:1px solid #2a2a2a;border-top:3px solid #ECAA27;padding:36px;">
        <div style="font-size:40px;color:#ECAA27;margin-bottom:20px;font-weight:900;
             font-family:'Arial Black',Arial,sans-serif;">01</div>
        <div style="font-size:18px;font-weight:900;color:#f5f0e8;margin-bottom:14px;
             font-family:'Arial Black',Arial,sans-serif;">Licensed &amp; Certified</div>
        <div style="font-size:14px;color:#888888;line-height:1.7;">
          Maryland OHCQ licensed and fully compliant. Your family&rsquo;s safety and trust is our highest priority.
        </div>
      </div>
      <div style="background:#111111;border:1px solid #2a2a2a;border-top:3px solid #ECAA27;padding:36px;">
        <div style="font-size:40px;color:#ECAA27;margin-bottom:20px;font-weight:900;
             font-family:'Arial Black',Arial,sans-serif;">02</div>
        <div style="font-size:18px;font-weight:900;color:#f5f0e8;margin-bottom:14px;
             font-family:'Arial Black',Arial,sans-serif;">Maryland Based</div>
        <div style="font-size:14px;color:#888888;line-height:1.7;">
          Rooted in the {city} community. We understand the unique needs of Maryland families and the resources available to them.
        </div>
      </div>
      <div style="background:#111111;border:1px solid #2a2a2a;border-top:3px solid #ECAA27;padding:36px;">
        <div style="font-size:40px;color:#ECAA27;margin-bottom:20px;font-weight:900;
             font-family:'Arial Black',Arial,sans-serif;">03</div>
        <div style="font-size:18px;font-weight:900;color:#f5f0e8;margin-bottom:14px;
             font-family:'Arial Black',Arial,sans-serif;">Personalized Care</div>
        <div style="font-size:14px;color:#888888;line-height:1.7;">
          Every client receives an individualized care plan tailored to their specific needs, goals, and family situation.
        </div>
      </div>
    </div>
  </div>
</section>

<!-- WHO WE SERVE -->
<section id="who-we-serve" style="background:#111111;padding:80px 60px;">
  <div style="max-width:1200px;">
    <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
         letter-spacing:3px;margin-bottom:16px;font-family:'Arial Black',Arial,sans-serif;">WHO WE SERVE</div>
    <h2 style="font-size:42px;font-weight:900;color:#f5f0e8;margin-bottom:48px;
         font-family:'Arial Black',Arial,sans-serif;">Serving Maryland Families</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">{who_html}</div>
  </div>
</section>

<!-- ACCENT BAR -->
{accent_bar}

<!-- CAREERS -->
<section id="careers" style="background:#1a1a1a;padding:60px 60px;">
  <div style="max-width:1200px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:32px;">
    <div>
      <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
           letter-spacing:3px;margin-bottom:12px;font-family:'Arial Black',Arial,sans-serif;">JOIN OUR TEAM</div>
      <h2 style="font-size:32px;font-weight:900;color:#f5f0e8;margin-bottom:12px;
           font-family:'Arial Black',Arial,sans-serif;">Careers at {name}</h2>
      <p style="font-size:15px;color:#888888;max-width:500px;">
        We are always looking for compassionate, dedicated care professionals to join our team in {city}, Maryland.
      </p>
    </div>
    <a href="#contact"
       style="background:transparent;border:2px solid #ECAA27;color:#ECAA27;padding:16px 36px;
              font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:2px;
              display:inline-block;font-family:'Arial Black',Arial,sans-serif;white-space:nowrap;">
      View Openings &rarr;
    </a>
  </div>
</section>

<!-- CONTACT -->
<section id="contact" style="background:#111111;padding:80px 60px;border-left:4px solid #ECAA27;">
  <div style="max-width:700px;">
    <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
         letter-spacing:3px;margin-bottom:16px;font-family:'Arial Black',Arial,sans-serif;">GET IN TOUCH</div>
    <h2 style="font-size:42px;font-weight:900;color:#f5f0e8;margin-bottom:16px;
         font-family:'Arial Black',Arial,sans-serif;">Ready to Get Started?</h2>
    <p style="font-size:16px;color:#888888;margin-bottom:8px;">{city}, Maryland</p>
    {phone_html}
    {email_html}
    <a href="#"
       style="display:inline-block;background:#ECAA27;color:#111111;padding:16px 40px;
              font-size:13px;font-weight:900;text-transform:uppercase;letter-spacing:2px;margin-top:16px;
              clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));
              font-family:'Arial Black',Arial,sans-serif;">
      Contact Us Today
    </a>
    <p style="font-size:13px;color:#555555;margin-top:24px;">Serving {city} and surrounding Maryland communities.</p>
  </div>
</section>

<!-- FOOTER -->
<footer style="background:#0a0a0a;padding:30px 60px;display:flex;
     justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;">
  <span style="font-size:12px;color:#444444;">&copy; 2026 {name} &middot; Licensed by Maryland OHCQ</span>
  <span style="font-size:12px;color:#444444;">Demo created by Proles HHC &middot; prolesconsulting.com</span>
</footer>

</body>
</html>"""


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    agencies = load_agencies()
    rows = ''
    for i in range(1, 51):
        a = agencies.get(i, {})
        name  = a.get('name')  or '—'
        atype = a.get('type')  or '—'
        city  = a.get('city')  or '—'
        phone = a.get('phone') or '—'
        email = a.get('email') or '—'
        sdat  = (a.get('sdat_status') or '').strip().upper()

        badge_html = ''
        if sdat and sdat in SDAT_BADGE:
            bg, fg = SDAT_BADGE[sdat]
            badge_html = (
                f'<span style="background:{bg};color:{fg};font-size:9px;'
                f'font-weight:900;padding:2px 7px;margin-left:7px;'
                f'letter-spacing:0.5px;text-transform:uppercase;">{sdat}</span>'
            )

        row_style = ' style="opacity:0.4;"' if sdat == 'FORFEITED' else ''

        if sdat in SDAT_TARGETABLE:
            action_html = (
                f'<a href="/proposal/{i}" class="btn btn-gold">Proposal</a>'
                f'<a href="/email/{i}" class="btn btn-red">Email</a>'
            )
        elif sdat == 'FORFEITED':
            action_html = '<span style="color:var(--text3);font-size:11px;">Forfeited</span>'
        else:
            action_html = f'<a href="/email/{i}" class="btn btn-red">Email</a>'

        rows += f"""<tr{row_style} onclick="openModal({i},'{name.replace("'","\\'")}','{atype}','{city}','{phone}','{email}','{sdat}')" style="cursor:pointer;">
          <td>{i}</td>
          <td><a href="/proposal/{i}" style="color:var(--gold);font-weight:bold;" onclick="event.stopPropagation();">{name}</a>{badge_html}</td>
          <td>{atype}</td><td>{city}</td><td>{phone}</td><td>{email}</td>
          <td onclick="event.stopPropagation();">{action_html}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Digitalization Outreach &mdash; Follow-Up 50</title>
<style>{INDEX_CSS}</style>
</head>
<body>

<div class="top-banner">
  <div class="banner-left">
    <div class="banner-eyebrow">Proles Home Healthcare Consultants &bull; Maryland</div>
    <div class="banner-title">Digitalization <span>Outreach</span></div>
    <div class="banner-sub">SDAT Verified &bull; Follow-Up 50 &bull; April 2026</div>
  </div>
  <div class="banner-right">
    <div class="banner-stat">
      <div class="stat-num">50</div>
      <div class="stat-label">Agencies</div>
    </div>
    <div class="banner-stat">
      <div class="stat-num">41</div>
      <div class="stat-label">Active</div>
    </div>
    <div class="banner-stat">
      <div class="stat-num">0</div>
      <div class="stat-label">Forfeited</div>
    </div>
    <img src="/static/logo.png" class="banner-logo" alt="Proles HHC">
  </div>
</div>
<div class="accent-bar"></div>

<div class="content">
<table>
  <thead><tr>
    <th>#</th><th>Agency Name</th><th>Type</th><th>City</th><th>Phone</th><th>Email</th><th>Actions</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>
</div>

<div class="modal-overlay" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal-box">
    <div class="modal-header">
      <div>
        <div class="modal-agency" id="m-name"></div>
        <div class="modal-type" id="m-type"></div>
      </div>
      <button class="modal-close" onclick="closeModal()">&times;</button>
    </div>
    <div class="modal-body">
      <div class="modal-sdat" id="m-sdat"></div>
      <div class="modal-stat"><strong>City:</strong> <span id="m-city"></span></div>
      <div class="modal-stat"><strong>Phone:</strong> <span id="m-phone"></span></div>
      <div class="modal-stat"><strong>Email:</strong> <span id="m-email"></span></div>
    </div>
    <div class="modal-actions">
      <a id="m-proposal" href="#" class="modal-btn btn-gold">View Proposal</a>
      <a id="m-email-btn" href="#" class="modal-btn btn-red">Email Template</a>
      <button id="m-draft" class="modal-btn btn-red" onclick="genDraftModal()">Generate Gmail Draft</button>
      <a id="m-demo" href="#" class="modal-btn btn-demo" target="_blank">View Demo Site</a>
    </div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
var _modalRow = null;
function openModal(n, name, type, city, phone, email, sdat) {{
  _modalRow = n;
  document.getElementById('m-name').textContent    = name;
  document.getElementById('m-type').textContent    = type;
  document.getElementById('m-city').textContent    = city;
  document.getElementById('m-phone').textContent   = phone;
  document.getElementById('m-email').textContent   = email;
  document.getElementById('m-proposal').href       = '/proposal/' + n;
  document.getElementById('m-email-btn').href      = '/email/' + n;
  document.getElementById('m-demo').href           = '/demo/' + n;
  var sdatEl = document.getElementById('m-sdat');
  var sdatColors = {{ACTIVE:'#1a4d1a,#5aff5a',REVIVED:'#1a1a4d,#5a8aff',INCORPORATED:'#3d2a00,#ECAA27',FORFEITED:'#4d1a1a,#ff5a5a'}};
  if (sdat && sdatColors[sdat]) {{
    var parts = sdatColors[sdat].split(',');
    sdatEl.style.background = parts[0]; sdatEl.style.color = parts[1]; sdatEl.textContent = sdat;
  }} else {{
    sdatEl.textContent = '';
  }}
  document.getElementById('modal').classList.add('open');
}}
function closeModal() {{ document.getElementById('modal').classList.remove('open'); _modalRow = null; }}
async function genDraftModal() {{
  if (!_modalRow) return;
  var btn = document.getElementById('m-draft');
  btn.textContent = 'Generating...'; btn.disabled = true;
  try {{
    var res = await fetch('/generate-draft/' + _modalRow);
    var data = await res.json();
    if (data.error) throw new Error(data.error);
    showToast('Draft created in Gmail — PDF attached');
    setTimeout(() => window.open(data.gmail_url, '_blank'), 500);
    closeModal();
  }} catch(e) {{ showToast('Error: ' + e.message); }}
  finally {{ btn.textContent = 'Generate Gmail Draft'; btn.disabled = false; }}
}}
function showToast(msg) {{
  var t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 4000);
}}
document.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') closeModal(); }});
</script>
</body>
</html>"""
    return Response(html, mimetype='text/html')


@app.route('/proposal/<int:row_num>')
def proposal(row_num):
    agencies = load_agencies()
    agency = agencies.get(row_num)
    if not agency:
        abort(404)
    return Response(build_proposal(agency, row_num), mimetype='text/html')


@app.route('/email/<int:row_num>')
def email_page(row_num):
    agencies = load_agencies()
    agency = agencies.get(row_num)
    if not agency:
        abort(404)

    name  = agency.get('name')  or 'Agency'
    email = agency.get('email') or ''
    phone = agency.get('phone') or ''
    subject = f"A Custom Website for {name} — Built in 3 Weeks | Proles Home Healthcare Consultants"
    body_html = build_email_html(agency, row_num)
    body_text = build_email_text(agency, row_num)

    if email:
        mailto = (
            f"mailto:{email}?subject={urllib.parse.quote(subject)}"
            f"&body={urllib.parse.quote(body_text)}"
        )
        contact_block = f"""<div class="mailto-bar">
  <div class="mailto-info">
    <strong>To:</strong> {email}<br>
    <strong>Subject:</strong> {subject}
  </div>
  <div class="btn-row">
    <a href="{mailto}" class="btn btn-gold">Open in Email Client</a>
    <button onclick="generateDraft()" class="btn btn-red">Generate Gmail Draft</button>
    <button onclick="copyBody()" class="btn btn-gold">Copy Body</button>
  </div>
</div>"""
    else:
        contact_block = f"""<div class="no-email-note">No email on file &mdash; call {phone}</div>
<div style="margin-top:12px;">
  <button onclick="generateDraft()" class="btn btn-gold">Generate Gmail Draft (No To)</button>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Email Preview &mdash; {name}</title>
<style>{EMAIL_CSS}</style>
</head>
<body>
<div class="container">
  <div class="page-title">Email Preview</div>
  <div class="subtitle">
    For {name} &nbsp;&bull;&nbsp;
    <a href="/proposal/{row_num}">Back to Proposal</a>
  </div>

  <div class="subject-box">
    <div class="subject-label">Subject Line</div>
    <div class="subject-line">{subject}</div>
  </div>

  <div class="email-card">
    <div class="email-card-header">
      <span class="email-brand">PROLES <span>HOME HEALTHCARE CONSULTANTS</span></span>
      <span style="color:var(--text2);font-size:11px;text-transform:uppercase;letter-spacing:1px;">Project Management &amp; Digital Solutions</span>
    </div>
    <div class="email-body">
      {body_html}
    </div>
  </div>

  {contact_block}
</div>
<div class="toast" id="toast"></div>
<script>
const bodyText = {json.dumps(body_text)};
async function generateDraft() {{
  const btns = document.querySelectorAll('.btn-red');
  btns.forEach(b => {{ b.textContent = 'Generating...'; b.disabled = true; }});
  try {{
    const res = await fetch('/generate-draft/{row_num}');
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    showToast('Draft created in Gmail — PDF attached');
    setTimeout(() => window.open(data.gmail_url, '_blank'), 500);
  }} catch(e) {{
    showToast('Error: ' + e.message);
  }} finally {{
    btns.forEach(b => {{ b.textContent = 'Generate Gmail Draft'; b.disabled = false; }});
  }}
}}
function copyBody() {{
  navigator.clipboard.writeText(bodyText).then(() => {{
    showToast('Email body copied!');
  }});
}}
function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 4000);
}}
</script>
</body>
</html>"""
    return Response(html, mimetype='text/html')


@app.route('/generate-draft/<int:row_num>')
def generate_draft(row_num):
    agencies = load_agencies()
    agency = agencies.get(row_num)
    if not agency:
        return jsonify({'error': 'Agency not found'}), 404

    name  = agency.get('name') or 'Agency'
    email = agency.get('email') or ''

    # 1. Generate PDF via WeasyPrint
    pdf_bytes = None
    try:
        from weasyprint import HTML, CSS
        print(f'[pdf] building HTML for {name}...')
        proposal_html = build_proposal_for_pdf(agency, row_num)
        print(f'[pdf] HTML len={len(proposal_html)}, calling WeasyPrint...')
        pdf_bytes = HTML(string=proposal_html, base_url=None).write_pdf(
            stylesheets=[CSS(string='@page { size: Letter; margin: 0.5in 0.6in; }')]
        )
        print(f'[pdf] done, size={len(pdf_bytes)} bytes')
    except Exception as e:
        import traceback
        print(f'[pdf] error: {e}')
        print(traceback.format_exc())

    # 2. Build Gmail draft
    gmail = get_gmail_service()
    if not gmail:
        return jsonify({'error': 'Gmail not configured — set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN'}), 503

    subject = f"A Custom Website for {name} — Built in 3 Weeks | Proles Home Healthcare Consultants"

    msg = MIMEMultipart('mixed')
    msg['From'] = GMAIL_USER
    if email:
        msg['To'] = email
    msg['Subject'] = subject

    # Attach HTML + text body
    body_alt = MIMEMultipart('alternative')
    body_alt.attach(MIMEText(build_email_text(agency, row_num), 'plain'))
    body_alt.attach(MIMEText(build_email_html(agency, row_num), 'html'))
    msg.attach(body_alt)

    # Attach PDF if we got one
    if pdf_bytes:
        pdf_part = MIMEBase('application', 'pdf')
        pdf_part.set_payload(pdf_bytes)
        encoders.encode_base64(pdf_part)
        safe_name = slugify(name)
        pdf_part.add_header('Content-Disposition', 'attachment', filename=f'{safe_name}_proposal.pdf')
        msg.attach(pdf_part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        draft = gmail.users().drafts().create(
            userId='me',
            body={'message': {'raw': raw}}
        ).execute()
        draft_id = draft.get('id', '')
        return jsonify({'draft_id': draft_id, 'gmail_url': 'https://mail.google.com/mail/#drafts'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Booking calendar ───────────────────────────────────────────────────────────

def _get_weekdays(count=14):
    days = []
    d = datetime.date.today()
    while len(days) < count:
        if d.weekday() < 5:  # Mon–Fri
            days.append(d)
        d += datetime.timedelta(days=1)
    return days


def _slot_labels():
    slots = []
    t = datetime.time(9, 0)
    while t < datetime.time(17, 0):
        slots.append(t.strftime('%-I:%M %p') if os.name != 'nt' else t.strftime('%#I:%M %p'))
        h, m = divmod(t.hour * 60 + t.minute + 15, 60)
        t = datetime.time(h, m)
    return slots


def _fake_busy_map(days):
    """Returns {date_iso: list_of_busy_slot_indices} — deterministic per date."""
    import hashlib
    result = {}
    for d in days:
        h = int(hashlib.md5(d.isoformat().encode()).hexdigest()[:8], 16)
        busy = set()
        for i in range(32):  # 32 slots from 9:00 to 16:45
            h = (h * 1664525 + 1013904223) & 0xFFFFFFFF
            # Gray out ~45% of slots, protect first 2 and last 2 slots of day
            if i >= 2 and i <= 29 and (h % 100) < 45:
                busy.add(i)
        result[d.isoformat()] = sorted(busy)
    return result


@app.route('/availability')
def availability():
    start = request.args.get('start')
    end = request.args.get('end')
    if not start or not end:
        return jsonify({'busy': []})
    creds = _build_creds()
    if not creds:
        return jsonify({'busy': []})
    try:
        from googleapiclient.discovery import build as gcal_build
        from dateutil import tz as dateutil_tz
        et = dateutil_tz.gettz('America/New_York')
        start_dt = datetime.datetime.strptime(start, '%Y-%m-%d').replace(
            hour=0, minute=0, second=0, tzinfo=et)
        end_dt = datetime.datetime.strptime(end, '%Y-%m-%d').replace(
            hour=23, minute=59, second=59, tzinfo=et)
        cal = gcal_build('calendar', 'v3', credentials=creds)
        result = cal.freebusy().query(body={
            'timeMin': start_dt.isoformat(),
            'timeMax': end_dt.isoformat(),
            'timeZone': 'America/New_York',
            'items': [{'id': 'primary'}],
        }).execute()
        busy = result.get('calendars', {}).get('primary', {}).get('busy', [])
        return jsonify({'busy': busy})
    except Exception as e:
        print(f'[availability] {e}')
        return jsonify({'busy': []})


@app.route('/book/<int:row_num>')
def book(row_num):
    import json as _json, hashlib

    agencies = load_agencies()
    agency   = agencies.get(row_num)
    name     = (agency.get('name') if agency else '') or 'Your Agency'

    # Next 14 weekdays
    days = _get_weekdays(14)

    # Date options for the dropdown
    date_options_html = '<option value="">-- Select a date --</option>'
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    dow_names   = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    for d in days:
        dow   = dow_names[d.weekday()]
        mon   = month_names[d.month - 1]
        label = f"{dow}, {mon} {d.day}"
        date_options_html += f'<option value="{d.isoformat()}">{label}</option>'

    # Build fake-busy slots per day — {{date_iso: [slot_indices]}}
    slot_labels = _slot_labels()
    busy_map = {}
    for d in days:
        h = int(hashlib.md5(d.isoformat().encode()).hexdigest()[:8], 16)
        busy = []
        for i in range(len(slot_labels)):
            h = (h * 1664525 + 1013904223) & 0xFFFFFFFF
            if i >= 2 and i <= len(slot_labels) - 3 and (h % 100) < 45:
                busy.append(i)
        busy_map[d.isoformat()] = busy

    slot_labels_json = _json.dumps(slot_labels)
    busy_map_json    = _json.dumps(busy_map)
    name_json        = _json.dumps(name)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Schedule a Call &mdash; {name}</title>
<style>{BOOK_CSS}</style>
</head>
<body>
<div class="card" id="bookCard">
  <div class="card-eyebrow">Proles Home Healthcare Consultants</div>
  <div class="card-title">Book a <span>15-Min</span> Call</div>
  <div class="card-sub">Re: {name}</div>
  <div class="divider"></div>

  <div class="field-row three">
    <div>
      <label class="field-label">Name</label>
      <input type="text" id="inp-name" placeholder="Jane Smith">
    </div>
    <div>
      <label class="field-label">Email</label>
      <input type="email" id="inp-email" placeholder="jane@agency.com">
    </div>
    <div>
      <label class="field-label">Phone</label>
      <input type="tel" id="inp-phone" placeholder="(410) 555-0100">
    </div>
  </div>

  <label class="field-label" style="margin-bottom:8px;">How You'd Like to Meet</label>
  <div class="meet-row" style="margin-bottom:20px;">
    <div class="meet-pill active" id="pill-meet" onclick="setMeet('Google Meet')">&#127760; Google Meet</div>
    <div class="meet-pill"        id="pill-zoom" onclick="setMeet('Zoom')">&#128249; Zoom</div>
  </div>

  <div class="field-row" style="margin-bottom:14px;">
    <div>
      <label class="field-label">Select a Date</label>
      <select id="date-sel" onchange="onDateChange(this.value)">
        {date_options_html}
      </select>
    </div>
    <div>
      <label class="field-label">Preferred Contact</label>
      <select id="contact-pref-sel" name="contact_pref">
        <option value="Email">Email</option>
        <option value="Phone">Phone</option>
        <option value="Both">Both</option>
      </select>
    </div>
  </div>

  <div class="slot-row field-row single" id="slot-row" style="display:none;">
    <div>
      <label class="field-label">Select a Time</label>
      <select id="time-sel" onchange="onTimeChange()">
        <option value="">-- Select a time --</option>
      </select>
    </div>
  </div>

  <button class="submit-btn" id="submit-btn" disabled onclick="submitBooking()">
    Confirm Booking
  </button>

  <div class="success-card" id="success-card">
    <div class="success-icon">&#10003;</div>
    <h2>You're Booked!</h2>
    <p id="success-detail"></p>
    <p style="margin-top:10px;">We'll send confirmation to your email.</p>
  </div>
</div>

<script>
const SLOT_LABELS  = {slot_labels_json};
const BUSY_MAP     = {busy_map_json};
let selectedMeet   = 'Google Meet';
let selectedDate   = null;
let selectedTime   = null;

function setMeet(t) {{
  selectedMeet = t;
  document.getElementById('pill-meet').classList.toggle('active', t === 'Google Meet');
  document.getElementById('pill-zoom').classList.toggle('active', t === 'Zoom');
}}

function onDateChange(iso) {{
  selectedDate = iso || null;
  selectedTime = null;
  const row  = document.getElementById('slot-row');
  const sel  = document.getElementById('time-sel');
  if (!iso) {{ row.style.display = 'none'; checkSubmit(); return; }}
  const busy = new Set(BUSY_MAP[iso] || []);
  sel.innerHTML = '<option value="">-- Select a time --</option>';
  SLOT_LABELS.forEach(function(lbl, i) {{
    const opt = document.createElement('option');
    opt.value = lbl;
    if (busy.has(i)) {{
      opt.disabled = true;
      opt.textContent = lbl + '  (Unavailable)';
      opt.className = 'unavailable';
    }} else {{
      opt.textContent = lbl;
    }}
    sel.appendChild(opt);
  }});
  row.style.display = '';
  checkSubmit();
}}

function onTimeChange() {{
  selectedTime = document.getElementById('time-sel').value || null;
  checkSubmit();
}}

function checkSubmit() {{
  const ok = !!(selectedDate && selectedTime &&
    document.getElementById('inp-name').value.trim() &&
    document.getElementById('inp-email').value.trim());
  document.getElementById('submit-btn').disabled = !ok;
}}

document.addEventListener('input', function(e) {{
  if (['inp-name','inp-email'].includes(e.target.id)) checkSubmit();
}});

async function submitBooking() {{
  const btn = document.getElementById('submit-btn');
  btn.disabled = true; btn.textContent = 'Confirming...';
  const payload = {{
    agency_num: {row_num},
    agency_name: {name_json},
    contact_name:  document.getElementById('inp-name').value.trim(),
    contact_email: document.getElementById('inp-email').value.trim(),
    contact_phone: document.getElementById('inp-phone').value.trim(),
    meeting_type:  selectedMeet,
    date: selectedDate,
    time: selectedTime
  }};
  try {{
    await fetch('/book-confirm', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify(payload)
    }});
  }} catch(e) {{}}
  document.getElementById('bookCard').querySelector('.card-eyebrow').style.display = 'none';
  document.getElementById('bookCard').querySelector('.card-title').style.display   = 'none';
  document.getElementById('bookCard').querySelector('.card-sub').style.display     = 'none';
  document.getElementById('bookCard').querySelector('.divider').style.display      = 'none';
  document.querySelectorAll('.field-row, .meet-row, .slot-row, #submit-btn, .field-label').forEach(function(el) {{
    el.style.display = 'none';
  }});
  const s = document.getElementById('success-card');
  s.style.display = 'block';
  document.getElementById('success-detail').textContent =
    payload.contact_name + ' · ' + payload.date + ' at ' + payload.time + ' · ' + payload.meeting_type;
}}
</script>
</body>
</html>"""
    return Response(html, mimetype='text/html')


@app.route('/book-confirm', methods=['POST'])
def book_confirm():
    data = request.get_json(silent=True) or {}
    print(f"[booking] {data.get('contact_name')} — {data.get('date')} {data.get('time')} — {data.get('meeting_type')}")
    return jsonify({'status': 'ok'})


@app.route('/confirm-booking', methods=['POST'])
def confirm_booking():
    data = request.get_json(force=True)
    date           = data.get('date', '')
    time_str       = data.get('time', '')
    agency_name    = data.get('agency_name', 'Agency')
    agency_num     = data.get('agency_num', '')
    contact_name   = data.get('contact_name', '')
    contact_email  = data.get('contact_email', '')
    contact_phone  = data.get('contact_phone', '')
    contact_co     = data.get('contact_company', '')
    contact_method = data.get('contact_method', 'Email')
    meeting_type   = data.get('meeting_type', 'Google Meet')

    meet_link = None
    cal = get_calendar_service()
    if cal and meeting_type == 'Google Meet':
        try:
            # Parse datetime — date is YYYY-MM-DD, time_str is like "9:00 AM"
            dt_str = f"{date} {time_str}"
            import dateutil.parser
            start_dt = dateutil.parser.parse(dt_str)
            end_dt   = start_dt + datetime.timedelta(minutes=15)
            tz = 'America/New_York'
            event = {
                'summary': f'Proles HHC Call — {agency_name}',
                'description': (
                    f"Booking from {contact_name} ({contact_email})\n"
                    f"Agency: {agency_name}\nPhone: {contact_phone}\n"
                    f"Preferred contact: {contact_method}"
                ),
                'start': {'dateTime': start_dt.isoformat(), 'timeZone': tz},
                'end':   {'dateTime': end_dt.isoformat(),   'timeZone': tz},
                'attendees': [
                    {'email': GMAIL_USER},
                    {'email': contact_email},
                ],
                'conferenceData': {
                    'createRequest': {'requestId': f"booking-{agency_num}-{date}-{time_str.replace(' ','')}", 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}
                },
            }
            created = cal.events().insert(
                calendarId='primary', body=event,
                conferenceDataVersion=1, sendUpdates='all'
            ).execute()
            meet_link = created.get('hangoutLink')
        except Exception as e:
            print(f'[calendar event] {e}')

    # Log booking regardless
    booking_record = {
        'date': date, 'time': time_str, 'agency_name': agency_name,
        'agency_num': agency_num, 'contact_name': contact_name,
        'contact_email': contact_email, 'contact_phone': contact_phone,
        'contact_company': contact_co, 'contact_method': contact_method,
        'meet_link': meet_link, 'logged_at': datetime.datetime.utcnow().isoformat(),
    }
    try:
        existing = []
        if os.path.exists(BOOKINGS_PATH):
            with open(BOOKINGS_PATH, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        existing.append(booking_record)
        with open(BOOKINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        print(f'[bookings.json] {e}')

    # Send confirmation emails
    gmail = get_gmail_service()
    if meeting_type == 'Zoom':
        meet_text = 'Zoom meeting — a link will be sent to your email shortly.'
    else:
        meet_text = meet_link or 'Google Meet link will be sent shortly.'

    internal_subject = f"[Booking] {contact_name} — {agency_name} — {date} {time_str} ({meeting_type})"
    internal_body = (
        f"New booking received.\n\n"
        f"Date/Time: {date} at {time_str}\n"
        f"Agency: {agency_name} (#{agency_num})\n"
        f"Contact: {contact_name}\n"
        f"Email: {contact_email}\n"
        f"Phone: {contact_phone}\n"
        f"Company: {contact_co}\n"
        f"Preferred contact: {contact_method}\n\n"
        f"Google Meet: {meet_text}"
    )

    prospect_subject = f"Your {meeting_type} Call with Proles Home Healthcare Consultants — {date} at {time_str}"
    prospect_body = (
        f"Hi {contact_name},\n\n"
        f"Your 15-minute {meeting_type} call is confirmed!\n\n"
        f"Date: {date}\nTime: {time_str} (Eastern)\nMeeting type: {meeting_type}\n\n"
        f"Meeting link: {meet_text}\n\n"
        f"We look forward to speaking with you about {agency_name}.\n\n"
        f"Best regards,\nAlex Thuku\nProles Home Healthcare Consultants\n"
        f"{COMPANY_URL} | amthuku@gmail.com | (434) 429-9296"
    )

    def _send_simple(to_addr, subj, body):
        m = MIMEText(body, 'plain')
        m['From'] = GMAIL_USER
        m['To']   = to_addr
        m['Subject'] = subj
        raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
        gmail.users().messages().send(userId='me', body={'raw': raw}).execute()

    if gmail:
        try:
            _send_simple(GMAIL_USER, internal_subject, internal_body)
        except Exception as e:
            print(f'[internal email] {e}')
        if contact_email:
            try:
                _send_simple(contact_email, prospect_subject, prospect_body)
            except Exception as e:
                print(f'[prospect email] {e}')

    return jsonify({'success': True, 'meet_link': meet_link})


@app.route('/overview/<int:row_num>')
def overview_page(row_num):
    agencies = load_agencies()
    agency = agencies.get(row_num)
    if not agency:
        abort(404)
    return Response(build_overview(agency, row_num), mimetype='text/html')


@app.route('/demo/<int:row_num>')
def demo_site(row_num):
    agencies = load_agencies()
    agency = agencies.get(row_num)
    if not agency:
        abort(404)
    return Response(build_demo(agency, row_num), mimetype='text/html')


@app.route('/client-site/style.css')
def client_site_css():
    css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'ioi_templates', 'style.css')
    css_path = os.path.normpath(css_path)
    try:
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()
    except FileNotFoundError:
        css = ''
    return Response(css, mimetype='text/css')

@app.route('/client-site/<int:n>/')
@app.route('/client-site/<int:n>')
def client_site_index(n):
    agencies = load_agencies()
    agency   = agencies.get(n) or {}
    html = build_client_site(_IOI_INDEX, agency, n)
    return Response(html, mimetype='text/html')

@app.route('/client-site/<int:n>/services')
def client_site_services(n):
    agencies = load_agencies()
    agency   = agencies.get(n) or {}
    html = build_client_site(_IOI_SERVICES, agency, n)
    return Response(html, mimetype='text/html')

@app.route('/client-site/<int:n>/about')
def client_site_about(n):
    agencies = load_agencies()
    agency   = agencies.get(n) or {}
    html = build_client_site(_IOI_ABOUT, agency, n)
    return Response(html, mimetype='text/html')

@app.route('/client-site/<int:n>/contact')
def client_site_contact(n):
    agencies = load_agencies()
    agency   = agencies.get(n) or {}
    html = build_client_site(_IOI_CONTACT, agency, n)
    return Response(html, mimetype='text/html')


if __name__ == '__main__':
    print(f"Proles Home Healthcare Consultants Proposal Server — http://0.0.0.0:{PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
