#!/usr/bin/env python3
"""
Daily LINE notification + GitHub Pages publish.

Each run:
  1. Queries arXiv for the latest EV inverter / power module paper
  2. Generates docs/index.html (mobile-friendly, with SVG hero + Chart.js)
  3. Sends LINE notification with the GitHub Pages URL

Reads from env (set as GitHub Secrets / Variables):
  LINE_CHANNEL_ACCESS_TOKEN  - required
  LINE_USER_ID               - required
  GITHUB_REPOSITORY          - auto-set by Actions: "owner/repo"
"""
import os
import sys
import json
import html
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

ARXIV_QUERY = (
    'abs:%22traction+inverter%22+OR+abs:%22EV+inverter%22'
    '+OR+abs:%22SiC+power+module%22+OR+abs:%22GaN+inverter%22'
    '+OR+abs:%22wide+bandgap+inverter%22+OR+abs:%22electric+vehicle+inverter%22'
)
ARXIV_URL = (
    f'http://export.arxiv.org/api/query?search_query={ARXIV_QUERY}'
    '&sortBy=submittedDate&sortOrder=descending&max_results=5'
)
NS = {'atom': 'http://www.w3.org/2005/Atom'}
JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(JST)


def fetch_latest_paper():
    print(f'[{now_jst().isoformat()}] Querying arXiv...')
    with urllib.request.urlopen(ARXIV_URL, timeout=30) as resp:
        xml_text = resp.read().decode('utf-8')

    root = ET.fromstring(xml_text)
    entries = root.findall('atom:entry', NS)
    if not entries:
        return None

    e = entries[0]
    title = ' '.join((e.findtext('atom:title', '', NS) or '').split())
    arxiv_id = (e.findtext('atom:id', '', NS) or '').replace('http://arxiv.org/abs/', '').strip()
    abstract = ' '.join((e.findtext('atom:summary', '', NS) or '').split())
    summary = abstract[:180] + '...' if len(abstract) > 180 else abstract

    authors = []
    for a in e.findall('atom:author', NS):
        name = a.findtext('atom:name', '', NS) or ''
        if name:
            authors.append(name.strip())

    pub_text = e.findtext('atom:published', '', NS) or e.findtext('atom:updated', '', NS) or ''
    try:
        pub_dt = datetime.fromisoformat(pub_text.replace('Z', '+00:00'))
        pub_date = pub_dt.astimezone(JST).strftime('%Y-%m-%d')
    except Exception:
        pub_date = now_jst().strftime('%Y-%m-%d')

    return {
        'title': title,
        'arxiv_id': arxiv_id,
        'abstract': abstract,
        'summary': summary,
        'authors': authors,
        'pub_date': pub_date,
    }


