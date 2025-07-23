#!/usr/bin/env python3
"""
Fetch the Charter Reform Commission Public Events page, detect changes,
archive snapshots, generate an HTML diff report in docs/index.html,
and optionally send an email when updates occur.
"""

import os
import sys
import time
import pathlib
import hashlib
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
from difflib import HtmlDiff

URL = "https://reformlacharter.lacity.gov/public-events"

# Paths (repo-relative)
ROOT = pathlib.Path(__file__).parent.resolve()
DATA_DIR = ROOT / "data"
SNAP_DIR = DATA_DIR / "snapshots"
DOCS_DIR = ROOT / "docs"
LATEST_TXT = DATA_DIR / "latest.txt"
LATEST_HTML = DATA_DIR / "latest.html"
REPORT_HTML = DOCS_DIR / "index.html"

# ------------------------------------------------------------------ extraction

def fetch_page():
    r = requests.get(URL, timeout=30)
    r.raise_for_status()
    return r.text

def extract_visible_text(html):
    soup = BeautifulSoup(html, "html.parser")

    # Remove scripts, styles, noscript, head, meta, and link tags
    for tag in soup(['script', 'style', 'noscript', 'head', 'meta', 'link']):
        tag.decompose()

    # Remove common layout/navigation clutter
    for tag in soup(['nav', 'header', 'footer', 'aside']):
        tag.decompose()

    # Remove elements hidden with CSS display:none or aria-hidden
    for tag in soup.find_all(style=lambda s: s and 'display:none' in s):
        tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()

    # Gather visible text from standard block elements (and links)
    text_chunks = []
    for element in soup.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'a', 'div']):
        # Use direct string if available, else recursive get_text
        if element.string and element.string.strip():
            text_chunks.append(element.string.strip())
        else:
            full = element.get_text(separator=' ', strip=True)
            if full:
                text_chunks.append(full)

    # Deduplicate while preserving order
    lines = [l for l in (t.strip() for t in text_chunks) if l]
    normalized = '\n'.join(dict.fromkeys(lines))

    return normalized, str(soup)

# ------------------------------------------------------------------ hashing

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def load_last_text():
    if LATEST_TXT.exists():
        return LATEST_TXT.read_text(encoding="utf-8")
    return ""

def save_latest(text: str, html: str):
    DATA_DIR.mkdir(exist_ok=True)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_TXT.write_text(text, encoding="utf-8")
    LATEST_HTML.write_text(html, encoding="utf-8")

def archive_snapshot(text: str, html: str, ts: datetime):
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = ts.strftime("%Y%m%d-%H%M%S")
    (SNAP_DIR / f"{stamp}.txt").write_text(text, encoding="utf-8")
    (SNAP_DIR / f"{stamp}.html").write_text(html, encoding="utf-8")
    return stamp

# ------------------------------------------------------------------ reporting

def build_report(current_text, current_html, current_hash, previous_text, previous_hash, stamp):
    """
    Build docs/index.html with:
      - Current status summary
      - Table of snapshots (read from folder)
      - Latest diff (prev vs current)
      - Raw current HTML (collapsed details)
    """
    DOCS_DIR.mkdir(exist_ok=True)

    # Build snapshots table
    rows = []
    snaps = sorted(SNAP_DIR.glob("*.txt"))
    for snap in sorted(snaps):  # chronological
        if snap.suffix != ".txt":
            continue
        snap_stamp = snap.stem
        snap_text = snap.read_text(encoding="utf-8")
        snap_hash = sha256_text(snap_text)
        rows.append((snap_stamp, snap_hash))

    # Diff block
    diff_html = ""
    if previous_text:
        hd = HtmlDiff(wrapcolumn=100)
        diff_html = hd.make_table(
            previous_text.splitlines(),
            current_text.splitlines(),
            fromdesc="Previous",
            todesc="Current",
            context=True,
            numlines=4,
        )
    else:
        diff_html = "<p>No previous snapshot; initial capture.</p>"

    now_iso = datetime.now(timezone.utc).isoformat()

    # Basic styling
    css = """
    body{font-family:system-ui,Arial,sans-serif;margin:2rem;max-width:900px;}
    table{border-collapse:collapse;width:100%;margin-bottom:2rem;}
    th,td{border:1px solid #ccc;padding:4px 8px;font-size:0.9rem;}
    th{background:#f0f0f0;}
    code{background:#f7f7f7;padding:2px 4px;font-size:0.9em;}
    details{margin-bottom:1.5rem;}
    .hash{font-family:monospace;font-size:0.8rem;}
    """
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Charter Reform Public Events Monitor</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{css}</style>
</head>
<body>
<h1>Charter Reform Public Events Monitor</h1>
<p>Automated status for the Public Events page. Last run: <strong>{now_iso}</strong> (UTC).</p>
<p>Latest detected content hash: <code class="hash">{current_hash}</code>.</p>
<p>Monitoring source: <a href="{URL}">{URL}</a></p>

