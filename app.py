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
  body { font-family: Arial, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; padding: 30px 20px; }
  .container { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 26px; font-weight: 900; text-transform: uppercase; letter-spacing: -0.5px; margin-bottom: 4px; }
  h1 span { color: var(--gold); }
  .sub { font-size: 11px; color: var(--text2); letter-spacing: 2px; text-transform: uppercase; margin-bottom: 28px; }
  .calendar-grid { display: grid; grid-template-columns: repeat(5,1fr); gap: 10px; margin-bottom: 30px; }
  .day-col { display: flex; flex-direction: column; gap: 4px; }
  .day-header {
    background: var(--bg2); border-bottom: 2px solid var(--gold);
    padding: 8px 4px; text-align: center; font-size: 9px; font-weight: 900;
    text-transform: uppercase; letter-spacing: 1.5px;
  }
  .day-date { color: var(--gold); font-size: 18px; font-weight: 900; display: block; }
  .day-name  { color: var(--text2); }
  .time-slot {
    background: var(--bg2); border: 1px solid var(--bg3); padding: 5px 2px;
    text-align: center; font-size: 10px; color: var(--text2); cursor: pointer;
    letter-spacing: 0.5px; transition: all 0.12s;
  }
  .time-slot:hover { background: var(--gold); color: #111; border-color: var(--gold); font-weight: 900; }
  .time-slot.selected { background: var(--red); color: var(--text); border-color: var(--red); font-weight: 900; }
  .time-slot.unavailable { background: var(--bg3); color: var(--text3); cursor: not-allowed; text-decoration: line-through; }
  .time-slot.unavailable:hover { background: var(--bg3); color: var(--text3); border-color: var(--bg3); font-weight: normal; }
  .form-section { background: var(--bg2); border: 2px solid var(--gold); padding: 28px; display: none; margin-top: 10px; }
  .form-section.visible { display: block; }
  .form-section h2 { font-size: 18px; font-weight: 900; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .selected-time { font-size: 13px; color: var(--gold); font-weight: 900; margin-bottom: 20px; }
  .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .form-group { display: flex; flex-direction: column; gap: 6px; }
  .form-group label { font-size: 9px; font-weight: 900; text-transform: uppercase; letter-spacing: 1.5px; color: var(--text2); }
  .form-group input, .form-group select {
    background: var(--bg); border: 1px solid var(--bg3); color: var(--text);
    padding: 10px 12px; font-size: 13px; font-family: Arial, sans-serif; outline: none;
  }
  .form-group input:focus, .form-group select:focus { border-color: var(--gold); }
  .form-group select option { background: var(--bg); }
  .submit-btn {
    background: var(--gold); color: #111; padding: 14px 36px; border: none;
    font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: 2px;
    cursor: pointer; font-family: Arial, sans-serif; margin-top: 8px;
    clip-path: polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));
  }
  .submit-btn:hover { background: var(--gold-light); }
  .success-msg { background: var(--bg2); border: 2px solid var(--gold); padding: 30px; text-align: center; display: none; }
  .success-msg.show { display: block; }
  .success-msg h2 { color: var(--gold); font-size: 22px; font-weight: 900; margin-bottom: 10px; text-transform: uppercase; }
  .success-msg p { color: var(--text2); font-size: 14px; line-height: 1.7; }
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

    <p style="margin-bottom:16px;">We recently built a complete digital platform for another Maryland home health agency. See it live:
    <a href="{EXAMPLE_HREF}" style="color:#8a0a0a;font-weight:bold;">{EXAMPLE_DISPLAY}</a> &mdash;
    a branded homepage, staff portal, appointment system, and contact forms. We delivered it in under three weeks.</p>

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

  <div style="background:#111111;padding:16px 28px;border-top:1px solid #2a2a2a;">
    <div style="font-size:12px;color:#888888;line-height:1.7;">
      <strong style="color:#f5f0e8;">Alex Thuku</strong><br>
      Proles Home Healthcare Consultants<br>
      <a href="https://{COMPANY_URL}" style="color:#ECAA27;">{COMPANY_URL}</a> |
      amthuku@gmail.com | (443) 374-2931 | Baltimore, MD
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
        f"See a live example: {EXAMPLE_DISPLAY} ({EXAMPLE_HREF})\n\n"
        f"See the attached one-page proposal PDF for full details and pricing.\n\n"
        f"Schedule a free 15-minute call: {book_url}\n\n"
        f"Proles Home Healthcare Consultants | {COMPANY_URL}\n\n"
        f"Best regards,\n"
        f"Alex Thuku\n"
        f"Proles Home Healthcare Consultants | {COMPANY_URL}\n"
        f"amthuku@gmail.com | (443) 374-2931 | Baltimore, MD"
    )


