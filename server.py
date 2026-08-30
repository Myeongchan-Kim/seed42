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
.more{margin:18px 0 0}
.more a{display:inline-block;padding:9px 18px;border:1px solid var(--rule);
border-radius:6px;background:var(--surface);color:var(--accent);text-decoration:none;
font-size:13px}
.more a:hover{border-color:var(--accent)}
.spacer{flex:1}
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
    lang = pick_lang()
    n = max(1, min(request.args.get("n", 200, type=int), 5000))
    conn_ = conn()
    total = conn_.execute("SELECT COUNT(*) c FROM response WHERE gen_model=?",
                          (llm.GEN_MODEL,)).fetchone()["c"]
    # 최근 것부터 n 개만. 1만 개를 통째로 렌더하면 페이지가 감당이 안 된다.
    rows = conn_.execute(
        "SELECT n.word FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE r.gen_model=? ORDER BY r.id DESC LIMIT ?", (llm.GEN_MODEL, n)).fetchall()
    items = "".join(
        f'<li><a href="{url_for("word", w=r["word"])}">{html.escape(r["word"])}</a></li>'
        for r in rows)
    more = ""
    if n < total:
        nxt = min(n + 200, total)
        more = (f'<p class="more"><a href="{url_for("index", n=nxt, lang=lang)}">'
                f'Load more ({total - n:,})</a></p>')
    body = (
        f'<h1>{T(lang, "title")}</h1>'
        f'<p class="note">{T(lang, "intro")}</p>'
        '<form class="q" action="/go" method="get">'
        f'<input name="w" placeholder="{T(lang, "ph")}" autofocus required>'
        f'<input type="hidden" name="lang" value="{lang}">'
        f'<button>{T(lang, "go")}</button></form>'
        f'<p class="lbl">{T(lang, "tried")} · {len(rows):,} / {total:,}</p>'
        f'<ul class="words">{items or empty}</ul>'
        f'{more}')
    return respond_html(T(lang, "title"), body, total, lang)


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
    app.run(host="127.0.0.1", port=5001, debug=False)
