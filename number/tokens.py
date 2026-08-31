"""응답 본문에서 이웃 단어를 뽑는다. 언어별 형태소 분석기를 쓴다.

이전에는 한국어 조사를 정규식으로 뗐는데, 명사 끝소리와 부딪혀 계속 땜질해야 했다
('말부터'->'말', '효과'가 '효'로, '은하'가 용언 어간으로 오인). 품사 태거는
"명사만" 이라고 말하면 되므로 그 규칙들이 통째로 사라진다.

도구 선택은 실측으로 정했다:
  ko  kiwipiepy   spaCy ko 는 '미토+콘드리아+는' 처럼 형태소를 +로 이어 붙여 못 쓴다
  zh  jieba       spaCy zh 는 '线粒体'를 '线'+'粒体'로 자르고 '细胞'를 동사로 태깅한다
  ja  spaCy       양호
  es  spaCy       양호
  en  spaCy       양호

K 로 상위 몇 개를 자르지 않는다. 본문에 나온 명사 전부가 이웃이다.
"""
from __future__ import annotations

import re
import threading

# 문자 범위로 언어를 가른다. 짧은 단어에도 통하고 모델을 안 띄워도 된다.
_RE = {
    "ko": re.compile(r"[가-힣]"),
    "ja": re.compile(r"[぀-ゟ゠-ヿ]"),          # 가나. 한자는 zh 와 겹쳐 단독으로 못 쓴다
    "zh": re.compile(r"[一-鿿]"),
    "en": re.compile(r"[A-Za-z]"),
}
# 스페인어 표지. 라틴 문자를 영어와 공유하므로 고유 글자·기능어로 가른다.
_ES_HINT = re.compile(r"[ñáéíóúü¿¡]|\b(?:de|la|el|los|las|que|con|para|una?)\b", re.I)

TOKEN = re.compile(r"[가-힣]+|[一-鿿]+|[぀-ゟ゠-ヿ]+|[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\-]*")

_lock = threading.Lock()
_nlp: dict[str, object] = {}


def detect(text: str) -> str:
    """본문의 언어. 문자 빈도로 정한다."""
    n = {k: len(r.findall(text)) for k, r in _RE.items()}
    if n["ko"] > 5:
        return "ko"
    if n["ja"] > 5:                       # 가나가 있으면 일본어
        return "ja"
    if n["zh"] > 5:
        return "zh"
    if n["en"] > 5:
        return "es" if len(_ES_HINT.findall(text)) >= 3 else "en"
    return "en"


def _load(lang: str):
    """모델은 무겁다. 쓰는 언어만 처음 한 번 올린다."""
    with _lock:
        if lang in _nlp:
            return _nlp[lang]
        if lang == "ko":
            from kiwipiepy import Kiwi
            obj = Kiwi()
        elif lang == "zh":
            import jieba
            import jieba.posseg as pseg
            jieba.setLogLevel(60)
            obj = pseg
        else:
            import warnings
            import spacy
            warnings.filterwarnings("ignore")
            name = {"ja": "ja_core_news_sm", "es": "es_core_news_sm",
                    "en": "en_core_web_sm"}[lang]
            # parser 를 켠다. 없으면 t.children 이 비어 복합어를 못 만들고
            # 'black hole' 에서 'hole' 만 남아 엉뚱한 엣지가 생긴다. 2.2배 느리다.
            obj = spacy.load(name, disable=["ner"])
        _nlp[lang] = obj
        return obj


# 내용이 없는 것들. 최소로 유지한다.
#
# 의존명사·조수사는 kiwi 가 NNB 로 태깅하므로 여기 넣을 필요가 없다
# ('간'은 liver 일 때 NNG, '사이'일 때 NNB / '수'는 number 일 때 NNG,
#  '할 수 있다'일 때 NNB). 목록으로 막으면 진짜 명사까지 함께 죽는다 -
# 처음에 간·물·성·인·화·점·말을 넣었다가 전부 잃을 뻔했다.
JUNK = {
    # 조사·어미가 명사로 잘못 분석된 것
    "은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "로", "와",
    "과", "르", "야", "요", "죠",
    # NNG 로 나오지만 내용이 없는 것
    "것", "때", "예", "등", "뿐", "듯", "따위", "및",
    "one", "two", "three", "first", "second", "next", "last", "part",
    "example", "way", "thing", "kind", "type", "case", "time", "year",
}