HTML_TEMPLATE = '''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>本日の論文 — {today}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", "Segoe UI", system-ui, sans-serif;
    color: #1a1a1a;
    background: #fafaf7;
    line-height: 1.75;
    font-size: 16px;
    -webkit-text-size-adjust: 100%;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 24px 20px 80px; }}
  .meta-pill {{
    display: inline-block;
    font-size: 12px;
    background: #1a1a1a;
    color: #fafaf7;
    padding: 4px 10px;
    border-radius: 999px;
    letter-spacing: 0.05em;
    margin-bottom: 14px;
  }}
  h1.title {{
    font-size: 22px;
    line-height: 1.45;
    margin: 0 0 14px;
    font-weight: 700;
    letter-spacing: -0.01em;
  }}
  .meta {{
    font-size: 13px;
    color: #666;
    border-top: 1px solid #e3e0d8;
    border-bottom: 1px solid #e3e0d8;
    padding: 12px 0;
    margin-bottom: 28px;
  }}
  .meta div {{ margin: 3px 0; }}
  .meta b {{ color: #1a1a1a; font-weight: 600; }}
  h2 {{
    font-size: 17px;
    margin: 32px 0 12px;
    padding-left: 12px;
    border-left: 4px solid #c75b00;
    font-weight: 700;
  }}
  p {{ margin: 10px 0; }}
  .figure {{
    background: #ffffff;
    border: 1px solid #e3e0d8;
    border-radius: 10px;
    padding: 16px;
    margin: 18px 0;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  }}
  .figure svg {{ width: 100%; height: auto; display: block; }}
  .figure .caption {{
    font-size: 13px;
    color: #555;
    margin-top: 10px;
    line-height: 1.55;
  }}
  .abstract {{
    background: #ffffff;
    border: 1px solid #e3e0d8;
    border-radius: 10px;
    padding: 16px;
    font-size: 14px;
    color: #1a1a1a;
    line-height: 1.7;
    white-space: normal;
  }}
  .links {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 24px;
  }}
  .links a {{
    display: inline-block;
    padding: 9px 14px;
    background: #1a1a1a;
    color: #fafaf7;
    text-decoration: none;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 500;
  }}
  .links a.secondary {{ background: #ffffff; color: #1a1a1a; border: 1px solid #1a1a1a; }}
  .footer-note {{
    font-size: 12px;
    color: #888;
    margin-top: 36px;
    padding-top: 16px;
    border-top: 1px solid #e3e0d8;
    line-height: 1.6;
  }}
  @media (max-width: 480px) {{
    h1.title {{ font-size: 19px; }}
    h2 {{ font-size: 16px; }}
    body {{ font-size: 15.5px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <span class="meta-pill">📄 本日の論文 · {today}</span>
  <h1 class="title">{title}</h1>
  <div class="meta">
    <div><b>著者</b>: {authors}</div>
    <div><b>arXiv ID</b>: {arxiv_id} ・ <b>公開日</b>: {pub_date}</div>
  </div>

  <h2>イメージ</h2>
  <div class="figure">
    <svg viewBox="0 0 720 260" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#1a1a1a"/>
        </marker>
      </defs>
      <rect x="40" y="80" width="100" height="100" fill="#fff5e6" stroke="#c75b00" stroke-width="1.5" rx="6"/>
      <text x="90" y="120" font-size="13" text-anchor="middle" fill="#c75b00" font-weight="700">Battery</text>
      <text x="90" y="138" font-size="11" text-anchor="middle" fill="#555">DC</text>
      <line x1="140" y1="130" x2="190" y2="130" stroke="#1a1a1a" stroke-width="2" marker-end="url(#arr)"/>
      <rect x="200" y="60" width="200" height="140" fill="#1a1a1a" rx="8"/>
      <text x="300" y="90" font-size="14" text-anchor="middle" fill="#fafaf7" font-weight="700">Inverter</text>
      <text x="300" y="108" font-size="11" text-anchor="middle" fill="#fafaf7">SiC / GaN Power Module</text>
      <g fill="#c75b00">
        <rect x="220" y="120" width="22" height="18" rx="2"/>
        <rect x="254" y="120" width="22" height="18" rx="2"/>
        <rect x="288" y="120" width="22" height="18" rx="2"/>
        <rect x="322" y="120" width="22" height="18" rx="2"/>
        <rect x="356" y="120" width="22" height="18" rx="2"/>
      </g>
      <text x="300" y="170" font-size="11" text-anchor="middle" fill="#fafaf7">3-phase switching</text>
      <line x1="400" y1="120" x2="450" y2="120" stroke="#c75b00" stroke-width="1.5"/>
      <line x1="400" y1="135" x2="450" y2="135" stroke="#c75b00" stroke-width="1.5"/>
      <line x1="400" y1="150" x2="450" y2="150" stroke="#c75b00" stroke-width="1.5"/>
      <text x="425" y="105" font-size="10" text-anchor="middle" fill="#555">3φ AC</text>
      <circle cx="490" cy="135" r="32" fill="#fff5e6" stroke="#c75b00" stroke-width="1.5"/>
      <text x="490" y="140" font-size="16" text-anchor="middle" fill="#c75b00" font-weight="700">M</text>
      <text x="490" y="180" font-size="11" text-anchor="middle" fill="#555">Traction Motor</text>
      <text x="40" y="50" font-size="13" font-weight="700" fill="#1a1a1a">EV パワートレイン全体像</text>
      <text x="40" y="220" font-size="11" fill="#888">本日の論文はこのEVトラクションインバータ領域に関するもの</text>
    </svg>
    <div class="caption">EV(電気自動車)用トラクションインバータの基本構成図。本日の論文はこの領域の最新研究です。</div>
  </div>

  <h2>論文要旨(原文)</h2>
  <div class="abstract">{abstract}</div>

  <div class="links">
    <a href="https://arxiv.org/abs/{arxiv_id}" target="_blank" rel="noopener">arXiv abstract</a>
    <a class="secondary" href="https://arxiv.org/pdf/{arxiv_id}" target="_blank" rel="noopener">PDF</a>
    <a class="secondary" href="https://arxiv.org/html/{arxiv_id}" target="_blank" rel="noopener">HTML(原図)</a>
  </div>

  <p class="footer-note">📝 このページは GitHub Actions が毎日21:05(JST)に arXiv から自動取得した最新論文を掲載しています。<br>
  生成日時: {generated_at}
  </p>
</div>
</body>
</html>
'''


