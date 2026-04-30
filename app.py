import json
import os
import re
import urllib.parse
from flask import Flask, Response, abort

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENCIES_PATH = os.path.join(BASE_DIR, 'agencies.json')
PORT = int(os.environ.get('PORT', 5050))

_agencies_cache = None


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


CSS = """
  @page { size: Letter; margin: 0.5in 0.6in; }
  @media print {
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .action-bar { display: none !important; }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  .action-bar {
    background: #1A7A6A; padding: 12px 24px;
    display: flex; justify-content: space-between; align-items: center;
    position: sticky; top: 0; z-index: 100; font-family: Arial, sans-serif;
  }
  .action-left { display: flex; flex-direction: column; gap: 2px; }
  .action-name { color: #fff; font-weight: bold; font-size: 16px; }
  .action-type { color: #aac8c0; font-size: 12px; }
  .action-right { display: flex; gap: 10px; }
  .action-btn {
    background: #D4820A; color: #fff; padding: 8px 16px; border-radius: 20px;
    font-family: Arial, sans-serif; font-size: 13px; font-weight: bold;
    text-decoration: none; border: none; cursor: pointer;
  }
  .action-btn:hover { background: #b8700a; }

  body {
    font-family: Arial, Helvetica, sans-serif; background: #0F1E2E; color: #fff;
    min-height: 100vh; display: flex; flex-direction: column; align-items: center;
  }
  .page {
    width: 100%; max-width: 7.3in; background: #0F1E2E;
    display: flex; flex-direction: column; gap: 0; padding: 0.5in 0.6in;
  }
  .header {
    border-bottom: 3px solid #1A7A6A; padding-bottom: 14px; margin-bottom: 18px;
    display: flex; justify-content: space-between; align-items: flex-end;
  }
  .header-title { font-size: 30px; font-weight: 900; color: #fff; letter-spacing: -0.5px; line-height: 1.1; }
  .header-title em { font-style: normal; color: #1A7A6A; }
  .header-sub { font-size: 13px; color: #aac8c0; margin-top: 4px; letter-spacing: 0.3px; }
  .header-right { text-align: right; }
  .brand-name { font-size: 15px; font-weight: bold; color: #D4820A; letter-spacing: 1px; }
  .brand-tagline { font-size: 10px; color: #888; letter-spacing: 0.5px; margin-top: 2px; }

  .section-label {
    display: inline-block; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;
    text-transform: uppercase; padding: 3px 10px; border-radius: 3px; margin-bottom: 8px;
  }
  .label-amber { background: #D4820A; color: #fff; }
  .label-teal  { background: #1A7A6A; color: #fff; }

  .section { margin-bottom: 16px; }
  .problem-text { font-size: 16px; line-height: 1.55; color: #f0f0f0; }
  .problem-text strong { color: #D4820A; font-weight: 700; }

  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }

  .deliver-list { list-style: none; padding: 0; margin: 0; }
  .deliver-list li {
    font-size: 13px; line-height: 1.5; color: #e0e0e0;
    padding: 6px 0 6px 18px; border-bottom: 1px solid #1a3347; position: relative;
  }
  .deliver-list li:last-child { border-bottom: none; }
  .deliver-list li::before { content: '\\25b8'; color: #1A7A6A; position: absolute; left: 0; font-size: 12px; }
  .deliver-list li strong { color: #fff; }

  .example-box { background: #0a1620; border: 1px solid #1A7A6A; border-radius: 4px; padding: 14px 16px; }
  .example-url { font-size: 14px; font-weight: bold; color: #1A7A6A; text-decoration: none; display: block; margin-bottom: 4px; }
  .example-desc { font-size: 12px; color: #aac8c0; line-height: 1.5; }
  .example-badge {
    display: inline-block; background: #D4820A; color: #fff; font-size: 10px;
    font-weight: bold; padding: 2px 8px; border-radius: 10px; margin-top: 8px; letter-spacing: 0.5px;
  }
  .why-text { font-size: 13px; line-height: 1.65; color: #d0d8e0; }
  .why-text strong { color: #fff; }

  .cta-box {
    border: 2px solid #1A7A6A; background: #0d2030; border-radius: 5px;
    padding: 16px 22px; display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px; gap: 20px;
  }
  .cta-headline { font-size: 18px; font-weight: 900; color: #fff; line-height: 1.2; }
  .cta-headline em { font-style: normal; color: #1A7A6A; }
  .cta-contact { text-align: right; font-size: 13px; color: #ccc; line-height: 1.8; white-space: nowrap; }
  .cta-contact a { color: #D4820A; text-decoration: none; font-weight: bold; }

  .footer {
    border-top: 1px solid #1a3347; padding-top: 10px;
    display: flex; justify-content: space-between; align-items: center;
  }
  .footer-left { font-size: 11px; color: #556677; }
  .footer-right { font-size: 11px; color: #556677; text-align: right; }
"""


