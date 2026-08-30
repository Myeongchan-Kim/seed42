#!/usr/bin/env python
"""Seed 42 - 클릭으로 걷는 연상 탐색.

응답 본문의 단어를 클릭하면 그 단어가 새 쿼리가 된다. K 로 상위 몇 개를 자르지
않으므로, 본문에 등장하는 모든 단어가 이웃이다. '진입차수 0 이라 도달 불가'
문제가 사라진다 (k=12 에서 베르세르크로 가는 길이 없었던 것이 그 예다).

클릭이 곧 그래프를 만든다. A 의 응답에서 B 를 누르면 A→B 엣지가 기록된다.
K 가 정의되지 않는 모드라 k=0 인 별도 graph_config 로 분리해 둔다.

  python server.py     ->  http://127.0.0.1:5001
"""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser

import markdown as md
from flask import Flask, redirect, request, url_for

from number import db, llm
from number.tokens import norm

app = Flask(__name__)
CLICK_K = 0  # 클릭 탐색 = K 없음

from number import tokens
from number.tokens import clean, is_word


def clickable(token: str) -> bool:
    return is_word(token)


def conn():
    return llm.conn()


def click_config() -> int:
    return db.config_id(conn(), llm.GEN_MODEL, 0.0, llm.PICK_MODEL, CLICK_K,
                        llm.PROMPT_VERSION, llm.SEED)


def known_words() -> set[str]:
    return {norm(r["word"]) for r in conn().execute(
        "SELECT n.word FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE r.gen_model=?", (llm.GEN_MODEL,))}



# ------------------------------------------------------------------- 다국어

LANGS = {"en": "English", "ko": "한국어", "zh": "中文", "es": "Español"}

STR = {
    "title":    {"en": "Seed 42", "ko": "Seed 42", "zh": "Seed 42", "es": "Seed 42"},
    "intro":    {"en": "Throw one word, get a response. Click any word inside it and "
                       "that becomes the next query. The path you click is the graph.",
                 "ko": "단어를 던지면 응답이 나오고, 응답 안의 단어를 누르면 "
                       "그것이 다음 쿼리가 된다. 누른 경로가 그대로 그래프가 된다.",
                 "zh": "投出一个词，得到回应。点击回应中的任意词，它就成为下一个查询。"
                       "你点击的路径就是这张图。",
                 "es": "Lanza una palabra y obtén una respuesta. Haz clic en cualquier "
                       "palabra dentro y esa será la siguiente consulta. El camino que "
                       "recorres es el grafo."},
    "ph":       {"en": "one word", "ko": "단어 하나", "zh": "一个词",
                 "es": "una palabra"},
    "go":       {"en": "Throw", "ko": "던지기", "zh": "投出", "es": "Lanzar"},
    "tried":    {"en": "Words thrown so far", "ko": "지금까지 던져본 단어",
                 "zh": "已投出的词", "es": "Palabras lanzadas"},
    "none":     {"en": "nothing yet", "ko": "아직 없음", "zh": "还没有",
                 "es": "todavía nada"},
    "from":     {"en": "came from", "ko": "에서 왔다", "zh": "来自", "es": "vino de"},
    "incoming": {"en": "Words that led here", "ko": "여기로 이어진 단어",
                 "zh": "通向这里的词", "es": "Palabras que llevan aquí"},
    "words":    {"en": "words", "ko": "단어", "zh": "词", "es": "palabras"},
    "indeg":    {"en": "in-degree", "ko": "들어온 경로", "zh": "入度",
                 "es": "grado de entrada"},
    "outdeg":   {"en": "clicks out", "ko": "나간 클릭", "zh": "出度",
                 "es": "clics de salida"},
    "chars":    {"en": "chars", "ko": "글자", "zh": "字数", "es": "caracteres"},
    "search":   {"en": "search", "ko": "단어 검색", "zh": "搜索", "es": "buscar"},
    "game":     {"en": "Find the path", "ko": "길 찾기", "zh": "寻路", "es": "Buscar camino"},
    "start":    {"en": "From", "ko": "출발 단어", "zh": "起点", "es": "Desde"},
    "goal":     {"en": "To", "ko": "도착 단어", "zh": "终点", "es": "Hasta"},
    "find":     {"en": "Find", "ko": "찾기", "zh": "查找", "es": "Buscar"},
    "hops":     {"en": "hops", "ko": "홉", "zh": "跳", "es": "saltos"},
    "nolink":   {"en": "No path yet — help connect them!",
                 "ko": "아직 연결이 없습니다 — 연결할 수 있게 도와주세요!",
                 "zh": "还没有路径 — 帮忙把它们连起来！",
                 "es": "Aún no hay camino — ¡ayuda a conectarlos!"},
    "nohelp":   {"en": "Click through words from either side. Every click adds an edge, "
                       "and the path may appear.",
                 "ko": "양쪽에서 단어를 눌러 걸어보세요. 클릭 하나가 엣지 하나가 되고, "
                       "그러다 길이 생깁니다.",
                 "zh": "从两边点击词语走走看。每一次点击都会添加一条边，路径可能就出现了。",
                 "es": "Haz clic en palabras desde ambos lados. Cada clic añade una arista "
                       "y el camino puede aparecer."},
    "unseen":   {"en": "not thrown yet", "ko": "아직 던져본 적 없는 단어",
                 "zh": "还没有投出过", "es": "aún no lanzada"},
    "throwit":  {"en": "Throw it first", "ko": "먼저 던져보기",
                 "zh": "先投出", "es": "Lánzala primero"},
    "explore":  {"en": "Explore", "ko": "탐색하기", "zh": "探索", "es": "Explorar"},
    "seeking":  {"en": "Searching…", "ko": "찾는 중…", "zh": "查找中…",
                 "es": "Buscando…"},
    "dash":     {"en": "Dashboard", "ko": "대시보드", "zh": "仪表板", "es": "Panel"},
    "toppath":  {"en": "Most searched paths", "ko": "인기 경로",
                 "zh": "热门路径", "es": "Rutas más buscadas"},
    "livewords":{"en": "Live searches", "ko": "실시간 검색어",
                 "zh": "实时搜索", "es": "Búsquedas en vivo"},
    "livepairs":{"en": "Recent pairs", "ko": "최근 검색 쌍",
                 "zh": "最近的词对", "es": "Pares recientes"},
    "graphof":  {"en": "The graph", "ko": "그래프", "zh": "图", "es": "El grafo"},
    "nodes":    {"en": "nodes", "ko": "노드", "zh": "节点", "es": "nodos"},
    "edges":    {"en": "edges", "ko": "엣지", "zh": "边", "es": "aristas"},
    "thrown":   {"en": "thrown", "ko": "던져봄", "zh": "已投出", "es": "lanzadas"},
    "empty":    {"en": "nothing yet", "ko": "아직 없음", "zh": "还没有", "es": "nada aún"},
    "gsub":     {"en": "Two words, one chain. How far apart are they?",
                 "ko": "두 단어, 하나의 사슬. 얼마나 멀리 떨어져 있을까?",
                 "zh": "两个词，一条链。它们相距多远？",
                 "es": "Dos palabras, una cadena. ¿Qué tan lejos están?"},
}