def spans(text: str, lang: str | None = None) -> list[tuple[int, int, str]]:
    """(시작, 끝, 표제어) 목록. 본문에서의 위치를 함께 준다 - 뷰어가 그 자리에
    링크를 걸어야 하므로 표제어만으로는 부족하다."""
    lang = lang or detect(text)
    nlp = _load(lang)
    out: list[tuple[int, int, str]] = []

    if lang == "ko":
        # SH(한자)를 빼면 한국어 본문의 한자 표기가 통째로 사라진다.
        # '산소' 응답의 酸素·山所·省墓 가 전부 버려지고 있었다.
        #
        # 한 글자 명사도 받는다. 질·뇌·폐·간·눈·물·불·빛·꿈·힘·법·돈 처럼
        # 한국어에는 한 글자 명사가 많아 len>=2 로 자르면 통째로 사라진다.
        # 대신 의존명사와 조사 오분석이 딸려오므로 JUNK 로 막는다.
        for t in nlp.tokenize(text):
            if t.tag in ("NNG", "NNP", "SH") or (t.tag == "SL" and len(t.form) >= 2):
                out.append((t.start, t.start + t.len, t.form))
    elif lang == "zh":
        pos = 0
        for w, flag in nlp.cut(text):
            if (flag.startswith(("n", "eng")) and len(w) >= 2
                    and not flag.startswith("nr")):      # nr=인명, 잡음이 많다
                out.append((pos, pos + len(w), w))
            pos += len(w)
    else:
        doc = nlp(text)
        for t in doc:
            if (t.pos_ not in ("NOUN", "PROPN") or t.is_stop
                    or len(t.text) < 2 or t.like_num):
                continue
            # 복합어가 있으면 그것을 쓰고 낱개 명사는 넣지 않는다.
            # 'a black hole' 에서 'hole' 만 남기면 '중력 -> 구멍' 같은 가짜
            # 엣지가 생긴다. 본문이 말한 것은 'black hole' 이다.
            # 자신이 다른 명사의 수식어라면 그 복합어에 흡수되므로 따로 넣지 않는다.
            # 넣으면 'event horizon' 과 'event' 가 둘 다 노드가 되어 쪼개진다.
            if (t.dep_ in ("compound", "amod") and t.head is not t
                    and t.head.pos_ in ("NOUN", "PROPN")):
                continue
            mods = [c for c in t.children
                    if c.dep_ in ("compound", "amod")
                    and c.pos_ in ("NOUN", "PROPN", "ADJ") and not c.is_stop]
            if mods:
                st = min(m.i for m in mods)
                span = doc[st : t.i + 1]
                if len(span) <= 3 and span.text.strip():
                    out.append((span.start_char, span.end_char, span.text))
                    continue
            out.append((t.idx, t.idx + len(t.text), t.lemma_ or t.text))

    return [(a, b, w) for a, b, w in out
            if w.lower() not in JUNK and not w.isdigit()]


def neighbors(text: str, exclude: str = "", lang: str | None = None) -> list[str]:
    """본문에 나온 순서대로, 중복 없이."""
    seen = {exclude.strip().lower()} if exclude else set()
    out = []
    for _, _, w in spans(text, lang):
        k = w.lower()
        if k not in seen:
            seen.add(k)
            out.append(w)
    return out


def is_word(token: str) -> bool:
    """단어 하나가 노드가 될 만한가. 시드·클릭 입력을 거르는 데 쓴다."""
    t = token.strip()
    if len(t) < 2 or t.isdigit() or t.lower() in JUNK:
        return False
    return bool(spans(t))


def clean(token: str) -> str:
    """표기 그대로 쓴다. 조사 제거는 형태소 분석기가 맡는다."""
    return token.strip()


_NORM = re.compile(r"[\s\-_·]+")


def norm(w: str) -> str:
    """노드 키. 표기 흔들림(공백·하이픈)만 없앤다."""
    return _NORM.sub("", w.strip().lower())