# ── Proposal HTML ─────────────────────────────────────────────────────────────

def build_proposal(agency, n):
    name = agency.get('name') or 'Agency'
    atype = agency.get('type') or ''
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
      <div class="section-label label-gold">Live Example</div>
      <div class="example-box">
        <a class="example-url" href="{EXAMPLE_HREF}">{EXAMPLE_DISPLAY}</a>
        <div class="example-desc">
          Built for a Maryland home health agency &mdash; full branded site, staff portal, appointment system, and contact forms. Exactly what we&rsquo;ll build for you.
        </div>
        <span class="example-badge">Live in 3 weeks</span>
      </div>
    </div>
  </div>

  <div class="section">
    <span class="section-label label-gold">YOUR DEMO SITE</span>
    <div class="example-box">
      <a class="example-url" href="{RAILWAY_URL}/demo/{n}" target="_blank">{RAILWAY_URL}/demo/{n}</a>
      <div class="example-desc">This preview was built specifically for <strong style="color:#ECAA27">{name}</strong>. Click the link above to see exactly what your website would look like &mdash; built and ready within 3 weeks.</div>
      <span class="example-badge">PERSONALIZED FOR YOU</span>
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
      (443) 374-2931<br>
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


def build_demo(agency, n):
    name   = agency.get('name')  or 'Agency'
    atype  = agency.get('type')  or ''
    city   = agency.get('city')  or 'Maryland'
    phone  = agency.get('phone') or ''
    phrase = type_phrase(atype)
    services = demo_services(atype)

    t = atype.lower()
    if 'home health' in t:
        svc_type = 'home health'
    elif 'residential' in t or 'rsa' in t or 'dda' in t:
        svc_type = 'residential care'
    elif 'day care' in t or 'adult day' in t:
        svc_type = 'adult day care'
    else:
        svc_type = 'care'

    cards_html = ''
    for idx, (svc_name, svc_desc) in enumerate(services):
        num_str = f'0{idx + 1}'
        cards_html += (
            f'<div style="background:#111111;border:1px solid #2a2a2a;border-top:3px solid #ECAA27;padding:28px;">'
            f'<div style="font-size:11px;font-weight:900;color:#ECAA27;letter-spacing:2px;margin-bottom:12px;">{num_str}</div>'
            f'<div style="font-size:18px;font-weight:900;color:#f5f0e8;margin-bottom:10px;">{svc_name}</div>'
            f'<div style="font-size:14px;color:#888888;line-height:1.6;">{svc_desc}</div>'
            f'</div>'
        )

    phone_html = ''
    if phone and phone != '—':
        phone_html = f'<div style="font-size:36px;font-weight:900;color:#ECAA27;margin:16px 0;">{phone}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{name} &mdash; Professional Care Services</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Arial, Helvetica, sans-serif; background: #111111; color: #f5f0e8; }}
a {{ text-decoration: none; }}
</style>
</head>
<body>

<div style="background:#ECAA27;color:#111111;font-size:10px;font-weight:900;text-transform:uppercase;
     letter-spacing:2px;text-align:center;padding:10px 20px;position:fixed;top:0;left:0;right:0;
     z-index:9999;height:38px;display:flex;align-items:center;justify-content:center;">
  <span>DEMO PREVIEW &mdash; Built for {name} by Proles HHC &mdash; Not a live website</span>
  <a href="{RAILWAY_URL}/proposal/{n}" target="_blank"
     style="position:absolute;right:20px;color:#8a0a0a;font-size:9px;font-weight:900;letter-spacing:1px;">
    VIEW PROPOSAL &rarr;
  </a>
</div>