<h2>Snapshot History</h2>
<table>
  <thead><tr><th>Timestamp</th><th>Hash</th></tr></thead>
  <tbody>
  {''.join(f'<tr><td>{ts}</td><td class="hash">{h}</td></tr>' for ts,h in rows)}
  </tbody>
</table>

<h2>Latest Change Diff</h2>
{diff_html}

<h2>Current Extracted Content</h2>
<details open><summary>Show/Hide</summary>
<pre style="white-space:pre-wrap;">{escape_html(current_text)}</pre>
</details>

<h2>Current Main HTML (raw)</h2>
<details><summary>Show raw HTML</summary>
<pre style="white-space:pre-wrap;">{escape_html(current_html)}</pre>
</details>

<footer><p>Generated by GitHub Actions.</p></footer>
</body>
</html>
"""
    REPORT_HTML.write_text(html, encoding="utf-8")

def escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )

# ------------------------------------------------------------------ email (optional)

def send_email_notification(subject: str, body: str):
    SMTP_HOST = "smtp.mailgun.org"
    SMTP_PORT = 587
    SMTP_USER = os.getenv("EMAIL_SENDER")     
    SMTP_PASS = os.getenv("EMAIL_PASSWORD")
    TO = os.getenv("EMAIL_RECIPIENT")

    if not all([SMTP_USER, SMTP_PASS, TO]):
        print("Missing Mailgun email environment variables.")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = TO

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, TO, msg.as_string())
            print("✅ Email notification sent.")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

# ------------------- GitHub issue creation ------------------- #

def create_github_issue(title, body):
    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")
    if not repo or not token:
        print("⚠️ GitHub issue creation skipped (missing repo or token).")
        return

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"title": title, "body": body}
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 201:
        print("✅ GitHub issue created successfully.")
    else:
        print(f"❌ Failed to create GitHub issue: {response.status_code} {response.text}")        


# ------------------------------------------------------------------ main

def main():
    try:
        html = fetch_page()
    except Exception as e:
        print(f"ERROR fetching page: {e}", file=sys.stderr)
        sys.exit(1)

    current_text, current_html = extract_visible_text(html)
    current_hash = sha256_text(current_text)
    previous_text = load_last_text()
    previous_hash = sha256_text(previous_text) if previous_text else ""

    changed = (current_hash != previous_hash)

    ts = datetime.now(timezone.utc)
    if changed:
        print("Change detected; archiving & rebuilding report.")
        save_latest(current_text, current_html)      # update latest
        stamp = archive_snapshot(current_text, current_html, ts)
        build_report(current_text, current_html, current_hash, previous_text, previous_hash, stamp)
        subj = "🔔 Charter Public Events Page Updated"
        body = f"A change was detected at {ts.isoformat()} UTC.\n\nSource: {URL}\nNew text: {current_text}\nPrev text: {previous_text}"
        send_email_notification(subj, body)
    else:
        print("No change; no commit will be made.")
        # Still rebuild report? Optional. Here we rebuild so the page shows last run time.
        build_report(current_text, current_html, current_hash, previous_text, previous_hash, stamp="")

if __name__ == "__main__":
    main()