def build_proposal(agency):
    name = agency.get('name') or 'Agency'
    atype = agency.get('type') or ''
    row_num = int(agency.get('num') or 0)
    phrase = type_phrase(atype)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Digital Presence Package — {name}</title>
<style>{CSS}</style>
</head>
<body>
<div class="action-bar">
  <div class="action-left">
    <span class="action-name">{name}</span>
    <span class="action-type">{atype}</span>
  </div>
  <div class="action-right">
    <a href="/email/{row_num}" target="_blank" class="action-btn">Preview Email</a>
    <button onclick="window.print()" class="action-btn">Print Proposal</button>
  </div>
</div>
<div class="page">

  <div class="header">
    <div class="header-left">
      <div class="header-title">Digital <em>Presence</em> Package</div>
      <div class="header-sub">For {name}</div>
    </div>
    <div class="header-right">
      <div class="brand-name">PROLES CONSULTING</div>
      <div class="brand-tagline">Project Management &amp; Digital Solutions</div>
    </div>
  </div>

  <div class="section">
    <div class="section-label label-amber">The Problem</div>
    <div class="problem-text">
      <strong>65% of families search online before choosing a care provider.</strong>
      {phrase} if you have no website, they find your competitor instead &mdash; even if your care is better.
      You&rsquo;re licensed, operating, and serving real families. But you&rsquo;re invisible to everyone searching online right now.
    </div>
  </div>

  <div class="two-col">
    <div>
      <div class="section-label label-teal">What We Deliver</div>
      <ul class="deliver-list">
        <li><strong>Professional website</strong> &mdash; branded, mobile-friendly, fast</li>
        <li><strong>Staff &amp; employee portal</strong> &mdash; internal tools for your team</li>
        <li><strong>Appointment &amp; contact forms</strong> &mdash; clients reach you directly</li>
        <li><strong>Deployed in under 3 weeks</strong> &mdash; no months-long delays</li>
      </ul>
    </div>
    <div>
      <div class="section-label label-amber">Live Example</div>
      <div class="example-box">
        <a class="example-url" href="https://delightful-glacier-0971dfb0f.1.azurestaticapps.net">inspiredoptionscare.com</a>
        <div class="example-desc">
          Built for a Maryland home health agency &mdash; full branded site, staff portal, appointment system, and contact forms. Exactly what we&rsquo;ll build for you.
        </div>
        <span class="example-badge">Live in 3 weeks</span>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-label label-teal">Why PROLES</div>
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
    <div class="footer-left">PROLES Consulting &nbsp;&bull;&nbsp; Baltimore, MD</div>
    <div class="footer-right">
      <a href="https://www.prolesconsulting.com" style="color:#D4820A;text-decoration:none;font-weight:bold;">www.prolesconsulting.com</a>
      &nbsp;&bull;&nbsp; Project Management &amp; Digital Solutions &nbsp;&bull;&nbsp; April 2026
    </div>
  </div>

