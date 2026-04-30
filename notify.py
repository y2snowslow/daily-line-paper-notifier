#!/usr/bin/env python3
"""
Daily LINE notification of the latest EV inverter / power module paper from arXiv.
Runs as a GitHub Actions scheduled workflow.

Reads credentials from environment variables (set as GitHub Secrets):
  LINE_CHANNEL_ACCESS_TOKEN
  LINE_USER_ID
"""
import os
import sys
import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

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
    summary = ' '.join((e.findtext('atom:summary', '', NS) or '').split())
    if len(summary) > 180:
        summary = summary[:180] + '...'

    pub_text = e.findtext('atom:published', '', NS) or e.findtext('atom:updated', '', NS) or ''
    try:
        pub_dt = datetime.fromisoformat(pub_text.replace('Z', '+00:00'))
        pub_date = pub_dt.astimezone(JST).strftime('%Y-%m-%d')
    except Exception:
        pub_date = now_jst().strftime('%Y-%m-%d')

    return {
        'title': title,
        'arxiv_id': arxiv_id,
        'summary': summary,
        'pub_date': pub_date,
    }


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
        print('ERROR: LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID env vars are not set', file=sys.stderr)
        sys.exit(1)

    paper = fetch_latest_paper()
    if not paper:
        print('No paper found. Skip notification.')
        return

    today = now_jst().strftime('%Y-%m-%d')
    msg = (
        f"📄 本日の論文 ({today})\n\n"
        f"{paper['title']}\n\n"
        f"公開日: {paper['pub_date']}\n"
        f"arXiv: https://arxiv.org/abs/{paper['arxiv_id']}\n\n"
        f"要旨: {paper['summary']}\n\n"
        f"▼ 図表入り詳細解説は Cowork の「daily-ev-inverter-paper」アーティファクトで"
    )

    send_line(token, user_id, msg)
    print(f'Done: {paper["title"]}')


if __name__ == '__main__':
    main()
