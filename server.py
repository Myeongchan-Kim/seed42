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
import random
import re
import threading
import time
import urllib.parse as U
from html.parser import HTMLParser
from pathlib import Path

import markdown as md
from dotenv import dotenv_values
from flask import Flask, redirect, request, url_for

from number import db, llm, tokens
from number.tokens import clean, is_word, norm

app = Flask(__name__)

CLICK_K = 0  # 클릭 탐색 = K 없음
ROOT_ENV = Path(__file__).resolve().parent / ".env"

# 공유 링크에 쓸 공개 주소. 없으면 공유 버튼을 숨긴다 -
# 127.0.0.1 링크는 남에게 보내봐야 열리지 않는다.
PUBLIC_URL = (dotenv_values(ROOT_ENV).get("PUBLIC_URL") or "").rstrip("/")


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
    "swap":     {"en": "Swap", "ko": "바꾸기", "zh": "交换", "es": "Intercambiar"},
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
    "badword":  {"en": "One word or one name, please — not a sentence",
                 "ko": "문장 말고 단어 하나(또는 이름 하나)를 넣어주세요",
                 "zh": "请输入一个词或一个名称，而不是句子",
                 "es": "Una palabra o un nombre, no una frase"},
    "unseen":   {"en": "not thrown yet", "ko": "아직 던져본 적 없는 단어",
                 "zh": "还没有投出过", "es": "aún no lanzada"},
    "throwit":  {"en": "Throw it first", "ko": "먼저 던져보기",
                 "zh": "先投出", "es": "Lánzala primero"},
    "explore":  {"en": "Explore", "ko": "탐색하기", "zh": "探索", "es": "Explorar"},
    "seeking":  {"en": "Searching…", "ko": "찾는 중…", "zh": "查找中…",
                 "es": "Buscando…"},
    "share":    {"en": "Share", "ko": "공유", "zh": "分享", "es": "Compartir"},
    "slogan":   {"en": "How far apart are two words inside an AI?",
                 "ko": "AI의 머릿속에서 두 단어는 얼마나 멀까?",
                 "zh": "在 AI 的联想里，两个词相隔多远？",
                 "es": "¿Qué tan lejos están dos palabras dentro de una IA?"},
    "chall":    {"en": "Can you find a shorter path?",
                 "ko": "더 짧은 길을 찾아보세요",
                 "zh": "你能找到更短的路径吗？",
                 "es": "¿Puedes encontrar un camino más corto?"},
    "ogdesc":   {"en": "Throw a word at an AI, follow what comes back. "
                       "Every word connects — the question is how far.",
                 "ko": "AI에게 단어 하나를 던지고 돌아온 말을 따라간다. "
                       "모든 단어는 이어져 있다 — 문제는 얼마나 머냐다.",
                 "zh": "向 AI 投出一个词，顺着回应走下去。所有词都相连——问题是有多远。",
                 "es": "Lanza una palabra a una IA y sigue lo que vuelve. "
                       "Todo se conecta — la pregunta es qué tan lejos."},
    "copied":   {"en": "Link copied", "ko": "링크 복사됨", "zh": "链接已复制",
                 "es": "Enlace copiado"},
    "copylink": {"en": "Copy link", "ko": "링크 복사", "zh": "复制链接",
                 "es": "Copiar enlace"},
    "newrec":   {"en": "New record! Leave your name",
                 "ko": "신기록! 이름을 남겨주세요",
                 "zh": "新纪录！留下你的名字", "es": "¡Nuevo récord! Deja tu nombre"},
    "save":     {"en": "Save", "ko": "저장", "zh": "保存", "es": "Guardar"},
    "held":     {"en": "record by", "ko": "기록 보유", "zh": "纪录保持",
                 "es": "récord de"},
    "records":  {"en": "Records", "ko": "기록", "zh": "纪录", "es": "Récords"},
    "top1":     {"en": "Top 1% — almost nothing is this far apart!",
                 "ko": "상위 1% — 이만큼 먼 쌍은 거의 없습니다!",
                 "zh": "前 1% — 几乎没有这么远的词对！",
                 "es": "Top 1% — ¡casi nada está tan lejos!"},
    "top5":     {"en": "Top 5% farthest", "ko": "상위 5% 먼 거리",
                 "zh": "最远的前 5%", "es": "Top 5% más lejanas"},
    "top10":    {"en": "Top 10% farthest", "ko": "상위 10% 먼 거리",
                 "zh": "最远的前 10%", "es": "Top 10% más lejanas"},
    "typical":  {"en": "About average", "ko": "평범한 거리",
                 "zh": "普通距离", "es": "Distancia típica"},
    "dash":     {"en": "Dashboard", "ko": "대시보드", "zh": "仪表板", "es": "Panel"},
    "toppath":  {"en": "Most searched", "ko": "인기 경로",
                 "zh": "热门路径", "es": "Más buscadas"},
    "farthest": {"en": "Farthest apart", "ko": "가장 먼 경로",
                 "zh": "距离最远", "es": "Más lejanas"},
    "nofar":    {"en": "Nothing this far yet — find a pair {n} hops apart!",
                 "ko": "아직 없습니다 — {n}홉 넘게 떨어진 쌍을 찾아보세요!",
                 "zh": "还没有这么远的 — 找一对相隔 {n} 跳的词吧！",
                 "es": "Nada tan lejos aún — ¡encuentra un par a {n} saltos!"},
    "paths":    {"en": "Paths", "ko": "경로 모아보기", "zh": "路径", "es": "Rutas"},
    "more":     {"en": "See all", "ko": "더보기", "zh": "查看全部", "es": "Ver todo"},
    "s_far":    {"en": "Farthest", "ko": "가장 먼", "zh": "最远", "es": "Más lejanas"},
    "s_far_en": {"en": "Farthest (English)", "ko": "영어끼리 가장 먼",
                 "zh": "最远（英文）", "es": "Más lejanas (inglés)"},
    "faren":    {"en": "Farthest, English only", "ko": "영어끼리 가장 먼 경로",
                 "zh": "最远的英文词对", "es": "Más lejanas solo en inglés"},
    "farensub": {"en": "Both ends English — the path may still cross languages",
                 "ko": "양 끝이 영어인 쌍. 경로는 다른 언어를 지날 수 있다",
                 "zh": "两端都是英文 — 路径仍可能跨语言",
                 "es": "Ambos extremos en inglés — el camino puede cruzar idiomas"},
    "s_oneway": {"en": "One-way", "ko": "일방통행", "zh": "单行道", "es": "Un sentido"},
    "s_open":   {"en": "Unconnected", "ko": "연결 없음", "zh": "未连接",
                 "es": "Sin conectar"},
    "s_shared": {"en": "Shared", "ko": "공유됨", "zh": "已分享", "es": "Compartidas"},
    "s_top":    {"en": "Popular", "ko": "인기", "zh": "热门", "es": "Populares"},
    "s_recent": {"en": "Recent", "ko": "최근", "zh": "最近", "es": "Recientes"},
    "shared":   {"en": "Most shared", "ko": "많이 공유된 경로",
                 "zh": "分享最多", "es": "Más compartidas"},
    "asym":     {"en": "One-way streets", "ko": "돌아오지 못하는 길",
                 "zh": "单行道", "es": "Calles de un solo sentido"},
    "asymsub":  {"en": "A→B is short, B→A is not",
                 "ko": "가기는 쉬운데 돌아오기는 어려운 쌍",
                 "zh": "去容易，回来难", "es": "Ir es fácil, volver no"},
    "unreach":  {"en": "no way back", "ko": "돌아올 길 없음",
                 "zh": "无法返回", "es": "sin regreso"},
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