def generate_html(paper: dict, today: str) -> str:
    return HTML_TEMPLATE.format(
        today=html.escape(today),
        title=html.escape(paper['title']),
        authors=html.escape(', '.join(paper['authors']) or 'N/A'),
        arxiv_id=html.escape(paper['arxiv_id']),
        pub_date=html.escape(paper['pub_date']),
        abstract=html.escape(paper['abstract']),
        generated_at=html.escape(now_jst().strftime('%Y-%m-%d %H:%M JST')),
    )


def write_html(paper: dict, today: str) -> None:
    docs = Path('docs')
    docs.mkdir(exist_ok=True)
    out = docs / 'index.html'
    out.write_text(generate_html(paper, today), encoding='utf-8')
    print(f'Wrote {out}  ({out.stat().st_size} bytes)')


def github_pages_url() -> str:
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if '/' not in repo:
        return ''
    owner, name = repo.split('/', 1)
    return f'https://{owner}.github.io/{name}/'


def send_line(token: str, user_id: str, message: str) -> None:
    payload = {'to': user_id, 'messages': [{'type': 'text', 'text': message}]}
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    req = urllib.request.Request(
        'https://api.line.me/v2/bot/message/push',
        data=body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Authorization': f'Bearer {token}',
        },
        method='POST',
    )
    print(f'[{now_jst().isoformat()}] Sending to LINE...')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f'[{now_jst().isoformat()}] OK ({resp.status})')
    except urllib.error.HTTPError as ex:
        body = ex.read().decode('utf-8', errors='replace')
        print(f'HTTP {ex.code}: {body}', file=sys.stderr)
        sys.exit(1)


def main() -> None:
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    user_id = os.environ.get('LINE_USER_ID')
    if not token or not user_id:
        print('ERROR: LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID not set', file=sys.stderr)
        sys.exit(1)

    paper = fetch_latest_paper()
    if not paper:
        print('No paper found. Skip.')
        return

    today = now_jst().strftime('%Y-%m-%d')
    write_html(paper, today)

    pages = github_pages_url()
    msg_lines = [
        f"📄 本日の論文 ({today})",
        '',
        paper['title'],
        '',
        f"公開日: {paper['pub_date']}",
        '',
        f"要旨: {paper['summary']}",
        '',
    ]
    if pages:
        msg_lines += ['▼ 図入り詳細(モバイル対応)', pages, '']
    msg_lines += ['▼ arXiv 原論文', f"https://arxiv.org/abs/{paper['arxiv_id']}"]
    msg = '\n'.join(msg_lines)

    send_line(token, user_id, msg)
    print(f'Done: {paper["title"]}')


if __name__ == '__main__':
    main()