def pick_lang() -> str:
    """?lang= -> 쿠키 -> Accept-Language -> en"""
    q = request.args.get("lang")
    if q in LANGS:
        return q
    c = request.cookies.get("lang")
    if c in LANGS:
        return c
    for part in request.headers.get("Accept-Language", "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return "en"


def T(lang: str, key: str) -> str:
    return STR[key].get(lang, STR[key]["en"])


def respond_html(title: str, body: str, count: int, lang: str):
    """언어 선택을 쿠키에 기억한다."""
    from flask import make_response
    r = make_response(page(title, body, count, lang))
    if request.args.get("lang") in LANGS:
        r.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return r


GAME_JS = r"""
const form = document.querySelector('form.pf');
const out = document.getElementById('out');
const chip = w => {
  const a = document.createElement('a');
  a.className = 'hop';
  a.href = '/w/' + encodeURIComponent(w) + '?lang=' + L.lang;
  a.textContent = w;
  return a;
};
const box = (cls, big, note, words, act) => {
  const d = document.createElement('div'); d.className = cls;
  const h = document.createElement('p'); h.className = 'big'; h.textContent = big;
  d.appendChild(h);
  if (note) { const n = document.createElement('p'); n.className = 'note';
              n.textContent = note; d.appendChild(n); }
  if (words) {
    const c = document.createElement('div'); c.className = 'ctas';
    for (const w of words) {
      const a = document.createElement('a'); a.className = 'cta';
      a.href = '/w/' + encodeURIComponent(w) + '?lang=' + L.lang;
      a.textContent = w + ' — ' + act;
      c.appendChild(a);
    }
    d.appendChild(c);
  }
  return d;
};
form.addEventListener('submit', async e => {
  const a = form.a.value.trim(), b = form.b.value.trim();
  if (!a || !b) return;                       // 빈 값이면 평소대로 제출
  e.preventDefault();
  out.textContent = '';
  out.appendChild(box('box seeking', L.seeking));
  history.replaceState(null, '', '/path?a=' + encodeURIComponent(a) +
    '&b=' + encodeURIComponent(b) + '&lang=' + L.lang);
  let r;
  try {
    r = await (await fetch('/api/path?a=' + encodeURIComponent(a) +
      '&b=' + encodeURIComponent(b))).json();
  } catch (err) { out.textContent = ''; out.appendChild(box('box warn', String(err)));
                  return; }
  out.textContent = '';
  if (r.status === 'ok') {
    const d = box('box ok', r.hops + ' ' + L.hops);
    const c = document.createElement('div'); c.className = 'chain';
    r.path.forEach((w, i) => {
      if (i) { const s = document.createElement('span'); s.className = 'arr';
               s.textContent = '\u2192'; c.appendChild(s); }
      c.appendChild(chip(w));
    });
    d.appendChild(c); out.appendChild(d);
  } else {
    const unseen = r.status === 'unseen';
    out.appendChild(box(unseen ? 'box' : 'box warn',
      unseen ? L.unseen : L.nolink, L.nohelp, r.missing,
      unseen ? L.throwit : L.explore));
  }
});
"""


# --------------------------------------------------------------------- 길찾기

_G: dict = {"cfg": None, "adj": None, "rev": None, "edges": 0}


def graph_adj():
    """인접 리스트를 메모리에 올려둔다. 요청마다 DB 에서 읽으면 7초가 걸려
    게임이 안 된다. 엣지 수가 5% 넘게 늘면 다시 읽는다 (크롤이 계속 돌기 때문)."""
    c = conn()
    cfg = click_config()
    n = c.execute("SELECT COUNT(*) x FROM edge WHERE config_id=?", (cfg,)).fetchone()["x"]
    if _G["adj"] is not None and _G["cfg"] == cfg and n < _G["edges"] * 1.05:
        return _G["adj"], _G["rev"]
    adj: dict[int, list[int]] = {}
    rev: dict[int, list[int]] = {}
    for a, b in c.execute("SELECT src_id, dst_id FROM edge WHERE config_id=?", (cfg,)):
        adj.setdefault(a, []).append(b)
        rev.setdefault(b, []).append(a)
    _G.update(cfg=cfg, adj=adj, rev=rev, edges=n)
    return adj, rev


def shortest(adj, rev, src: int, dst: int, cap: int = 300_000):
    """양방향 BFS. 한쪽에서만 뻗으면 분기수가 100 을 넘어 금방 터진다."""
    if src == dst:
        return [src]
    fp, bp = {src: None}, {dst: None}
    fq, bq = [src], [dst]
    seen = 0
    while fq and bq and seen < cap:
        if len(fq) <= len(bq):
            nxt = []
            for u in fq:
                for v in adj.get(u, ()):
                    if v in bp:
                        return _join(fp, bp, u, v)
                    if v not in fp:
                        fp[v] = u
                        nxt.append(v)
                seen += 1
            fq = nxt
        else:
            nxt = []
            for u in bq:
                for v in rev.get(u, ()):
                    if v in fp:
                        return _join(fp, bp, v, u)
                    if v not in bp:
                        bp[v] = u
                        nxt.append(v)
                seen += 1
            bq = nxt
    return None


def _join(fp, bp, u, v):
    left, k = [], u
    while k is not None:
        left.append(k)
        k = fp[k]
    right, k = [], v
    while k is not None:
        right.append(k)
        k = bp[k]
    return left[::-1] + right


def node_of(word: str):
    r = conn().execute("SELECT id FROM node WHERE lower(word)=lower(?)",
                       (word.strip(),)).fetchone()
    return r["id"] if r else None


def has_response(word: str) -> bool:
    return conn().execute(
        "SELECT 1 FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE lower(n.word)=lower(?) AND r.gen_model=? LIMIT 1",
        (word.strip(), llm.GEN_MODEL)).fetchone() is not None


# ------------------------------------------------------------------- 렌더링

CSS = """
:root{--ground:#f7f8f7;--surface:#fff;--raised:#f0f3f2;--ink:#16211f;--muted:#5e6b68;
--faint:#8b9793;--rule:#dde3e1;--accent:#0f6e63;--accent-soft:#e3f0ee;--seen:#7b4bb8;
--sans:"IBM Plex Sans",system-ui,sans-serif;--serif:"IBM Plex Serif",Georgia,serif;
--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--ground:#101514;--surface:#171e1d;--raised:#1e2726;
--ink:#e6edeb;--muted:#93a29e;--faint:#6e7d79;--rule:#263231;--accent:#4fd1c0;
--accent-soft:#16302c;--seen:#b79bea}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
font-size:15px;line-height:1.6}
header{border-bottom:1px solid var(--rule);background:var(--surface);padding:12px 22px;
display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;position:sticky;top:0;z-index:5}
header a.home{font-family:var(--serif);font-weight:600;font-size:16px;color:var(--ink);
text-decoration:none}
.sub{font-family:var(--mono);font-size:12px;color:var(--faint)}
.wrap{max-width:min(74ch,100%);margin:0 auto;padding:26px 22px 70px}
h1{font-family:var(--serif);font-size:30px;margin:0 0 2px;font-weight:600}
.params{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 22px}
.chip{font-family:var(--mono);font-size:11px;padding:3px 9px;border-radius:4px;
border:1px solid var(--rule);background:var(--surface);color:var(--muted)}
.chip b{color:var(--ink);font-weight:500}
.body{word-break:break-word;background:var(--surface);border:1px solid var(--rule);
border-radius:8px;padding:20px 24px;font-size:14.5px;line-height:1.75}
.body>*:first-child{margin-top:0}.body>*:last-child{margin-bottom:0}
.body h1,.body h2,.body h3,.body h4{font-family:var(--serif);line-height:1.3;
margin:26px 0 10px;font-weight:600}
.body h1{font-size:21px}.body h2{font-size:18px}.body h3{font-size:16px}.body h4{font-size:15px}
.body p{margin:0 0 13px}
.body ul,.body ol{margin:0 0 13px;padding-left:22px}
.body li{margin:3px 0}
.body li>p{margin:0}
.body strong{font-weight:600;color:var(--ink)}
.body em{font-style:italic}
.body code{font-family:var(--mono);font-size:12.5px;background:var(--raised);
padding:1px 5px;border-radius:4px}
.body pre{background:var(--raised);border:1px solid var(--rule);border-radius:6px;
padding:12px 14px;overflow-x:auto;margin:0 0 13px}
.body pre code{background:none;padding:0;font-size:12.5px;line-height:1.55}
.body blockquote{margin:0 0 13px;padding:2px 0 2px 14px;border-left:3px solid var(--rule);
color:var(--muted)}
.body hr{border:0;border-top:1px solid var(--rule);margin:20px 0}
.body table{border-collapse:collapse;width:100%;margin:0 0 13px;font-size:13.5px;display:block;
overflow-x:auto}
.body th,.body td{border:1px solid var(--rule);padding:6px 10px;text-align:left;vertical-align:top}
.body th{background:var(--raised);font-weight:500}
a.t{color:inherit;text-decoration:none;border-bottom:1px dotted var(--faint);cursor:pointer}
a.t:hover{background:var(--accent-soft);color:var(--accent);border-bottom-color:var(--accent)}
a.t.seen{color:var(--seen);border-bottom-color:var(--seen)}
a.t:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.lbl{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);
margin:26px 0 9px;font-weight:500}
.trail{font-size:13px;color:var(--muted)}
.trail a{color:var(--accent)}
ul.words{list-style:none;padding:0;margin:0;display:grid;
grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:5px}
ul.words a{display:block;padding:7px 11px;border:1px solid var(--rule);border-radius:6px;
background:var(--surface);color:var(--ink);text-decoration:none;font-size:14px;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
ul.words a:hover{border-color:var(--accent);color:var(--accent)}
form.q{display:flex;gap:7px;margin:0 0 22px}
form.q input{flex:1;font:inherit;font-size:14px;padding:8px 12px;border:1px solid var(--rule);
border-radius:6px;background:var(--surface);color:var(--ink)}
form.q button{font:inherit;font-size:14px;padding:8px 16px;border:1px solid var(--accent);
background:var(--accent);color:var(--ground);border-radius:6px;cursor:pointer}
.note{color:var(--faint);font-size:13px}
form.pf{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin:18px 0 6px}
form.pf label{display:flex;flex-direction:column;gap:5px;font-size:11px;
letter-spacing:.06em;text-transform:uppercase;color:var(--faint);font-weight:500}
form.pf input{font:inherit;font-size:15px;padding:9px 13px;border:1px solid var(--rule);
border-radius:6px;background:var(--surface);color:var(--ink);min-width:190px}
form.pf button{font:inherit;font-size:14px;padding:10px 22px;border:1px solid var(--accent);
background:var(--accent);color:var(--ground);border-radius:6px;cursor:pointer}
.box{margin:26px 0 0;padding:20px 22px;border:1px solid var(--rule);border-radius:9px;
background:var(--surface)}
.box.ok{border-color:var(--accent)}
.box.warn{border-color:var(--warn,#b8860b)}
.big{margin:0 0 12px;font-family:var(--serif);font-size:24px;font-weight:600}
.chain{display:flex;flex-wrap:wrap;gap:7px;align-items:center;line-height:2}
a.hop{padding:5px 12px;border:1px solid var(--rule);border-radius:99px;
background:var(--ground);color:var(--ink);text-decoration:none;font-size:14px}
a.hop:hover{border-color:var(--accent);color:var(--accent)}
.arr{color:var(--faint);font-size:13px}
.ctas{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
a.cta{padding:9px 16px;border:1px solid var(--accent);border-radius:6px;
color:var(--accent);text-decoration:none;font-size:13px}
a.cta:hover{background:var(--accent-soft)}
.stats{display:flex;gap:22px;flex-wrap:wrap;margin:20px 0 4px;font-size:13px;
color:var(--muted)}
.stats b{color:var(--ink);font-family:var(--mono);font-size:15px;
font-variant-numeric:tabular-nums}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:28px;
margin-top:8px}
ul.rows{list-style:none;padding:0;margin:0}
ul.rows li{display:flex;align-items:center;gap:8px;padding:8px 0;
border-bottom:1px solid var(--rule);font-size:14px}
ul.rows li a{color:var(--ink);text-decoration:none;flex:1;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
ul.rows li a:hover{color:var(--accent)}
.pill{font-family:var(--mono);font-size:11px;padding:2px 8px;border-radius:99px;
background:var(--accent-soft);color:var(--accent);white-space:nowrap}
.pill.warn{background:var(--raised);color:var(--faint)}
.cnt{font-family:var(--mono);font-size:11px;color:var(--faint);min-width:20px;
text-align:right;font-variant-numeric:tabular-nums}
.tags{display:flex;flex-wrap:wrap;gap:5px}
.tags a{font-size:13px;padding:4px 10px;border:1px solid var(--rule);border-radius:99px;
color:var(--ink);text-decoration:none;background:var(--surface)}
.tags a:hover{border-color:var(--accent);color:var(--accent)}
.box.seeking{border-style:dashed;color:var(--muted)}
.box.seeking .big{color:var(--muted);font-size:19px}
.more{margin:18px 0 0}
.more a{display:inline-block;padding:9px 18px;border:1px solid var(--rule);
border-radius:6px;background:var(--surface);color:var(--accent);text-decoration:none;
font-size:13px}
.more a:hover{border-color:var(--accent)}
.spacer{flex:1}
a.navlink{font-size:13px;color:var(--accent);text-decoration:none;
padding:3px 10px;border:1px solid var(--rule);border-radius:5px}
a.navlink:hover{border-color:var(--accent)}
.langs{display:flex;gap:2px;flex-wrap:wrap}
.langs a{font-size:12px;padding:3px 9px;border-radius:5px;text-decoration:none;
color:var(--muted);border:1px solid transparent}
.langs a:hover{border-color:var(--rule)}
.langs a.on{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}
"""

HEAD = ('<!doctype html><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&'
        'family=IBM+Plex+Serif:wght@500;600&display=swap">'
        f"<style>{CSS}</style>")


def page(title: str, body: str, count: int, lang: str = "en") -> str:
    picker = "".join(
        f'<a class="lang{" on" if code == lang else ""}" '
        f'href="?lang={code}">{name}</a>'
        for code, name in LANGS.items())
    return (f"{HEAD}<title>{html.escape(title)}</title>"
            f'<header><a class="home" href="/">Seed 42</a>'
            f'<a class="navlink" href="{url_for("find_path", lang=lang)}">'
            f'{T(lang, "game")}</a>'
            f'<a class="navlink" href="{url_for("explore", lang=lang)}">'
            f'{T(lang, "explore")}</a>'
            f'<span class="sub">{llm.GEN_MODEL} · seed {llm.SEED} · '
            f'{count} {T(lang, "words")}</span>'
            f'<span class="spacer"></span><nav class="langs">{picker}</nav>'
            f"</header><div class=\"wrap\">{body}</div>")


class _Linkify(HTMLParser):
    """마크다운을 렌더한 HTML 에서 **텍스트 노드에만** 링크를 건다.

    원문에 정규식으로 링크를 걸면 마크다운 문법(**굵게**, `코드`, 표)이 깨지고,
    렌더된 HTML 에 정규식을 걸면 태그 속성까지 건드린다. 그래서 파서로 훑으며
    태그는 그대로 흘려보내고 본문 글자만 바꾼다."""

    SKIP = {"code", "pre", "a", "script", "style"}

    def __init__(self, seen: set[str], src: str, lang: str):
        super().__init__(convert_charrefs=True)
        self.seen, self.src, self.out, self.depth = seen, src, [], 0
        self.lang = lang

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        self.out.append(self.get_starttag_text() or f"<{tag}>")

    def handle_startendtag(self, tag, attrs):
        self.out.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.depth:                       # 코드·링크 안에서는 건드리지 않는다
            self.out.append(html.escape(data))
            return
        last = 0
        # 형태소 분석기가 준 위치에 그대로 링크를 건다. 표제어만 받으면
        # 본문 어디를 감싸야 할지 알 수 없다.
        for a, b, lemma in tokens.spans(data, self.lang):
            if a < last:
                continue
            self.out.append(html.escape(data[last:a]))
            surface = data[a:b]
            if norm(lemma) != norm(self.src):
                cls = "t seen" if norm(lemma) in self.seen else "t"
                url = url_for("word", w=lemma, **{"from": self.src})
                self.out.append(
                    f'<a class="{cls}" href="{html.escape(url)}">{html.escape(surface)}</a>')
            else:
                self.out.append(html.escape(surface))
            last = b
        self.out.append(html.escape(data[last:]))

    def result(self) -> str:
        return "".join(self.out)


def render_body(text: str, seen: set[str], src: str) -> str:
    rendered = md.markdown(text, extensions=["extra", "sane_lists", "nl2br"])
    p = _Linkify(seen, src, tokens.detect(text))
    p.feed(rendered)
    p.close()
    return p.result()


# --------------------------------------------------------------------- 라우트

@app.get("/")
def index():
    """대시보드. 사람들이 무엇을 찾았고 그래프가 어떻게 생겼는지."""
    lang = pick_lang()
    c = conn()
    cfg = click_config()

    q = lambda s_, *a_: c.execute(s_, a_).fetchall()
    thrown = c.execute("SELECT COUNT(*) n FROM response WHERE gen_model=?",
                       (llm.GEN_MODEL,)).fetchone()["n"]
    nodes = c.execute("SELECT COUNT(*) n FROM node").fetchone()["n"]
    edges = c.execute("SELECT COUNT(*) n FROM edge WHERE config_id=?",
                      (cfg,)).fetchone()["n"]

    # 가장 많이 찾은 쌍. 경로가 있는 것만 - 없는 쌍은 아래 '연결해 주세요' 로 간다.
    top = q("""SELECT a, b, COUNT(*) c, MIN(hops) h FROM search_log
               WHERE kind='path' AND status='ok'
               GROUP BY lower(a), lower(b) ORDER BY c DESC, h ASC LIMIT 10""")
    # 아직 이어지지 않은 쌍 — 도와줄 거리
    open_pairs = q("""SELECT a, b, COUNT(*) c FROM search_log
                      WHERE kind='path' AND status<>'ok'
                      GROUP BY lower(a), lower(b) ORDER BY c DESC LIMIT 6""")
    live_words = q("""SELECT a, COUNT(*) c FROM search_log WHERE kind='word'
                      GROUP BY lower(a) ORDER BY MAX(id) DESC LIMIT 18""")
    live_pairs = q("""SELECT a, b, status, hops FROM search_log WHERE kind='path'
                      ORDER BY id DESC LIMIT 10""")

    def pathrow(r):
        badge = f'<span class="pill">{r["h"]} {T(lang, "hops")}</span>'
        link = url_for("find_path", a=r["a"], b=r["b"], lang=lang)
        return (f'<li><a href="{html.escape(link)}">'
                f'{html.escape(r["a"])} <span class="arr">→</span> '
                f'{html.escape(r["b"])}</a>{badge}'
                f'<span class="cnt">{r["c"]}</span></li>')

    def openrow(r):
        link = url_for("find_path", a=r["a"], b=r["b"], lang=lang)
        return (f'<li><a href="{html.escape(link)}">'
                f'{html.escape(r["a"])} <span class="arr">⇢</span> '
                f'{html.escape(r["b"])}</a>'
                f'<span class="pill warn">{T(lang, "nolink").split("—")[0].strip()}</span></li>')

    def liverow(r):
        st = r["status"]
        tag = (f'<span class="pill">{r["hops"]} {T(lang, "hops")}</span>'
               if st == "ok" else '<span class="pill warn">·</span>')
        link = url_for("find_path", a=r["a"], b=r["b"], lang=lang)
        return (f'<li><a href="{html.escape(link)}">{html.escape(r["a"])} '
                f'<span class="arr">→</span> {html.escape(r["b"])}</a>{tag}</li>')

    empty = f'<li class="note">{T(lang, "empty")}</li>'
    body = f"""
      <h1>Seed 42</h1>
      <p class="note">{T(lang, "gsub")}</p>
      <form class="pf" action="{url_for('find_path')}" method="get">
        <input type="hidden" name="lang" value="{lang}">
        <label>{T(lang, "start")}<input name="a" placeholder="{T(lang, "ph")}"></label>
        <label>{T(lang, "goal")}<input name="b" placeholder="{T(lang, "ph")}"></label>
        <button>{T(lang, "find")}</button>
      </form>
      <div class="stats">
        <span><b>{thrown:,}</b> {T(lang, "thrown")}</span>
        <span><b>{nodes:,}</b> {T(lang, "nodes")}</span>
        <span><b>{edges:,}</b> {T(lang, "edges")}</span>
      </div>
      <div class="cols">
        <section>
          <p class="lbl">{T(lang, "toppath")}</p>
          <ul class="rows">{"".join(pathrow(r) for r in top) or empty}</ul>
          {'<p class="lbl">' + T(lang, "nolink").split("—")[0].strip() + '</p><ul class="rows">'
           + "".join(openrow(r) for r in open_pairs) + '</ul>' if open_pairs else ''}
        </section>
        <section>
          <p class="lbl">{T(lang, "livepairs")}</p>
          <ul class="rows">{"".join(liverow(r) for r in live_pairs) or empty}</ul>
          <p class="lbl">{T(lang, "livewords")}</p>
          <div class="tags">{"".join(
              f'<a href="{url_for("word", w=r["a"], lang=lang)}">{html.escape(r["a"])}</a>'
              for r in live_words) or f'<span class="note">{T(lang, "empty")}</span>'}</div>
        </section>
      </div>"""
    return respond_html("Seed 42", body, thrown, lang)


@app.get("/explore")
def explore():
    """던져본 단어 목록. 여기서 클릭해 들어가면 새 경로가 생긴다."""
    lang = pick_lang()
    n = max(1, min(request.args.get("n", 200, type=int), 5000))
    c = conn()
    total = c.execute("SELECT COUNT(*) c FROM response WHERE gen_model=?",
                      (llm.GEN_MODEL,)).fetchone()["c"]
    rows = c.execute(
        "SELECT n.word FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE r.gen_model=? ORDER BY r.id DESC LIMIT ?", (llm.GEN_MODEL, n)).fetchall()
    empty_li = f'<li class="note">{T(lang, "none")}</li>'
    items = "".join(
        f'<li><a href="{url_for("word", w=r["word"], lang=lang)}">'
        f'{html.escape(r["word"])}</a></li>' for r in rows)
    more = ""
    if n < total:
        more = (f'<p class="more"><a href="{url_for("explore", n=n + 200, lang=lang)}">'
                f'Load more ({total - n:,})</a></p>')
    body = (f'<h1>{T(lang, "explore")}</h1>'
            f'<p class="note">{T(lang, "intro")}</p>'
            f'<form class="q" action="/go" method="get">'
            f'<input name="w" placeholder="{T(lang, "ph")}" autofocus required>'
            f'<input type="hidden" name="lang" value="{lang}">'
            f'<button>{T(lang, "go")}</button></form>'
            f'<p class="lbl">{T(lang, "tried")} · {len(rows):,} / {total:,}</p>'
            f'<ul class="words">{items or empty_li}</ul>'
            f'{more}')
    return respond_html(T(lang, "explore"), body, total, lang)


@app.get("/path")
def find_path():
    lang = pick_lang()
    a = (request.args.get("a") or "").strip()
    b = (request.args.get("b") or "").strip()

    form = (
        f'<form class="pf" action="/path" method="get">'
        f'<input type="hidden" name="lang" value="{lang}">'
        f'<label>{T(lang, "start")}<input name="a" value="{html.escape(a)}" '
        f'placeholder="{T(lang, "ph")}" autofocus></label>'
        f'<label>{T(lang, "goal")}<input name="b" value="{html.escape(b)}" '
        f'placeholder="{T(lang, "ph")}"></label>'
        f'<button>{T(lang, "find")}</button></form>')

    out = ""
    if a and b:
        out = _result(a, b, lang)
    labels = {
        "hops": T(lang, "hops"), "nolink": T(lang, "nolink"),
        "unseen": T(lang, "unseen"), "nohelp": T(lang, "nohelp"),
        "throwit": T(lang, "throwit"), "explore": T(lang, "explore"),
        "seeking": T(lang, "seeking"), "lang": lang,
    }
    body = (f'<h1>{T(lang, "game")}</h1>'
            f'<p class="note">{T(lang, "gsub")}</p>{form}'
            f'<div id="out">{out}</div>'
            f'<script>const L={json.dumps(labels, ensure_ascii=False)};{GAME_JS}</script>')
    return respond_html(T(lang, "game"), body,
                        conn().execute("SELECT COUNT(*) n FROM response WHERE gen_model=?",
                                       (llm.GEN_MODEL,)).fetchone()["n"], lang)


def _chip(word: str, lang: str) -> str:
    return (f'<a class="hop" href="{url_for("word", w=word, lang=lang)}">'
            f'{html.escape(word)}</a>')


def solve(a: str, b: str, lang: str | None = None) -> dict:
    """길찾기 결과를 자료로 돌려준다. HTML 과 JSON 이 같은 로직을 쓰도록."""
    missing = [w for w in (a, b) if not has_response(w)]
    if missing:
        return {"status": "unseen", "missing": missing}
    sid, did = node_of(a), node_of(b)
    adj, rev = graph_adj()
    p = shortest(adj, rev, sid, did) if sid and did else None
    if not p:
        return {"status": "nolink", "missing": [a, b]}
    c = conn()
    words = [c.execute("SELECT word FROM node WHERE id=?", (i,)).fetchone()["word"]
             for i in p]
    return {"status": "ok", "hops": len(p) - 1, "path": words}


def solve_logged(a: str, b: str, lang: str) -> dict:
    r = solve(a, b)
    db.log_search(conn(), "path", a, b, r["status"], r.get("hops"), lang)
    return r


def _result(a: str, b: str, lang: str) -> str:
    r = solve_logged(a, b, lang)
    if r["status"] == "ok":
        chain = '<span class="arr">→</span>'.join(
            _chip(w, lang) for w in r["path"])
        return (f'<div class="box ok"><p class="big">{r["hops"]} {T(lang, "hops")}</p>'
                f'<div class="chain">{chain}</div></div>')
    key = "unseen" if r["status"] == "unseen" else "nolink"
    act = "throwit" if r["status"] == "unseen" else "explore"
    links = " ".join(
        f'<a class="cta" href="{url_for("word", w=w, lang=lang)}">'
        f'{html.escape(w)} — {T(lang, act)}</a>' for w in r["missing"])
    cls = "box" if r["status"] == "unseen" else "box warn"
    return (f'<div class="{cls}"><p class="big">{T(lang, key)}</p>'
            f'<p class="note">{T(lang, "nohelp")}</p>'
            f'<div class="ctas">{links}</div></div>')


@app.get("/api/path")
def api_path():
    from flask import jsonify
    a = (request.args.get("a") or "").strip()
    b = (request.args.get("b") or "").strip()
    if not a or not b:
        return jsonify({"status": "empty"}), 400
    return jsonify(solve_logged(a, b, pick_lang()))


@app.get("/go")
def go():
    return redirect(url_for("word", w=request.args.get("w", "").strip(),
                            lang=request.args.get("lang", "")))


@app.get("/w/<path:w>")
def word(w: str):
    lang = pick_lang()
    w = clean(w).strip()
    if not w:
        return redirect("/")
    src = request.args.get("from", "")

    text = llm.respond(w)                       # 캐시에 없으면 여기서 실제 호출
    c = conn()
    cfg = click_config()
    dst = db.node_id(c, norm(w), w, w)
    db.record_response(c, dst, text, llm.GEN_MODEL, 0.0, llm.PROMPT_VERSION)
    if src and norm(src) != norm(w):            # 클릭이 곧 엣지다
        s_ = db.node_id(c, norm(src), src, src)
        db.record_edges(c, cfg, s_, [dst], None)

    db.log_search(c, "word", w, lang=lang)
    seen = known_words()
    count = c.execute("SELECT COUNT(*) n FROM response WHERE gen_model=?",
                      (llm.GEN_MODEL,)).fetchone()["n"]
    ins = [r["word"] for r in c.execute(
        "SELECT DISTINCT s.word FROM edge e JOIN node s ON s.id=e.src_id"
        " WHERE e.config_id=? AND e.dst_id=? LIMIT 12", (cfg, dst))]
    outs = c.execute("SELECT COUNT(*) n FROM edge WHERE config_id=? AND src_id=?",
                     (cfg, dst)).fetchone()["n"]

    trail = ""
    if src:
        trail = (f'<p class="trail">← <a href="{url_for("word", w=src, lang=lang)}">'
                 f'{html.escape(src)}</a> {T(lang, "from")}</p>')
    chips = "".join(f'<span class="chip">{k} <b>{html.escape(str(v))}</b></span>'
                    for k, v in [("model", llm.GEN_MODEL), ("seed", llm.SEED),
                                 (T(lang, "chars"), len(text)),
                                 (T(lang, "indeg"), len(ins)),
                                 (T(lang, "outdeg"), outs)])
    incoming = ""
    if ins:
        incoming = (f'<p class="lbl">{T(lang, "incoming")}</p><ul class="words">'
                    + "".join(f'<li><a href="{url_for("word", w=x, lang=lang)}">'
                              f'{html.escape(x)}</a></li>' for x in ins) + "</ul>")
    body = (f"<h1>{html.escape(w)}</h1>{trail}"
            f'<div class="params">{chips}</div>'
            f'<div class="body">{render_body(text, seen, w)}</div>{incoming}')
    return respond_html(w, body, count, lang)


if __name__ == "__main__":
    import threading
    # 첫 요청이 2초 걸리는 것을 없앤다. 백그라운드로 미리 올린다.
    threading.Thread(target=lambda: graph_adj(), daemon=True).start()
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