def respond_html(title: str, body: str, count: int, lang: str, og: str = ""):
    """언어 선택을 쿠키에 기억한다."""
    from flask import make_response
    r = make_response(page(title, body, count, lang, og))
    if request.args.get("lang") in LANGS:
        r.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return r


SWAP_JS = r"""
(function () {
  const f = document.querySelector('form.pf'), s = document.getElementById('swap');
  if (!f || !s) return;
  // 출발/도착 맞바꾸기. 비대칭이 큰 쌍이 많아 반대 방향을 바로 보고 싶을 때 쓴다.
  s.addEventListener('click', () => {
    const t = f.a.value; f.a.value = f.b.value; f.b.value = t;
    if (f.a.value.trim() && f.b.value.trim()) f.submit(); else f.a.focus();
  });
})();
"""

GAME_JS = r"""
const form = document.querySelector('form.pf');
const out = document.getElementById('out');

const swapBtn = document.getElementById('swap');
if (swapBtn && form) swapBtn.addEventListener('click', () => {
  const t = form.a.value; form.a.value = form.b.value; form.b.value = t;
  if (form.a.value.trim() && form.b.value.trim())
    form.requestSubmit ? form.requestSubmit() : form.submit();
  else form.a.focus();
});

// 경로의 홉에 마우스를 올리면 다음 단어가 본문 어디에서 나왔는지 보여준다.
const tipEl = document.createElement('div');
tipEl.className = 'tip'; tipEl.hidden = true;
document.body.appendChild(tipEl);
const cache = new Map();
let tipFor = null;

async function showTip(el) {
  const a = el.dataset.w, b = el.dataset.next;
  if (!a || !b) return;
  tipFor = el;
  const key = a + '|' + b;
  let d = cache.get(key);
  if (!d) {
    tipEl.textContent = L.seeking; place(el);
    try {
      d = await (await fetch('/api/snippet?a=' + encodeURIComponent(a) +
        '&b=' + encodeURIComponent(b))).json();
    } catch { d = {ok: false}; }
    cache.set(key, d);
  }
  if (tipFor !== el) return;
  tipEl.textContent = '';
  if (!d.ok) { tipEl.textContent = '\u2014'; }
  else {
    const h = document.createElement('div');
    h.className = 'tiphead'; h.textContent = a; tipEl.appendChild(h);
    const body = document.createElement('div');
    body.append(d.before);
    const m = document.createElement('mark'); m.textContent = d.match;
    body.appendChild(m); body.append(d.after);
    tipEl.appendChild(body);
  }
  place(el);
}
function place(el) {
  tipEl.hidden = false;
  const r = el.getBoundingClientRect();
  const w = Math.min(420, window.innerWidth - 24);
  tipEl.style.width = w + 'px';
  let left = Math.max(12, Math.min(r.left + r.width / 2 - w / 2,
                                   window.innerWidth - w - 12));
  tipEl.style.left = left + 'px';
  const h = tipEl.offsetHeight, above = r.top > h + 16;
  tipEl.style.top = (above ? r.top - h - 10 : r.bottom + 10) + window.scrollY + 'px';
}
function hideTip() { tipEl.hidden = true; tipFor = null; }

function bind(root) {
  root.querySelectorAll('a.hop[data-next]').forEach(el => {
    el.addEventListener('mouseenter', () => showTip(el));
    el.addEventListener('focus', () => showTip(el));
    el.addEventListener('mouseleave', hideTip);
    el.addEventListener('blur', hideTip);
  });
  const rec = root.querySelector('#recform');
  if (rec) rec.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = rec.querySelector('button'); btn.disabled = true;
    const res = await (await fetch('/api/record', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({a: rec.dataset.a, b: rec.dataset.b,
                            name: rec.name.value})
    })).json();
    rec.textContent = res.ok
      ? L.held + ' ' + (res.name || '—') + ' · ' + res.hops + ' ' + L.hops
      : L.held + ' ' + (res.holder || '—');
  });
  root.querySelectorAll('.sh[data-to]').forEach(el => {
    el.addEventListener('click', () => {
      // 링크가 새 탭으로 나가므로 sendBeacon 으로 보낸다. 페이지가 떠나도 남는다.
      const p = JSON.stringify({a: el.dataset.a, b: el.dataset.b,
                                to: el.dataset.to, hops: +el.dataset.hops});
      if (navigator.sendBeacon)
        navigator.sendBeacon('/api/share', new Blob([p], {type: 'application/json'}));
      else fetch('/api/share', {method: 'POST', keepalive: true,
                 headers: {'Content-Type': 'application/json'}, body: p});
    });
  });
  const more = root.querySelector('#shmore');
  if (more) more.addEventListener('click', async () => {
    const url = more.dataset.url, text = more.dataset.text;
    if (navigator.share) { try { await navigator.share({title: 'Seed 42', text, url}); return; } catch {} }
    try { await navigator.clipboard.writeText(url); more.textContent = L.copied; } catch {}
  });
}
bind(document);

form.addEventListener('submit', async e => {
  const a = form.a.value.trim(), b = form.b.value.trim();
  if (!a || !b) return;
  e.preventDefault();
  out.innerHTML = '<div class="box seeking"><p class="big">' + L.seeking + '</p></div>';
  history.replaceState(null, '', '/path?a=' + encodeURIComponent(a) +
    '&b=' + encodeURIComponent(b) + '&lang=' + L.lang);
  try {
    const r = await (await fetch('/api/path?a=' + encodeURIComponent(a) +
      '&b=' + encodeURIComponent(b))).json();
    out.innerHTML = r.html || '';
  } catch (err) {
    out.innerHTML = '<div class="box warn"><p class="big">' + err + '</p></div>';
  }
  bind(out);
});
"""


# --------------------------------------------------------------------- 길찾기

_G: dict = {"cfg": None, "adj": None, "rev": None, "rowid": 0}
_G_lock = threading.Lock()