<nav style="background:#111111;border-bottom:2px solid #ECAA27;position:sticky;top:38px;z-index:999;
     height:60px;display:flex;align-items:center;justify-content:space-between;padding:0 60px;">
  <div style="font-size:18px;font-weight:900;color:#ECAA27;">{name}</div>
  <div style="display:flex;gap:32px;">
    <a href="#services" style="color:#f5f0e8;font-size:14px;font-weight:600;"
       onmouseover="this.style.color='#ECAA27'" onmouseout="this.style.color='#f5f0e8'">Services</a>
    <a href="#about" style="color:#f5f0e8;font-size:14px;font-weight:600;"
       onmouseover="this.style.color='#ECAA27'" onmouseout="this.style.color='#f5f0e8'">About</a>
    <a href="#contact" style="color:#f5f0e8;font-size:14px;font-weight:600;"
       onmouseover="this.style.color='#ECAA27'" onmouseout="this.style.color='#f5f0e8'">Contact</a>
  </div>
</nav>

<section style="min-height:calc(100vh - 98px);background:#111111;padding:80px 60px;
     display:flex;align-items:center;clip-path:polygon(0 0,100% 0,88% 100%,0 100%);
     padding-right:calc(12% + 60px);">
  <div style="max-width:700px;">
    <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
         letter-spacing:3px;margin-bottom:20px;">{city}, Maryland &middot; {phrase}</div>
    <h1 style="font-size:56px;font-weight:900;color:#f5f0e8;line-height:1.1;
         margin-bottom:20px;letter-spacing:-1px;">{name}</h1>
    <p style="font-size:18px;color:#888888;line-height:1.6;margin-bottom:40px;">
      Providing professional {svc_type} services to families across {city} and surrounding Maryland communities.
    </p>
    <div style="display:flex;gap:16px;flex-wrap:wrap;">
      <a href="#contact" style="background:#ECAA27;color:#111111;padding:16px 32px;
         font-size:13px;font-weight:900;text-transform:uppercase;letter-spacing:2px;
         clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));">
        Request Services &rarr;
      </a>
      <a href="#services" style="background:transparent;border:2px solid #ECAA27;color:#ECAA27;
         padding:16px 32px;font-size:13px;font-weight:900;text-transform:uppercase;letter-spacing:2px;">
        Learn More
      </a>
    </div>
  </div>
</section>

<section id="services" style="background:#1a1a1a;padding:80px 60px;">
  <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
       letter-spacing:3px;margin-bottom:16px;">WHAT WE OFFER</div>
  <h2 style="font-size:36px;font-weight:900;color:#f5f0e8;margin-bottom:48px;">Our Services</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">{cards_html}</div>
</section>

<section id="about" style="background:#111111;padding:80px 60px;">
  <div style="font-size:11px;font-weight:900;color:#ECAA27;text-transform:uppercase;
       letter-spacing:3px;margin-bottom:16px;">WHY CHOOSE US</div>
  <h2 style="font-size:36px;font-weight:900;color:#f5f0e8;margin-bottom:48px;">Our Commitment</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:32px;">
    <div style="background:#1a1a1a;border:1px solid #2a2a2a;padding:32px;">
      <div style="font-size:28px;color:#ECAA27;margin-bottom:16px;">&#9733;</div>
      <div style="font-size:18px;font-weight:900;color:#f5f0e8;margin-bottom:12px;">Licensed &amp; Certified</div>
      <div style="font-size:14px;color:#888888;line-height:1.6;">Maryland OHCQ licensed and fully compliant. Your family&rsquo;s safety and trust is our highest priority.</div>
    </div>
    <div style="background:#1a1a1a;border:1px solid #2a2a2a;padding:32px;">
      <div style="font-size:28px;color:#ECAA27;margin-bottom:16px;">&#9670;</div>
      <div style="font-size:18px;font-weight:900;color:#f5f0e8;margin-bottom:12px;">Maryland Based</div>
      <div style="font-size:14px;color:#888888;line-height:1.6;">Rooted in the local community. We understand the unique needs of Maryland families and the resources available to them.</div>
    </div>
    <div style="background:#1a1a1a;border:1px solid #2a2a2a;padding:32px;">
      <div style="font-size:28px;color:#ECAA27;margin-bottom:16px;">&#9829;</div>
      <div style="font-size:18px;font-weight:900;color:#f5f0e8;margin-bottom:12px;">Personalized Care</div>
      <div style="font-size:14px;color:#888888;line-height:1.6;">Every client receives an individualized care plan tailored to their specific needs, goals, and family situation.</div>
    </div>
  </div>
