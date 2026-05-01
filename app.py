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
EXAMPLE_DISPLAY = 'inspiredoptionscare.com'
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
  body { font-family: Arial, sans-serif; background: var(--bg); color: var(--text); padding: 30px 20px; min-height: 100vh; }
  .page-header {
    border-bottom: 3px solid var(--gold); padding-bottom: 16px; margin-bottom: 24px;
    display: flex; justify-content: space-between; align-items: flex-end;
  }
  h1 { font-size: 26px; color: var(--text); font-weight: 900; text-transform: uppercase; letter-spacing: -0.5px; }
  h1 span { color: var(--gold); }
  .sub { font-size: 11px; color: var(--text2); margin-top: 4px; letter-spacing: 2px; text-transform: uppercase; }
  .brand-badge { font-size: 11px; font-weight: 900; color: var(--gold); text-transform: uppercase; letter-spacing: 1.5px; text-align: right; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th {
    background: var(--bg2); color: var(--gold); padding: 10px 12px; text-align: left;
    font-size: 9px; letter-spacing: 2px; text-transform: uppercase; border-bottom: 2px solid var(--gold);
  }
  td { padding: 9px 12px; border-bottom: 1px solid var(--bg3); color: var(--text); vertical-align: middle; }
  tr:hover td { background: var(--bg2); }
  .btn {
    display: inline-block; padding: 5px 14px; font-size: 10px; font-weight: 900;
    text-decoration: none; margin-right: 4px; text-transform: uppercase; letter-spacing: 1px;
    clip-path: polygon(0 0,calc(100% - 5px) 0,100% 5px,100% 100%,5px 100%,0 calc(100% - 5px));
    cursor: pointer; border: none; font-family: Arial, sans-serif;
  }
  .btn-gold { background: var(--gold); color: #111; }
  .btn-red  { background: var(--red);  color: var(--text); }
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
    <img src="https://ioi-proposal-server-production.up.railway.app/static/logo.png" alt="Proles" style="height:56px;width:auto;filter:brightness(0) invert(1);">
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
      <img src="/static/logo.png" alt="Proles Home Healthcare Consultants" style="height:64px;width:auto;display:block;filter:brightness(0) invert(1);">
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

        rows += f"""<tr{row_style}>
          <td>{i}</td>
          <td><a href="/proposal/{i}" style="color:var(--gold);font-weight:bold;">{name}</a>{badge_html}</td>
          <td>{atype}</td><td>{city}</td><td>{phone}</td><td>{email}</td>
          <td>{action_html}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>IOI Outreach &mdash; Follow-Up 50 (SDAT Verified)</title>
<style>{INDEX_CSS}</style>
</head>
<body>
<div class="page-header">
  <div>
    <h1>IOI Outreach &mdash; <span>Follow-Up 50</span></h1>
    <div class="sub">SDAT Verified &bull; Maryland Agency Outreach &bull; April 2026</div>
  </div>
  <div class="brand-badge">Proles Home Healthcare Consultants</div>
</div>
<table>
  <thead><tr>
    <th>#</th><th>Agency Name</th><th>Type</th><th>City</th><th>Phone</th><th>Email</th><th>Actions</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>
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
        proposal_html = build_proposal(agency, row_num)
        pdf_bytes = HTML(string=proposal_html, base_url=None).write_pdf(
            stylesheets=[CSS(string='@page { size: Letter; margin: 0.5in 0.6in; }')]
        )
    except Exception as e:
        print(f'[pdf] {e}')

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
        slots_html = ''
        for sl in slot_labels:
            slot_id = f"{iso}T{sl.replace(' ', '').replace(':', '')}"
            slots_html += f'<div class="time-slot" onclick="selectSlot(this,\'{iso}\',\'{sl}\')" data-slot="{slot_id}">{sl}</div>\n'
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
function selectSlot(el, date, time) {{
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


if __name__ == '__main__':
    print(f"Proles Home Healthcare Consultants Proposal Server — http://0.0.0.0:{PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