</div>
</body>
</html>"""


def build_email_body(agency):
    name = agency.get('name') or 'Agency'
    atype = agency.get('type') or 'home health agency'
    city = agency.get('city') or 'Maryland'
    return (
        f"Hi there,\n\n"
        f"My name is Alexander Thuku, and I'm reaching out from PROLES Consulting — "
        f"a Baltimore-based firm specializing in project management and digital solutions for healthcare providers in Maryland.\n\n"
        f"We came across {name} in the Maryland OHCQ provider registry as a licensed {atype.lower()}. "
        f"While reviewing the registry, we noticed that your agency doesn't appear to have a website — "
        f"which means families and patients searching online for services in {city} simply can't find you, "
        f"even though you're fully licensed and operating.\n\n"
        f"We recently built a complete digital platform for another Maryland home health agency. "
        f"Here's what it looks like: www.inspiredoptionscare.com — a branded homepage, staff and employee portal, "
        f"appointment request form, contact page, and services overview. Everything a family needs to find, trust, "
        f"and contact a provider. We delivered it in under three weeks.\n\n"
        f"We'd love to build the same for {name}. Would you be open to a quick 15-minute call this week to hear more? "
        f"No obligation — just a conversation to see if it's a good fit.\n\n"
        f"Best regards,\nAlexander Thuku\n"
        f"PROLES Consulting | Project Management & Digital Solutions\n"
        f"amthuku@gmail.com | (443) 374-2931 | Baltimore, MD"
    )


EMAIL_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: #0F1E2E; color: #fff; min-height: 100vh; padding: 30px 20px; }
  .container { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 22px; color: #fff; margin-bottom: 4px; }
  .subtitle { font-size: 13px; color: #aac8c0; margin-bottom: 24px; }
  .subject-box {
    background: #0d2030; border-left: 4px solid #1A7A6A; padding: 16px 20px;
    border-radius: 4px; margin-bottom: 24px;
  }
  .subject-label { font-size: 10px; font-weight: bold; letter-spacing: 1.5px; text-transform: uppercase; color: #aac8c0; margin-bottom: 8px; }
  .subject-line { font-size: 16px; color: #fff; font-weight: bold; }
  .email-card { background: #fff; color: #1a1a1a; border-radius: 6px; overflow: hidden; margin-bottom: 24px; }
  .email-card-header { background: #0F1E2E; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
  .email-brand { color: #fff; font-weight: bold; font-size: 14px; letter-spacing: 0.5px; }
  .email-brand span { color: #1A7A6A; }
  .email-body { padding: 32px 36px; font-size: 15px; line-height: 1.75; color: #2a2a2a; }
  .email-body p { margin-bottom: 16px; white-space: pre-wrap; }
  .mailto-bar {
    background: #0d2030; border: 1px solid #1A7A6A; border-radius: 5px;
    padding: 16px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px;
  }
  .mailto-info { font-size: 13px; color: #aac8c0; line-height: 1.6; }
  .mailto-info strong { color: #fff; }
  .btn-row { display: flex; gap: 10px; }
  .btn {
    display: inline-block; padding: 10px 20px; border-radius: 20px;
    font-size: 13px; font-weight: bold; text-decoration: none; cursor: pointer;
    border: none; font-family: Arial, sans-serif;
  }
  .btn-amber { background: #D4820A; color: #fff; }
  .btn-teal  { background: #1A7A6A; color: #fff; }
  .no-email-note { font-size: 14px; color: #D4820A; font-weight: bold; }
"""