def graph_adj():
    """인접 리스트를 메모리에 올려둔다. 요청마다 DB 에서 다 읽으면 7초라 게임이 안 된다.

    갱신은 새로 들어온 엣지만 덧붙인다. 예전에는 '엣지가 5% 늘면 다시 읽기'였는데,
    사용자가 클릭으로 만든 엣지 몇 개는 5%(7만 개)에 한참 못 미쳐 영원히 반영되지
    않았다 - 직접 걸어서 만든 길을 길찾기가 못 찾았다.
    MAX(rowid) 확인은 0ms, COUNT(*) 는 30ms 라 rowid 를 기준으로 쓴다."""
    c = conn()
    cfg = click_config()
    top = c.execute("SELECT MAX(rowid) x FROM edge").fetchone()["x"] or 0
    with _G_lock:
        # ok=0 인 노드는 뺀다. 옛 토크나이저가 만든 잔재('땀을', 'rises')가
        # 경로에 끼면 사슬이 말이 안 된다. 실측상 빼도 손해가 거의 없다 -
        # 무작위 300쌍 중 끊긴 것 1개, 평균 홉 +0.22.
        Q = ("SELECT e.src_id, e.dst_id FROM edge e"
             " JOIN node s ON s.id=e.src_id JOIN node d ON d.id=e.dst_id"
             " WHERE e.config_id=? AND s.ok IS NOT 0 AND d.ok IS NOT 0")
        if _G["adj"] is None or _G["cfg"] != cfg:
            adj: dict[int, list[int]] = {}
            rev: dict[int, list[int]] = {}
            for a, b in c.execute(Q, (cfg,)):
                adj.setdefault(a, []).append(b)
                rev.setdefault(b, []).append(a)
            _G.update(cfg=cfg, adj=adj, rev=rev, rowid=top)
        elif top > _G["rowid"]:                     # 새로 생긴 것만 덧붙인다
            adj, rev = _G["adj"], _G["rev"]
            for a, b in c.execute(Q + " AND e.rowid>?", (cfg, _G["rowid"])):
                adj.setdefault(a, []).append(b)
                rev.setdefault(b, []).append(a)
            _G["rowid"] = top
        return _G["adj"], _G["rev"]


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


# 무거운 통계는 백그라운드에서만 계산한다. 요청 중에 계산하면 캐시가 만료된
# 그 한 번의 요청이 전부를 뒤집어쓴다 - 대시보드 한 번이 BFS 를 880회 돌려
# 20초, 심하면 Cloudflare 100초 한도를 넘겨 524 가 났다.
# 요청은 마지막으로 계산된 값을 그냥 읽는다. 없으면 없는 대로 보여준다.
STATS_EVERY = 600.0        # 백그라운드 재계산 주기
DIST_SAMPLE = 150          # 홉 분포 표본. 그래프가 커져 500 은 비싸다
ASYM_SCAN = 40             # 비대칭을 볼 쌍 수

_DIST: dict = {"at": 0.0, "vals": []}


def hop_distribution(n: int = DIST_SAMPLE, compute: bool = False) -> list[int]:
    """무작위 쌍의 홉 분포. 백분위를 진짜 수치로 말하기 위한 것.
    그래프가 자라면 분포가 변하므로 하드코딩하지 않고 다시 잰다 (600쌍에 1초)."""
    if not compute:
        return _DIST["vals"]               # 요청은 마지막 값만 읽는다
    adj, rev = graph_adj()
    pool = list(adj.keys())
    if len(pool) < 50:
        return []
    rng = random.Random(42)
    vals = []
    for _ in range(n):
        a, b = rng.sample(pool, 2)
        p_ = shortest(adj, rev, a, b, cap=60_000)
        if p_:
            vals.append(len(p_) - 1)
    vals.sort()
    _DIST.update(at=time.time(), vals=vals)
    return vals


def far_threshold(p: float = 0.10) -> int:
    """'가장 먼 경로' 에 올릴 최소 홉 수. 무작위 쌍 중 상위 p 에 드는 값.

    고정 숫자로 박으면 그래프가 자랄 때 어긋난다. 지금은 중앙값이 3~4홉이라
    5홉짜리는 자랑거리가 못 된다 - 절반 가까이가 그만큼 떨어져 있다."""
    vals = hop_distribution()
    if not vals:
        return 6                           # 아직 계산 전 - 기본값
    n = len(vals)
    for h in sorted(set(vals)):
        if sum(1 for v in vals if v >= h) / n <= p:
            return h
    return max(vals)


_OPEN: dict = {"at": 0.0, "rows": []}


def still_open(limit: int = 6, compute: bool = False) -> list[dict]:
    """아직 이어지지 않은 쌍. 기록만 보면 안 되고 지금 다시 풀어봐야 한다 -
    그래프가 자라 이미 이어진 쌍을 '도와주세요' 로 계속 보여주고 있었다."""
    if not compute:
        return _OPEN["rows"][:limit]
    c = conn()
    adj, rev = graph_adj()
    seen, out = set(), []
    for r in c.execute("""SELECT a, b, COUNT(*) c FROM search_log
                          WHERE kind='path' AND status<>'ok'
                          GROUP BY lower(a), lower(b)
                          ORDER BY c DESC, MAX(id) DESC LIMIT ?""", (ASYM_SCAN,)):
        k = (r["a"].lower(), r["b"].lower())
        if k in seen:
            continue
        seen.add(k)
        ia, ib = node_of(r["a"]), node_of(r["b"])
        if ia and ib and shortest(adj, rev, ia, ib):
            continue                       # 그사이 이어졌다
        out.append({"a": r["a"], "b": r["b"], "c": r["c"]})
    _OPEN.update(at=time.time(), rows=out)
    return out[:limit]


_ASYM: dict = {"at": 0.0, "rows": []}


def asymmetric_pairs(limit: int = 6, compute: bool = False) -> list[dict]:
    """A→B 는 가까운데 B→A 는 멀거나 아예 없는 쌍.

    상호성이 0.068 이라 대부분의 연상은 일방통행이다. 그 성질이 눈에 보이게
    한다. 사람들이 실제로 찾아본 쌍만 대상으로 하고, 반대 방향은 여기서 푼다."""
    if not compute:
        return _ASYM["rows"][:limit]
    c = conn()
    adj, rev = graph_adj()
    seen, out = set(), []
    for r in c.execute("""SELECT a, b FROM search_log WHERE kind='path'
                          AND status='ok' GROUP BY lower(a), lower(b)
                          ORDER BY MAX(id) DESC LIMIT ?""", (ASYM_SCAN,)):
        a, b = r["a"], r["b"]
        k = tuple(sorted((a.lower(), b.lower())))
        if k in seen:
            continue
        seen.add(k)
        ia, ib = node_of(a), node_of(b)
        if not ia or not ib:
            continue
        pf = shortest(adj, rev, ia, ib)
        pb = shortest(adj, rev, ib, ia)
        if not pf:
            continue
        fwd = len(pf) - 1
        back = len(pb) - 1 if pb else None
        gap = 99 if back is None else back - fwd
        if gap >= 2:
            out.append({"a": a, "b": b, "fwd": fwd, "back": back, "gap": gap})
    out.sort(key=lambda r: (-r["gap"], r["fwd"]))
    _ASYM.update(at=time.time(), rows=out)
    return out[:limit]