</section>

<section id="contact" style="background:#1a1a1a;padding:80px 60px;border-left:4px solid #ECAA27;">
  <h2 style="font-size:36px;font-weight:900;color:#f5f0e8;margin-bottom:16px;">Ready to Get Started?</h2>
  <p style="font-size:16px;color:#888888;margin-bottom:24px;">{city}, Maryland</p>
  {phone_html}
  <a href="#" style="display:inline-block;background:#ECAA27;color:#111111;padding:16px 40px;
     font-size:13px;font-weight:900;text-transform:uppercase;letter-spacing:2px;margin-top:16px;
     clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));">
    Contact Us Today
  </a>
</section>

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
    agencies = load_agencies()
    agency = agencies.get(row_num)
    name = (agency.get('name') if agency else '') or 'Your Agency'

    weekdays = _get_weekdays(14)
    slot_labels = _slot_labels()

    day_cols_html = ''
    for day in weekdays:
        day_name = day.strftime('%a').upper()
        day_date = day.strftime('%-d') if os.name != 'nt' else day.strftime('%#d')
        month    = day.strftime('%b').upper()
        iso      = day.isoformat()
        t = datetime.time(9, 0)
        slots_html = ''
        for sl in slot_labels:
            slot_id = f"{iso}T{sl.replace(' ', '').replace(':', '')}"
            slot_iso = f"{iso}T{t.strftime('%H:%M:00')}-04:00"
            slots_html += f'<div class="time-slot" onclick="selectSlot(this,\'{iso}\',\'{sl}\')" data-slot="{slot_id}" data-iso="{slot_iso}">{sl}</div>\n'
            h, m = divmod(t.hour * 60 + t.minute + 15, 60)
            t = datetime.time(h, m)
        day_cols_html += f"""<div class="day-col">
  <div class="day-header">
    <span class="day-date">{day_date}</span>
    <span class="day-name">{day_name} {month}</span>
  </div>
  {slots_html}
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Schedule a Call &mdash; {name}</title>
<style>{BOOK_CSS}</style>
</head>
<body>
<div class="container">
  <h1>Schedule a <span>Free 15-Minute Call</span></h1>
  <div class="sub">With Proles Home Healthcare Consultants &bull; Re: {name}</div>

  <div class="calendar-grid">
    {day_cols_html}
  </div>

  <div class="form-section" id="contactForm">
    <h2>Your Details</h2>
    <div class="selected-time" id="selectedTime"></div>
    <form onsubmit="submitBooking(event)">
      <input type="hidden" id="chosenDate" name="date" value="">
      <input type="hidden" id="chosenTime" name="time" value="">
      <input type="hidden" name="agency_num" value="{row_num}">
      <input type="hidden" name="agency_name" value="{name}">
      <div class="form-row">
        <div class="form-group">
          <label>Full Name</label>
          <input type="text" name="contact_name" required placeholder="Jane Smith">
        </div>
        <div class="form-group">
          <label>Email</label>
          <input type="email" name="contact_email" required placeholder="jane@agency.com">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Phone</label>
          <input type="tel" name="contact_phone" placeholder="(410) 555-0100">
        </div>
        <div class="form-group">
          <label>Company / Agency</label>
          <input type="text" name="contact_company" placeholder="{name}">
        </div>
      </div>
      <div class="form-group" style="margin-bottom:20px;">
        <label>Preferred Contact Method</label>
        <select name="contact_method">
          <option value="Email">Email</option>
          <option value="Phone">Phone</option>
          <option value="Both">Both</option>
        </select>
      </div>
      <div class="form-group" style="margin-bottom:24px;">
        <label>Meeting Type</label>
        <div style="display:flex;gap:16px;margin-top:8px;">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:var(--text);font-weight:normal;letter-spacing:0;text-transform:none;">
            <input type="radio" name="meeting_type" value="Google Meet" checked
              style="accent-color:var(--gold);width:16px;height:16px;cursor:pointer;">
            <span style="display:flex;align-items:center;gap:6px;">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
              </svg>
              Google Meet
            </span>
          </label>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:var(--text);font-weight:normal;letter-spacing:0;text-transform:none;">
            <input type="radio" name="meeting_type" value="Zoom"
              style="accent-color:var(--gold);width:16px;height:16px;cursor:pointer;">
            <span style="display:flex;align-items:center;gap:6px;">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="#2D8CFF" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.25 15.75a.75.75 0 01-.75.75H7.5a.75.75 0 01-.75-.75V8.25A.75.75 0 017.5 7.5h9a.75.75 0 01.75.75v7.5zm2.25-1.5l-3-2.25V11l3-2.25v5.5z"/>
              </svg>
              Zoom
            </span>
          </label>
        </div>
      </div>
      <button type="submit" class="submit-btn">Confirm Booking</button>
    </form>
  </div>

  <div class="success-msg" id="successMsg">
    <h2>&#10003; Booking Confirmed!</h2>
    <p id="successDetail"></p>
    <p style="margin-top:12px;">Check your email for confirmation and meeting details.</p>
  </div>
</div>
<script>
let selectedSlotEl = null;
let busyPeriods = [];

async function loadAvailability() {{
  const slots = document.querySelectorAll('[data-iso]');
  if (!slots.length) return;
  const dates = [...new Set([...slots].map(s => s.dataset.iso.slice(0, 10)))].sort();
  const start = dates[0];
  const end = dates[dates.length - 1];
  try {{
    const res = await fetch('/availability?start=' + start + '&end=' + end);
    const data = await res.json();
    busyPeriods = (data.busy || []).map(b => ({{ start: new Date(b.start), end: new Date(b.end) }}));
    markUnavailableSlots();
  }} catch(e) {{
    console.warn('[availability]', e);
  }}
}}

function markUnavailableSlots() {{
  document.querySelectorAll('.time-slot').forEach(el => {{
    const iso = el.dataset.iso;
    if (!iso) return;
    const slotStart = new Date(iso);
    const slotEnd = new Date(slotStart.getTime() + 15 * 60000);
    const isBusy = busyPeriods.some(b => slotStart < b.end && slotEnd > b.start);
    if (isBusy) el.classList.add('unavailable');
  }});
}}

function selectSlot(el, date, time) {{
  if (el.classList.contains('unavailable')) return;
  if (selectedSlotEl) selectedSlotEl.classList.remove('selected');
  el.classList.add('selected');
  selectedSlotEl = el;
  document.getElementById('chosenDate').value = date;
  document.getElementById('chosenTime').value = time;
  document.getElementById('selectedTime').textContent = date + ' at ' + time;
  const form = document.getElementById('contactForm');
  form.classList.add('visible');
  form.scrollIntoView({{behavior:'smooth', block:'start'}});
}}
async function submitBooking(e) {{
  e.preventDefault();
  const btn = e.target.querySelector('button[type=submit]');
  btn.textContent = 'Submitting...'; btn.disabled = true;
  const data = Object.fromEntries(new FormData(e.target));
  try {{
    const res = await fetch('/confirm-booking', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(data)
    }});
    const json = await res.json();
    if (!json.success) throw new Error(json.error || 'Unknown error');
    document.getElementById('contactForm').style.display = 'none';
    const sm = document.getElementById('successMsg');
    document.getElementById('successDetail').textContent =
      'Your call with Proles Home Healthcare Consultants is booked for ' +
      data.date + ' at ' + data.time + '.';
    sm.classList.add('show');
  }} catch(err) {{
    alert('Error: ' + err.message);
    btn.textContent = 'Confirm Booking'; btn.disabled = false;
  }}
}}
loadAvailability();
</script>
</body>
</html>"""
    return Response(html, mimetype='text/html')


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
        f"{COMPANY_URL} | amthuku@gmail.com | (443) 374-2931"
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


@app.route('/demo/<int:row_num>')
def demo_site(row_num):
    agencies = load_agencies()
    agency = agencies.get(row_num)
    if not agency:
        abort(404)
    return Response(build_demo(agency, row_num), mimetype='text/html')


if __name__ == '__main__':
    print(f"Proles Home Healthcare Consultants Proposal Server — http://0.0.0.0:{PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
