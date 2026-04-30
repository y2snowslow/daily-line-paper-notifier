#!/usr/bin/env python3
"""
Daily LINE notification + GitHub Pages publish with Gemini-generated commentary.

Each run:
  1. Queries arXiv for the latest EV inverter / power module paper
  2. Asks Gemini 2.0 Flash to generate Japanese summary, explanation, and 2 SVG figures
  3. Generates docs/index.html (mobile-friendly) with the commentary embedded
  4. Sends LINE notification with the GitHub Pages URL

Reads from env (set as GitHub Secrets / Variables):
  LINE_CHANNEL_ACCESS_TOKEN  - required
  LINE_USER_ID               - required
  GEMINI_API_KEY             - required
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

GEMINI_MODEL = 'gemini-2.5-flash-lite'  # current free-tier friendly
GEMINI_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'
GEMINI_FALLBACK_MODELS = [
    'gemini-2.5-flash',
    'gemini-flash-latest',
    'gemini-2.0-flash-lite',
]


def now_jst() -> datetime:
    return datetime.now(JST)


# ---------- arXiv ----------
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
        'authors': authors,
        'pub_date': pub_date,
    }


# ---------- Gemini ----------
GEMINI_PROMPT_TEMPLATE = """あなたはEVパワーエレクトロニクス分野(SiC/GaNパワーモジュール、トラクションインバータ、モータ駆動回路)の専門研究者です。以下の arXiv 論文のアブストラクトを読み、日本人エンジニア向けに詳しい解説とビジュアライズを作成してください。

論文タイトル: {title}
著者: {authors}
公開日: {pub_date}
arXiv ID: {arxiv_id}

アブストラクト(英語原文):
\"\"\"
{abstract}
\"\"\"

以下のJSON形式で返答してください。**JSON以外の前置き・後置きは禁止**:

{{
  "summary_short": "80字以内の超要約 (LINE通知に使う)",
  "background": "背景・課題の日本語解説 (200-300字、業界の何が問題で、なぜこの研究が必要か)",
  "explanation": "手法・成果の日本語解説 (400-600字、技術的詳細・回路トポロジー・制御則・デバイス選定・定量結果まで踏み込む)",
  "implications": "実用上の示唆 (200-300字、量産設計への含意、限界、他手法との比較)",
  "svg_main": "提案手法または論文の中心概念を可視化したSVG文字列。<svg ...>...</svg> の完全な形で返す。必ず viewBox=\\"0 0 720 280\\" を指定。色は #c75b00 (オレンジ強調), #1a1a1a (黒文字), #fff5e6 (薄オレンジ背景), #e3e0d8 (枠線), #fff (白) を使用。テキストは font-size 10-14。日本語混在可。要素を整理して情報量がある図にすること",
  "fig1_caption": "svg_main の解説キャプション (100-150字、技術的)",
  "svg_secondary": "結果・効果・比較を可視化したSVG文字列。バーチャート・折れ線・概念図など適切なものを選択。viewBox=\\"0 0 720 280\\" を指定。同じ色パレット使用",
  "fig2_caption": "svg_secondary の解説キャプション (100-150字)"
}}