def rarity(hops: int) -> float | None:
    """이 거리보다 먼 무작위 쌍의 비율. 0.01 이면 상위 1%."""
    vals = hop_distribution()
    if not vals:
        return None
    return sum(1 for v in vals if v >= hops) / len(vals)


def node_of(word: str):
    r = conn().execute("SELECT id FROM node WHERE lower(word)=lower(?)",
                       (word.strip(),)).fetchone()
    return r["id"] if r else None


def mentions(src: str, dst: str) -> bool:
    """src 의 응답이 실제로 dst 를 언급하는가. 클릭 엣지를 남기기 전에 확인한다."""
    r = conn().execute(
        "SELECT r.text FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE lower(n.word)=lower(?) AND r.gen_model=? LIMIT 1",
        (src.strip(), llm.GEN_MODEL)).fetchone()
    if not r:
        return False
    d = norm(dst)
    return any(norm(w) == d for w in tokens.neighbors(r["text"]))


def has_response(word: str) -> bool:
    return conn().execute(
        "SELECT 1 FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE lower(n.word)=lower(?) AND r.gen_model=? LIMIT 1",
        (word.strip(), llm.GEN_MODEL)).fetchone() is not None


# ------------------------------------------------------- 사전 최장일치

_VOCAB: dict = {"rowid": -1, "words": set(), "maxlen": 2}


def vocab():
    """이미 그래프에 있는 단어들. 본문에서 이것들을 최장일치로 잡는다.

    형태소 분석기만으로는 'black hole' 을 잡아도 'event horizon' 을 놓치는 식으로
    들쭉날쭉하다. 반면 한 번이라도 노드가 된 말은 확실히 하나의 단위다.
    그래서 파서 결과 위에 사전 일치를 덧대고, 겹치면 긴 쪽을 쓴다.

    다중 패턴이라 KMP(패턴 하나)가 아니라, 토큰 경계에서 시작하는 후보를
    긴 것부터 집합 조회한다. 응답 하나가 1~2천 자라 이 방식으로 충분히 빠르다.
    """
    c = conn()
    top = c.execute("SELECT MAX(rowid) x FROM node").fetchone()["x"] or 0
    if _VOCAB["rowid"] == top:
        return _VOCAB["words"], _VOCAB["maxlen"]
    ws = {r["word"].lower() for r in c.execute(
        "SELECT word FROM node WHERE length(word) >= 4 AND instr(word, ' ') > 0")}
    _VOCAB.update(rowid=top, words=ws,
                  maxlen=max((len(w) for w in ws), default=2))
    return ws, _VOCAB["maxlen"]


def merge_known(text: str, spans: list) -> list:
    """파서가 준 구간 위에 사전 최장일치를 덧댄다. 겹치면 긴 쪽이 이긴다."""
    ws, maxlen = vocab()
    if not ws:
        return spans
    starts = sorted({a for a, _, _ in spans})
    hits = []
    for a in starts:
        best = None
        for b in range(min(len(text), a + min(maxlen, 60)), a, -1):
            cand = text[a:b]
            if len(cand) >= 4 and cand.lower() in ws:
                best = (a, b, cand)
                break
        if best:
            hits.append(best)
    if not hits:
        return spans
    merged = sorted(spans + hits, key=lambda s: (s[0], -(s[1] - s[0])))
    out, last = [], -1
    for a, b, w in merged:
        if a >= last:
            out.append((a, b, w))
            last = b
    return out


def refresh_stats() -> None:
    """백그라운드에서만 부른다. 요청 경로는 compute=False 로 읽기만 한다."""
    hop_distribution(compute=True)
    asymmetric_pairs(50, compute=True)
    still_open(50, compute=True)


def stats_loop() -> None:
    """통계 갱신과 WAL 정리를 함께 맡는다.

    크롤이 안 도는 동안에도 사람들의 클릭이 WAL 을 키운다. 읽는 쪽이 계속 붙어
    있으면 체크포인트가 굶어 무한정 자라므로(실측 7.7GB) 여기서 주기적으로 민다.
    TRUNCATE 는 읽는 연결이 있으면 실패하니 PASSIVE 로 되는 만큼만 반영한다."""
    while True:
        try:
            graph_adj()
            refresh_stats()
        except Exception as e:                      # 통계가 죽어도 사이트는 산다
            print(f"[stats] {e}", flush=True)
        try:
            n = db.wal_pages(conn())
            if n > 20000:                           # 약 80MB 넘으면 알린다
                print(f"[wal] {n} pages", flush=True)
        except Exception as e:
            print(f"[wal] {e}", flush=True)
        time.sleep(STATS_EVERY)


# --------------------------------------------------------------- 경로 목록

# 정렬 방식만 다르고 나머지는 같다. 대시보드는 각 5개를 보여주고 나머지는
# /paths?sort=... 로 넘긴다.
SORTS = ("far", "far_en", "oneway", "open", "shared", "top", "recent")


_LANG_CACHE: dict[str, str] = {}


def is_en(word: str) -> bool:
    """이 단어가 영어 노드인가. key 로 조회한다 - node.key 에는 UNIQUE 인덱스가
    있어 즉시 찾지만, word 로 lower() JOIN 하면 전체 스캔이 된다."""
    k = norm(word)
    v = _LANG_CACHE.get(k)
    if v is None:
        r = conn().execute("SELECT lang FROM node WHERE key=?", (k,)).fetchone()
        v = (r["lang"] if r and r["lang"] else "?")
        _LANG_CACHE[k] = v
    return v == "en"