@app.route('/')
def index():
    agencies = load_agencies()
    rows = ''
    for i in range(1, 51):
        a = agencies.get(i, {})
        name = a.get('name') or '—'
        atype = a.get('type') or '—'
        city = a.get('city') or '—'
        phone = a.get('phone') or '—'
        email = a.get('email') or '—'
        rows += f"""<tr>
          <td>{i}</td>
          <td><a href="/proposal/{i}" style="color:#1A7A6A;font-weight:bold;">{name}</a></td>
          <td>{atype}</td><td>{city}</td><td>{phone}</td><td>{email}</td>
          <td>
            <a href="/proposal/{i}" class="btn btn-teal">Proposal</a>
            <a href="/email/{i}" class="btn btn-amber">Email</a>
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Follow-Up 50 — PROLES Outreach</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; background: #0F1E2E; color: #fff; padding: 30px 20px; }}
  h1 {{ font-size: 26px; color: #fff; margin-bottom: 4px; }}
  .sub {{ font-size: 13px; color: #aac8c0; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #1A7A6A; color: #fff; padding: 10px 12px; text-align: left; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid #1a3347; color: #ddd; vertical-align: middle; }}
  tr:hover td {{ background: #0d2030; }}
  .btn {{ display: inline-block; padding: 5px 12px; border-radius: 12px; font-size: 11px; font-weight: bold; text-decoration: none; margin-right: 4px; }}
  .btn-teal {{ background: #1A7A6A; color: #fff; }}
  .btn-amber {{ background: #D4820A; color: #fff; }}
</style>
</head>
<body>
<h1>Follow-Up 50</h1>
<div class="sub">PROLES Consulting &mdash; Maryland Agency Outreach &mdash; April 2026</div>
<table>
  <thead><tr><th>#</th><th>Agency Name</th><th>Type</th><th>City</th><th>Phone</th><th>Email</th><th>Actions</th></tr></thead>
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
    return Response(build_proposal(agency), mimetype='text/html')


@app.route('/email/<int:row_num>')
def email_page(row_num):
    agencies = load_agencies()
    agency = agencies.get(row_num)
    if not agency:
        abort(404)

    name = agency.get('name') or 'Agency'
    email = agency.get('email') or ''
    phone = agency.get('phone') or ''
    subject = f"A Website for {name} — Built in 3 Weeks"
    body = build_email_body(agency)

    if email:
        mailto = f"mailto:{email}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
        contact_block = f"""<div class="mailto-bar">
  <div class="mailto-info">
    <strong>To:</strong> {email}<br>
    <strong>Subject:</strong> {subject}
  </div>
  <div class="btn-row">
    <a href="{mailto}" class="btn btn-teal">Open in Email Client</a>
    <button onclick="copyBody()" class="btn btn-amber">Copy Email Body</button>
  </div>
</div>"""
    else:
        contact_block = f'<div class="no-email-note">No email on file &mdash; call {phone}</div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Email Preview — {name}</title>
<style>{EMAIL_CSS}</style>
</head>
<body>
<div class="container">
  <h1>Email Preview</h1>
  <div class="subtitle">For {name} &nbsp;&bull;&nbsp; <a href="/proposal/{row_num}" style="color:#D4820A;">Back to Proposal</a></div>

  <div class="subject-box">
    <div class="subject-label">Subject Line</div>
    <div class="subject-line">{subject}</div>
  </div>

  <div class="email-card">
    <div class="email-card-header">
      <span class="email-brand">PROLES <span>Consulting</span></span>
      <span style="color:#888;font-size:12px;">Project Management &amp; Digital Solutions</span>
    </div>
    <div class="email-body">
      <p>{body.replace(chr(10), '<br>')}</p>
    </div>
  </div>

  {contact_block}
</div>
<script>
const emailBody = {repr(body)};
function copyBody() {{
  navigator.clipboard.writeText(emailBody).then(() => {{
    const btn = document.querySelector('.btn-amber');
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy Email Body', 2000);
  }});
}}
</script>
</body>
</html>"""
    return Response(html, mimetype='text/html')


if __name__ == '__main__':
    print(f"PROLES Proposal Server starting on http://0.0.0.0:{PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