SVGは情報量を持たせ、ただの装飾ではなく **論文の中身を理解する助けになる図** にしてください。アブストに数値があれば数値を反映してください。"""


def _call_one_model(api_key: str, model: str, prompt: str) -> dict:
    """Call a specific Gemini model. Returns parsed dict or raises."""
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.6,
            'responseMimeType': 'application/json',
            'maxOutputTokens': 8192,
        },
    }
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    print(f'[{now_jst().isoformat()}] Calling Gemini ({model})...')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as ex:
        err_body = ex.read().decode('utf-8', errors='replace')
        print(f'  HTTP {ex.code} from {model}: {err_body[:500]}', file=sys.stderr)
        raise

    if 'candidates' not in result or not result['candidates']:
        print(f'  No candidates in response: {json.dumps(result)[:500]}', file=sys.stderr)
        raise RuntimeError('Gemini returned no candidates')

    cand = result['candidates'][0]
    finish = cand.get('finishReason', 'UNKNOWN')
    if finish not in ('STOP', 'MAX_TOKENS'):
        print(f'  Bad finishReason: {finish}', file=sys.stderr)
    try:
        text = cand['content']['parts'][0]['text']
    except (KeyError, IndexError):
        print(f'  Unexpected response shape: {json.dumps(result)[:500]}', file=sys.stderr)
        raise

    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text
        text = text.rsplit('```', 1)[0]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as ex:
        print(f'  JSON parse failed: {ex}\n  Raw text (first 800 chars): {text[:800]}', file=sys.stderr)
        raise

    print(f'  OK from {model} (bg={len(data.get("background",""))}, exp={len(data.get("explanation",""))})')
    return data


def call_gemini(api_key: str, paper: dict) -> dict:
    prompt = GEMINI_PROMPT_TEMPLATE.format(
        title=paper['title'],
        authors=', '.join(paper['authors']) or 'N/A',
        pub_date=paper['pub_date'],
        arxiv_id=paper['arxiv_id'],
        abstract=paper['abstract'],
    )
    models_to_try = [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS
    last_err = None
    for model in models_to_try:
        try:
            return _call_one_model(api_key, model, prompt)
        except Exception as e:
            last_err = e
            print(f'  -> {model} failed: {type(e).__name__}: {e}', file=sys.stderr)
            continue
    raise RuntimeError(f'All Gemini models failed. Last error: {last_err}')


def fallback_commentary(paper: dict) -> dict:
    """If Gemini fails, return a basic structure so the page still builds."""
    abstract = paper['abstract']
    short = abstract[:80] + '...' if len(abstract) > 80 else abstract
    placeholder_svg = (
        '<svg viewBox="0 0 720 280" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="720" height="280" fill="#fff5e6"/>'
        '<text x="360" y="140" font-size="14" text-anchor="middle" fill="#c75b00">'
        'Gemini commentary unavailable'
        '</text></svg>'
    )
    return {
        'summary_short': short,
        'background': '(Gemini API応答なし — 原文要旨を参照してください)',
        'explanation': abstract,
        'implications': '(同上)',
        'svg_main': placeholder_svg,
        'fig1_caption': '図の生成に失敗しました',
        'svg_secondary': placeholder_svg,
        'fig2_caption': '図の生成に失敗しました',
    }


# ---------- HTML ----------
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
  .figure .caption b {{ color: #c75b00; }}
  .pull {{
    background: #fff5e6;
    border-left: 4px solid #c75b00;
    padding: 12px 14px;
    border-radius: 4px;
    margin: 14px 0;
    font-size: 14.5px;
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
  details.original-abstract {{
    margin: 18px 0;
    background: #fff;
    border: 1px solid #e3e0d8;
    border-radius: 10px;
    padding: 12px 16px;
  }}
  details.original-abstract summary {{
    cursor: pointer;
    font-size: 13px;
    color: #555;
    font-weight: 600;
  }}
  details.original-abstract p {{
    font-size: 13px;
    color: #444;
    line-height: 1.7;
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

  <div class="pull">{summary_short}</div>

  <h2>背景・課題</h2>
  <p>{background}</p>

  <h2>提案手法・主要構成</h2>
  <div class="figure">
    {svg_main}
    <div class="caption"><b>Fig.1</b>: {fig1_caption}</div>
  </div>

  <h2>手法と成果の解説</h2>
  <p>{explanation}</p>

  <h2>結果・効果のビジュアライズ</h2>
  <div class="figure">
    {svg_secondary}
    <div class="caption"><b>Fig.2</b>: {fig2_caption}</div>
  </div>

  <h2>実用への示唆</h2>
  <p>{implications}</p>

  <details class="original-abstract">
    <summary>原文アブストラクト(英語)を表示</summary>
    <p>{abstract}</p>
  </details>

  <div class="links">
    <a href="https://arxiv.org/abs/{arxiv_id}" target="_blank" rel="noopener">arXiv abstract</a>
    <a class="secondary" href="https://arxiv.org/pdf/{arxiv_id}" target="_blank" rel="noopener">PDF</a>
    <a class="secondary" href="https://arxiv.org/html/{arxiv_id}" target="_blank" rel="noopener">HTML(原図)</a>
  </div>

  <p class="footer-note">📝 解説と図はGemini AIが論文アブストから生成しています(自動生成のため細部に誤りがある場合があります — 詳細は arXiv 原論文を参照してください)。<br>
  生成日時: {generated_at}
  </p>
</div>
</body>
</html>
'''


def build_html(paper: dict, commentary: dict, today: str) -> str:
    return HTML_TEMPLATE.format(
        today=html.escape(today),
        title=html.escape(paper['title']),
        authors=html.escape(', '.join(paper['authors']) or 'N/A'),
        arxiv_id=html.escape(paper['arxiv_id']),
        pub_date=html.escape(paper['pub_date']),
        abstract=html.escape(paper['abstract']),
        summary_short=html.escape(commentary.get('summary_short', '')),
        background=html.escape(commentary.get('background', '')),
        explanation=html.escape(commentary.get('explanation', '')),
        implications=html.escape(commentary.get('implications', '')),
        svg_main=commentary.get('svg_main', ''),  # raw SVG, not escaped
        fig1_caption=html.escape(commentary.get('fig1_caption', '')),
        svg_secondary=commentary.get('svg_secondary', ''),
        fig2_caption=html.escape(commentary.get('fig2_caption', '')),
        generated_at=html.escape(now_jst().strftime('%Y-%m-%d %H:%M JST')),
    )


def write_html(html_text: str) -> None:
    docs = Path('docs')
    docs.mkdir(exist_ok=True)
    out = docs / 'index.html'
    out.write_text(html_text, encoding='utf-8')
    print(f'Wrote {out}  ({out.stat().st_size} bytes)')
    nojekyll = docs / '.nojekyll'
    if not nojekyll.exists():
        nojekyll.write_text('', encoding='utf-8')
        print(f'Wrote {nojekyll}')


# ---------- LINE ----------
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


# ---------- main ----------
def main() -> None:
    line_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    line_uid   = os.environ.get('LINE_USER_ID')
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if not (line_token and line_uid and gemini_key):
        print('ERROR: LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID / GEMINI_API_KEY env vars missing', file=sys.stderr)
        sys.exit(1)

    paper = fetch_latest_paper()
    if not paper:
        print('No paper found. Skip.')
        return

    try:
        commentary = call_gemini(gemini_key, paper)
    except Exception as e:
        print(f'Gemini call failed, falling back: {e}', file=sys.stderr)
        commentary = fallback_commentary(paper)

    today = now_jst().strftime('%Y-%m-%d')
    write_html(build_html(paper, commentary, today))

    pages = github_pages_url()
    msg_lines = [
        f"📄 本日の論文 ({today})",
        '',
        paper['title'],
        '',
        commentary.get('summary_short', ''),
        '',
    ]
    if pages:
        msg_lines += ['▼ 図入り解説(モバイル対応)', pages, '']
    msg_lines += ['▼ arXiv 原論文', f"https://arxiv.org/abs/{paper['arxiv_id']}"]
    msg = '\n'.join(msg_lines)

    send_line(line_token, line_uid, msg)
    print(f'Done: {paper["title"]}')


if __name__ == '__main__':
    main()