def path_rows(sort: str, limit: int) -> list[dict]:
    c = conn()
    if sort == "oneway":
        return [dict(r) for r in asymmetric_pairs(limit)]
    if sort == "open":
        return [dict(r) for r in still_open(limit)]
    if sort == "far_en":
        # 양 끝이 모두 영어인 쌍. 경로 자체는 언어를 건널 수 있다.
        #
        # node.word 로 JOIN 하면 안 된다. 그 컬럼에 인덱스가 없고 lower() 를
        # 씌우면 있어도 못 쓴다 - 83만 행 전체 스캔이라 쿼리 하나가 418초 걸려
        # 대시보드가 통째로 멈췄다. 먼저 후보를 뽑고 파이썬에서 거른다.
        rows = c.execute(
            """SELECT a, b, MIN(hops) h, COUNT(1) c FROM search_log
               WHERE kind='path' AND status='ok'
               GROUP BY lower(a), lower(b) ORDER BY h DESC, MAX(id) DESC
               LIMIT 300""").fetchall()
        out = []
        for r in rows:
            if is_en(r["a"]) and is_en(r["b"]):
                out.append(dict(r))
                if len(out) >= limit:
                    break
        return out
    if sort == "far":
        fth = far_threshold()
        return [dict(r) for r in c.execute(
            """SELECT a, b, MIN(hops) h, COUNT(1) c FROM search_log
               WHERE kind='path' AND status='ok'
               GROUP BY lower(a), lower(b) HAVING h >= ?
               ORDER BY h DESC, MAX(id) DESC LIMIT ?""", (fth, limit))]
    if sort == "shared":
        return [dict(r) for r in c.execute(
            """SELECT a, b, COUNT(1) c, MIN(hops) h FROM search_log
               WHERE kind='share' GROUP BY lower(a), lower(b)
               ORDER BY c DESC, MAX(id) DESC LIMIT ?""", (limit,))]
    if sort == "top":
        return [dict(r) for r in c.execute(
            """SELECT a, b, COUNT(1) c, MIN(hops) h FROM search_log
               WHERE kind='path' AND status='ok'
               GROUP BY lower(a), lower(b) ORDER BY c DESC, h ASC LIMIT ?""",
            (limit,))]
    return [dict(r) for r in c.execute(                     # recent
        """SELECT a, b, status, hops AS h FROM search_log WHERE kind='path'
           ORDER BY id DESC LIMIT ?""", (limit,))]


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
form.pf button.swap{font-size:17px;padding:8px 12px;background:var(--surface);
color:var(--muted);border:1px solid var(--rule);border-radius:6px;cursor:pointer;
line-height:1;align-self:flex-end;margin-bottom:1px}
form.pf button.swap:hover{border-color:var(--accent);color:var(--accent)}
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
.pill.big{font-size:13px;padding:3px 11px;font-weight:500}
ul.rows.far li{padding:10px 0}
ul.rows.far li a{font-size:15px}
a.seemore{font-size:11px;color:var(--accent);text-decoration:none;
letter-spacing:0;text-transform:none;font-weight:400;margin-left:6px}
a.seemore:hover{text-decoration:underline}
.tabs{display:flex;gap:5px;flex-wrap:wrap;margin:16px 0 18px}
.tabs a{font-size:13px;padding:6px 13px;border:1px solid var(--rule);border-radius:99px;
color:var(--muted);text-decoration:none;background:var(--surface)}
.tabs a:hover{border-color:var(--accent);color:var(--accent)}
.tabs a.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);
font-weight:500}
a.revlink{color:var(--faint);text-decoration:none;font-size:13px;padding:0 2px}
a.revlink:hover{color:var(--accent)}
.cnt{font-family:var(--mono);font-size:11px;color:var(--faint);min-width:20px;
text-align:right;font-variant-numeric:tabular-nums}
.tags{display:flex;flex-wrap:wrap;gap:5px}
.tags a{font-size:13px;padding:4px 10px;border:1px solid var(--rule);border-radius:99px;
color:var(--ink);text-decoration:none;background:var(--surface)}
.tags a:hover{border-color:var(--accent);color:var(--accent)}
.tier{margin-left:12px;font-size:12px;padding:3px 10px;border-radius:99px;
background:var(--accent-soft);color:var(--accent);vertical-align:middle;
font-family:var(--sans);font-weight:500;letter-spacing:0}
.tier.top1{background:#f6e4b8;color:#7a5200}
.sharebar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:16px;
padding-top:14px;border-top:1px solid var(--rule)}
.shlbl{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint)}
a.sh,button.sh{font:inherit;font-size:12px;padding:6px 13px;border:1px solid var(--rule);
border-radius:99px;background:var(--surface);color:var(--muted);text-decoration:none;
cursor:pointer}
a.sh:hover,button.sh:hover{border-color:var(--accent);color:var(--accent)}
form.rec{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:14px;
font-size:13px}
form.rec input{font:inherit;font-size:13px;padding:6px 11px;border:1px solid var(--rule);
border-radius:6px;background:var(--ground);color:var(--ink);width:150px}
form.rec button{font:inherit;font-size:13px;padding:6px 14px;border:1px solid var(--accent);
background:var(--accent);color:var(--ground);border-radius:6px;cursor:pointer}
.tip{position:absolute;z-index:50;background:var(--surface);border:1px solid var(--rule);
border-radius:8px;padding:12px 14px;font-size:13px;line-height:1.65;color:var(--ink);
box-shadow:0 6px 24px rgba(0,0,0,.13);pointer-events:none;white-space:pre-wrap;
word-break:break-word;max-height:220px;overflow:hidden}
.tiphead{font-family:var(--mono);font-size:11px;color:var(--faint);
margin-bottom:6px;letter-spacing:.04em}
.tip mark{background:var(--accent-soft);color:var(--accent);font-weight:600;
padding:1px 3px;border-radius:3px}
a.hop[data-next]{cursor:help}
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


def og_tags(title: str, desc: str, url: str) -> str:
    """링크 미리보기 카드. 없으면 X·Facebook·LinkedIn 에서 밋밋한 URL 만 나온다."""
    def m(prop, val, attr="property"):
        return f'<meta {attr}="{prop}" content="{html.escape(val)}">'
    return (m("og:site_name", "Seed 42") + m("og:type", "website")
            + m("og:title", title) + m("og:description", desc)
            + (m("og:url", url) if url else "")
            + m("twitter:card", "summary", "name")
            + m("twitter:title", title, "name")
            + m("twitter:description", desc, "name"))


def page(title: str, body: str, count: int, lang: str = "en",
         og: str = "") -> str:
    picker = "".join(
        f'<a class="lang{" on" if code == lang else ""}" '
        f'href="?lang={code}">{name}</a>'
        for code, name in LANGS.items())
    return (f"{HEAD}<title>{html.escape(title)}</title>{og}"
            f'<header><a class="home" href="/">Seed 42</a>'
            # 길찾기 폼은 대시보드(/)에 이미 있어 헤더 버튼은 중복이다.
            # 대신 /paths 를 둔다 - 대시보드의 '더보기' 로만 갈 수 있어
            # 다른 페이지에서는 접근할 길이 없었다.
            f'<a class="navlink" href="{url_for("paths", lang=lang)}">'
            f'{T(lang, "paths")}</a>'
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
        for a, b, lemma in merge_known(data, tokens.spans(data, self.lang)):
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
    top = path_rows("top", 5)
    # 가장 멀리 떨어진 쌍. 인기는 '무엇이 궁금했나'지만 거리는 '그래프가 어떻게
    # 생겼나'라서, 니치한 대상이나 언어를 건너는 경로가 여기 올라온다.
    # 흔한 거리는 올리지 않는다. 분포에서 상위 10% 컷을 뽑아 그 이상만 본다.
    # 그중 20개를 모아 무작위 5개 - 전부 보여주면 매번 같아 다시 볼 이유가 없다.
    fth = far_threshold()
    # 상위 20 중 무작위 5개. 전부 보여주면 매번 같은 목록이라 다시 볼 이유가 없다.
    far = path_rows("far", 20)
    far = random.sample(far, min(5, len(far)))
    far.sort(key=lambda r: -r["h"])
    asym = asymmetric_pairs(5)
    far_en = path_rows("far_en", 5)
    shared = path_rows("shared", 5)
    open_pairs = still_open(5)
    live_words = q("""SELECT a, COUNT(*) c FROM search_log WHERE kind='word'
                      GROUP BY lower(a) ORDER BY MAX(id) DESC LIMIT 18""")
    live_pairs = path_rows("recent", 5)

    def pathrow(r):
        badge = f'<span class="pill">{r["h"]} {T(lang, "hops")}</span>'
        link = url_for("find_path", a=r["a"], b=r["b"], lang=lang)
        return (f'<li><a href="{html.escape(link)}">'
                f'{html.escape(r["a"])} <span class="arr">→</span> '
                f'{html.escape(r["b"])}</a>{badge}'
                f'<span class="cnt">{r["c"]}</span></li>')

    def seemore(sort):
        return (f' <a class="seemore" href="{url_for("paths", sort=sort, lang=lang)}">'
                f'{T(lang, "more")} →</a>')

    def hoprow(r, big=False):
        cls = "pill big" if big else "pill"
        link = url_for("find_path", a=r["a"], b=r["b"], lang=lang)
        return (f'<li><a href="{html.escape(link)}">'
                f'{html.escape(r["a"])} <span class="arr">→</span> '
                f'{html.escape(r["b"])}</a>'
                f'<span class="{cls}">{r["h"]} {T(lang, "hops")}</span></li>')

    def openrow(r):
        link = url_for("find_path", a=r["a"], b=r["b"], lang=lang)
        return (f'<li><a href="{html.escape(link)}">'
                f'{html.escape(r["a"])} <span class="arr">⇢</span> '
                f'{html.escape(r["b"])}</a>'
                f'<span class="pill warn">{T(lang, "nolink").split("—")[0].strip()}</span></li>')

    def asymrow(r):
        fwd, back = r["fwd"], r["back"]
        tag = (f'<span class="pill warn">{T(lang, "unreach")}</span>'
               if back is None else f'<span class="pill">{back}</span>')
        link = url_for("find_path", a=r["a"], b=r["b"], lang=lang)
        rev = url_for("find_path", a=r["b"], b=r["a"], lang=lang)
        return (f'<li><a href="{html.escape(link)}">'
                f'{html.escape(r["a"])} <span class="arr">→</span> '
                f'{html.escape(r["b"])}</a>'
                f'<span class="pill">{fwd}</span>'
                f'<a class="revlink" href="{html.escape(rev)}">↩</a>{tag}</li>')

    def liverow(r):
        st = r["status"]
        tag = (f'<span class="pill">{r["h"]} {T(lang, "hops")}</span>'
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
        <button type="button" class="swap" id="swap" title="{T(lang, "swap")}"
                aria-label="{T(lang, "swap")}">⇄</button>
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
          <p class="lbl">{T(lang, "farthest")}{seemore("far")} · {fth}+ {T(lang, "hops")}</p>
          <ul class="rows far">{"".join(hoprow(r, True) for r in far)
              or f'<li class="note">{T(lang, "nofar").format(n=fth)}</li>'}</ul>
          {'<p class="lbl">' + T(lang, "faren") + seemore("far_en") + '</p>'
           '<p class="note">' + T(lang, "farensub") + '</p><ul class="rows">'
           + "".join(hoprow(r) for r in far_en) + '</ul>' if far_en else ''}
          <p class="lbl">{T(lang, "livepairs")}{seemore("recent")}</p>
          <ul class="rows">{"".join(liverow(r) for r in live_pairs) or empty}</ul>
        </section>
        <section>
          {'<p class="lbl">' + T(lang, "asym") + seemore("oneway") + '</p>'
           '<p class="note">' + T(lang, "asymsub") + '</p><ul class="rows">'
           + "".join(asymrow(r) for r in asym) + '</ul>' if asym else ''}
          {'<p class="lbl">' + T(lang, "nolink").split("—")[0].strip() + seemore("open") + '</p><ul class="rows">'
           + "".join(openrow(r) for r in open_pairs) + '</ul>' if open_pairs else ''}
          {'<p class="lbl">' + T(lang, "shared") + seemore("shared") + '</p><ul class="rows">'
           + "".join(pathrow(r) for r in shared) + '</ul>' if shared else ''}
          <p class="lbl">{T(lang, "livewords")}</p>
          <div class="tags">{"".join(
              f'<a href="{url_for("word", w=r["a"], lang=lang)}">{html.escape(r["a"])}</a>'
              for r in live_words) or f'<span class="note">{T(lang, "empty")}</span>'}</div>
          <p class="lbl">{T(lang, "toppath")}{seemore("top")}</p>
          <ul class="rows">{"".join(pathrow(r) for r in top) or empty}</ul>
        </section>
      </div>
      <script>{SWAP_JS}</script>"""
    return respond_html("Seed 42", body, thrown, lang,
                        og_tags(f'Seed 42 — {T(lang, "slogan")}',
                                T(lang, "ogdesc"), PUBLIC_URL))


@app.get("/paths")
def paths():
    """경로 목록. 정렬 방식만 다르고 화면은 같다."""
    lang = pick_lang()
    sort = request.args.get("sort", "far")
    if sort not in SORTS:
        sort = "far"
    n = max(5, min(request.args.get("n", 50, type=int), 300))
    rows = path_rows(sort, n)

    tabs = "".join(
        f'<a class="tab{" on" if k == sort else ""}" '
        f'href="{url_for("paths", sort=k, lang=lang)}">{T(lang, "s_" + k)}</a>'
        for k in SORTS)

    def row(r):
        link = url_for("find_path", a=r["a"], b=r["b"], lang=lang)
        rev = url_for("find_path", a=r["b"], b=r["a"], lang=lang)
        bits = ""
        if sort == "oneway":
            back = r.get("back")
            bits = (f'<span class="pill">{r["fwd"]}</span>'
                    f'<a class="revlink" href="{html.escape(rev)}">↩</a>'
                    + (f'<span class="pill warn">{T(lang, "unreach")}</span>'
                       if back is None else f'<span class="pill">{back}</span>'))
        elif sort == "open":
            bits = f'<span class="pill warn">{T(lang, "unreach")}</span>'
        else:
            if r.get("h") is not None:
                bits += f'<span class="pill">{r["h"]} {T(lang, "hops")}</span>'
            if r.get("c"):
                bits += f'<span class="cnt">{r["c"]}</span>'
        return (f'<li><a href="{html.escape(link)}">{html.escape(r["a"])} '
                f'<span class="arr">→</span> {html.escape(r["b"])}</a>{bits}</li>')

    more = ""
    if len(rows) >= n < 300:
        more = (f'<p class="more"><a href="{url_for("paths", sort=sort, n=n + 50, lang=lang)}">'
                f'Load more</a></p>')
    items = "".join(row(r) for r in rows) or '<li class="note">-</li>'
    body = (f'<h1>{T(lang, "paths")}</h1>'
            f'<nav class="tabs">{tabs}</nav>'
            f'<ul class="rows">{items}</ul>{more}')
    return respond_html(T(lang, "paths"), body, len(rows), lang)


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
        " WHERE r.gen_model=? AND n.ok IS NOT 0"
        " ORDER BY r.id DESC LIMIT ?", (llm.GEN_MODEL, n)).fetchall()
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
        f'<button type="button" class="swap" id="swap" '
        f'title="{T(lang, "swap")}" aria-label="{T(lang, "swap")}">⇄</button>'
        f'<label>{T(lang, "goal")}<input name="b" value="{html.escape(b)}" '
        f'placeholder="{T(lang, "ph")}"></label>'
        f'<button>{T(lang, "find")}</button></form>')

    labels = {
        "hops": T(lang, "hops"), "nolink": T(lang, "nolink"),
        "unseen": T(lang, "unseen"), "nohelp": T(lang, "nohelp"),
        "throwit": T(lang, "throwit"), "explore": T(lang, "explore"),
        "seeking": T(lang, "seeking"), "held": T(lang, "held"),
        "copied": T(lang, "copied"), "lang": lang,
    }
    out = ""
    og_title, og_desc = "Seed 42", T(lang, "ogdesc")
    if a and b:
        r = solve_logged(a, b, lang)
        out = _render(r, a, b, lang)
        if r["status"] == "ok":
            og_title = f'{a} → {b} · {r["hops"]} {T(lang, "hops")}'
            tk = tier_key(r.get("rarity"))
            og_desc = ((T(lang, tk) + " — " if tk and tk != "typical" else "")
                       + " → ".join(r["path"]))
        else:
            og_title, og_desc = f"{a} → {b}", T(lang, "nolink")
    url = (f"{PUBLIC_URL}/path?a={U.quote(a)}&b={U.quote(b)}"
           if PUBLIC_URL and a and b else PUBLIC_URL)
    body = (f'<h1>{T(lang, "game")}</h1>'
            f'<p class="note">{T(lang, "gsub")}</p>{form}'
            f'<div id="out">{out}</div>'
            f'<script>const L={json.dumps(labels, ensure_ascii=False)};{GAME_JS}</script>')
    return respond_html(T(lang, "game"), body,
                        conn().execute("SELECT COUNT(*) n FROM response WHERE gen_model=?",
                                       (llm.GEN_MODEL,)).fetchone()["n"], lang,
                        og_tags(og_title, og_desc, url))


def _chip(word: str, lang: str, nxt: str | None = None) -> str:
    data = f' data-w="{html.escape(word)}" data-next="{html.escape(nxt)}"' if nxt else ""
    return (f'<a class="hop"{data} href="{url_for("word", w=word, lang=lang)}">'
            f'{html.escape(word)}</a>')


def solve(a: str, b: str, lang: str | None = None) -> dict:
    """길찾기 결과를 자료로 돌려준다. HTML 과 JSON 이 같은 로직을 쓰도록."""
    # 문장은 노드가 될 수 없다. 검증을 여기서 막지 않으면 'I love MC' 가
    # unseen 으로 안내되고, 사용자가 그 안내를 따라가면 노드가 만들어진다.
    bad = [w for w in (a, b) if not tokens.is_query(w) and not has_response(w)]
    if bad:
        return {"status": "badword", "missing": bad}
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
    hops = len(p) - 1
    key = norm(a) + "\x00" + norm(b)
    prev = db.get_record(conn(), key)
    record = prev is None or hops < prev["hops"]
    return {"status": "ok", "hops": hops, "path": words,
            "rarity": rarity(hops), "record": record,
            "prev": prev["hops"] if prev else None,
            "holder": prev["finder"] if prev else None}


def solve_logged(a: str, b: str, lang: str) -> dict:
    r = solve(a, b)
    db.log_search(conn(), "path", a, b, r["status"], r.get("hops"), lang)
    return r


def tier_key(rar: float | None) -> str | None:
    if rar is None:
        return None
    return ("top1" if rar <= 0.01 else "top5" if rar <= 0.05
            else "top10" if rar <= 0.10 else "typical")


def share_bar(a: str, b: str, hops: int, lang: str,
              rar: float | None = None) -> str:
    """X·Facebook·LinkedIn 은 웹 인텐트가 있다. 인스타그램은 링크 공유용 웹
    엔드포인트가 없어서 (모바일의 Web Share API 나) 링크 복사로 처리한다."""
    if not PUBLIC_URL:
        return ""
    link = f"{PUBLIC_URL}/path?a={U.quote(a)}&b={U.quote(b)}"
    # 경로만 적으면 무슨 서비스인지 모른다. 슬로건으로 열고, 희귀한 결과면
    # 그것을 앞세우고, 마지막에 도전을 건다.
    tk = tier_key(rar)
    head = (T(lang, tk) if tk and tk != "typical" else T(lang, "slogan"))
    txt = (f"{head}\n{a} → {b} : {hops} {T(lang, 'hops')}\n"
           f"{T(lang, 'chall')} — Seed 42")
    e_l, e_t = U.quote(link, safe=""), U.quote(txt, safe="")
    outs = [
        ("X", f"https://twitter.com/intent/tweet?text={e_t}&url={e_l}"),
        ("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={e_l}"),
        ("LinkedIn", f"https://www.linkedin.com/sharing/share-offsite/?url={e_l}"),
    ]
    d = (f'data-a="{html.escape(a)}" data-b="{html.escape(b)}" '
         f'data-hops="{hops}"')
    btns = "".join(f'<a class="sh" target="_blank" rel="noopener" {d} '
                   f'data-to="{n}" href="{html.escape(u)}">{n}</a>' for n, u in outs)
    return (f'<div class="sharebar" id="sharebar">'
            f'<span class="shlbl">{T(lang, "share")}</span>{btns}'
            f'<button class="sh" type="button" id="shmore" {d} data-to="copy" '
            f'data-url="{html.escape(link)}" data-text="{html.escape(txt)}">'
            f'Instagram · {T(lang, "copylink")}</button></div>')


def _result(a: str, b: str, lang: str) -> str:
    return _render(solve_logged(a, b, lang), a, b, lang)


def _render(r: dict, a: str, b: str, lang: str) -> str:
    if r["status"] == "ok":
        p_ = r["path"]
        chain = '<span class="arr">→</span>'.join(
            _chip(w, lang, p_[i + 1] if i + 1 < len(p_) else None)
            for i, w in enumerate(p_))
        tk = tier_key(r.get("rarity"))
        badge = (f'<span class="tier {tk}">{T(lang, tk)}</span>'
                 if tk and tk != "typical" else "")
        rec = ""
        if r.get("record"):
            rec = (f'<form class="rec" id="recform" data-a="{html.escape(a)}" '
                   f'data-b="{html.escape(b)}">'
                   f'<span>{T(lang, "newrec")}</span>'
                   f'<input name="name" maxlength="24" placeholder="name">'
                   f'<button type="submit">{T(lang, "save")}</button></form>')
        elif r.get("holder"):
            rec = (f'<p class="note">{T(lang, "held")} '
                   f'<b>{html.escape(r["holder"])}</b> · {r["prev"]} {T(lang, "hops")}</p>')
        return (f'<div class="box ok"><p class="big">{r["hops"]} {T(lang, "hops")}'
                f'{badge}</p>'
                f'<div class="chain">{chain}</div>{rec}'
                f'{share_bar(a, b, r["hops"], lang, r.get("rarity"))}</div>')
    key = ("badword" if r["status"] == "badword"
           else "unseen" if r["status"] == "unseen" else "nolink")
    act = "throwit" if r["status"] == "unseen" else "explore"
    links = " ".join(
        f'<a class="cta" href="{url_for("word", w=w, lang=lang)}">'
        f'{html.escape(w)} — {T(lang, act)}</a>' for w in r["missing"])
    cls = "box" if r["status"] == "unseen" else "box warn"
    return (f'<div class="{cls}"><p class="big">{T(lang, key)}</p>'
            f'<p class="note">{T(lang, "nohelp")}</p>'
            f'<div class="ctas">{links}</div></div>')


@app.get("/api/snippet")
def api_snippet():
    """a 의 응답에서 b 가 나온 대목을 잘라 준다. 경로의 각 홉이 실제 본문
    어디에서 왔는지 보여주기 위한 것 - 경로가 진짜인지 눈으로 확인할 수 있다."""
    from flask import jsonify
    a = (request.args.get("a") or "").strip()
    b = (request.args.get("b") or "").strip()
    if not a or not b:
        return jsonify({"ok": False}), 400
    r = conn().execute(
        "SELECT r.text FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE lower(n.word)=lower(?) AND r.gen_model=? LIMIT 1",
        (a, llm.GEN_MODEL)).fetchone()
    if not r:
        return jsonify({"ok": False})
    text = r["text"]
    hit = next((sp for sp in tokens.spans(text) if sp[2].lower() == b.lower()), None)
    if hit is None:                      # 표제어가 아닌 표기로 등장했을 수 있다
        i = text.lower().find(b.lower())
        if i < 0:
            return jsonify({"ok": False})
        hit = (i, i + len(b), b)
    st, en, _ = hit
    pad = 140
    lo, hi = max(0, st - pad), min(len(text), en + pad)
    return jsonify({
        "ok": True,
        "before": ("…" if lo else "") + text[lo:st],
        "match": text[st:en],
        "after": text[en:hi] + ("…" if hi < len(text) else ""),
    })


@app.post("/api/share")
def api_share():
    """공유 버튼 클릭을 남긴다. 링크가 외부로 나가므로 sendBeacon 으로 받는다.
    search_log 를 재사용한다 - kind='share', status 에 어디로 나갔는지."""
    from flask import jsonify
    d = request.get_json(silent=True, force=True) or {}
    a, b = (d.get("a") or "").strip(), (d.get("b") or "").strip()
    to = (d.get("to") or "")[:20]
    if a and b:
        db.log_search(conn(), "share", a, b, to, d.get("hops"), pick_lang())
    return jsonify({"ok": True})


@app.post("/api/record")
def api_record():
    """더 짧은 경로를 찾은 사람의 이름을 남긴다. 서버에서 다시 풀어 확인한다 -
    클라이언트가 보낸 홉 수를 그대로 믿으면 아무 숫자나 넣을 수 있다."""
    from flask import jsonify
    d = request.get_json(silent=True) or {}
    a, b = (d.get("a") or "").strip(), (d.get("b") or "").strip()
    who = (d.get("name") or "").strip()[:24] or None
    if not a or not b:
        return jsonify({"ok": False}), 400
    r = solve(a, b)
    if r["status"] != "ok":
        return jsonify({"ok": False})
    key = norm(a) + "\x00" + norm(b)
    prev = db.get_record(conn(), key)
    if prev and r["hops"] >= prev["hops"]:
        return jsonify({"ok": False, "hops": prev["hops"], "holder": prev["finder"]})
    db.put_record(conn(), key, a, b, r["hops"], json.dumps(r["path"], ensure_ascii=False), who)
    return jsonify({"ok": True, "hops": r["hops"], "name": who})


@app.get("/api/path")
def api_path():
    from flask import jsonify
    a = (request.args.get("a") or "").strip()
    b = (request.args.get("b") or "").strip()
    if not a or not b:
        return jsonify({"status": "empty"}), 400
    lang = pick_lang()
    r = solve_logged(a, b, lang)
    # 렌더링을 JS 에 복제하지 않는다. 이스케이프도 여기서 한 번만 한다.
    r["html"] = _render(r, a, b, lang)
    return jsonify(r)


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
    # 검증을 통과한 것만 LLM 에 던진다. 안 그러면 'I love MC' 같은 문장이
    # 그대로 노드가 되어 그래프와 대시보드를 오염시킨다.
    if not tokens.is_query(w) and not has_response(w):
        body = (f'<h1>{html.escape(w)}</h1>'
                f'<div class="box warn"><p class="big">{T(lang, "badword")}</p>'
                f'<div class="ctas"><a class="cta" href="{url_for("explore", lang=lang)}">'
                f'{T(lang, "explore")}</a></div></div>')
        return respond_html(w, body, 0, lang)
    src = request.args.get("from", "")

    text = llm.respond(w)                       # 캐시에 없으면 여기서 실제 호출
    c = conn()
    cfg = click_config()
    dst = db.node_id(c, norm(w), w, w)
    c.execute("UPDATE node SET ok=? WHERE id=? AND ok IS NULL",
              (1 if tokens.is_word(w) else 0, dst))
    db.record_response(c, dst, text, llm.GEN_MODEL, 0.0, llm.PROMPT_VERSION)
    # 클릭이 곧 엣지다. 다만 from 은 사용자가 URL 로 아무 값이나 줄 수 있으므로
    # 반드시 확인한다 - 검증이 없으면 /w/베르세르크?from=TCA%20cycle 한 줄로
    # 임의의 두 단어를 1홉으로 이어붙일 수 있다 (실제로 8홉 -> 1홉이 됐다).
    if src and norm(src) != norm(w) and mentions(src, w):
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
    # 첫 요청이 2초 걸리는 것을 없앤다. 백그라운드로 미리 올린다.
    threading.Thread(target=lambda: graph_adj(), daemon=True).start()
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
