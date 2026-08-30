"""LLM 호출 계층. 키는 프로젝트 루트의 .env 에서만 읽는다 (셸 환경변수 무시).

재현성은 오직 seed 가 준다. 실측 (gemini-flash-lite-latest, 같은 프롬프트 5회):

    T=1.0, seed 없음  ->  5/5 서로 다름
    T=0.0, seed 없음  ->  5/5 서로 다름     temperature=0 만으로는 재현성이 없다
    T=*  , seed=42    ->  1/5 완전 동일

게다가 seed 를 고정하면 temperature 는 무효다 (seed=7 에서 T=0/1/2 가 모두 동일 응답).
그래서 그래프의 정체성에 들어가는 것은 temperature 가 아니라 seed 다.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

import numpy as np
from dotenv import dotenv_values

from . import db

ROOT = Path(__file__).resolve().parent.parent

SEED = 42

PROVIDERS = {
    "gemini": {
        "gen": "gemini-3.7-flash",           # 맨 단어에 대한 응답 (실험의 본질)
        "pick": "gemini-flash-lite-latest",  # 추출·정규화·판정 (4배 빠르다)
        "embed": "gemini-embedding-001",
    },
    "openai": {
        "gen": "gpt-4.1-mini",
        "pick": "gpt-4.1-mini",
        "embed": "text-embedding-3-small",
    },
}

PROVIDER = (dotenv_values(ROOT / ".env").get("PROVIDER") or "gemini").lower()
GEN_MODEL = PROVIDERS[PROVIDER]["gen"]
PICK_MODEL = PROVIDERS[PROVIDER]["pick"]
EMBED_MODEL = PROVIDERS[PROVIDER]["embed"]

# 파이프라인 버전. 프롬프트든 토크나이저든 바뀌면 그래프가 달라지므로 올린다.
#   v3: 정규식으로 조사를 떼던 한국어 전용 토크나이저
#   v4: 언어별 형태소 분석기 (ko=kiwipiepy, zh=jieba, ja/es/en=spaCy)
PROMPT_VERSION = "v4"


class CacheMiss(RuntimeError):
    """OFFLINE 상태에서 캐시에 없는 호출을 시도했다."""


OFFLINE = False  # True 면 API 를 부르지 않고 캐시에 있는 것만 쓴다

# SQLite 객체는 스레드를 넘을 수 없고, genai 클라이언트(httpx)도 스레드 간 공유하면
# "Cannot send a request, as the client has been closed" 로 죽는다. 둘 다 스레드별로 둔다.
_local = threading.local()


def _config() -> dict[str, str]:
    cfg = dotenv_values(ROOT / ".env")
    need = "GEMINI_API_KEY" if PROVIDER == "gemini" else "OPENAI_API_KEY"
    if not cfg.get(need):
        raise RuntimeError(f"{ROOT/'.env'} 에 {need} 가 없습니다.")
    return cfg


def client():
    c = getattr(_local, "client", None)
    if c is None:
        cfg = _config()
        if PROVIDER == "gemini":
            from google import genai
            c = genai.Client(api_key=cfg["GEMINI_API_KEY"])
        else:
            from openai import OpenAI
            c = OpenAI(api_key=cfg["OPENAI_API_KEY"])
        _local.client = c
    return c


def conn():
    """스레드마다 자기 연결을 갖는다. 전역 하나로 두면 Flask 가 다른 스레드에서
    요청을 처리할 때 'SQLite objects created in a thread can only be used in
    that same thread' 로 죽는다. WAL 모드라 동시 읽기는 자유롭고, 쓰기는
    timeout 안에서 직렬화된다."""
    c = getattr(_local, "conn", None)
    if c is None:
        c = _local.conn = db.connect()
    return c


# --------------------------------------------------------------- 제공자 흡수

def chat(model: str, prompt: str, temperature: float = 0.0,
         seed: int | None = None) -> str:
    if PROVIDER == "gemini":
        from google.genai import types
        r = client().models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature, seed=SEED if seed is None else seed),
        )
        return r.text or ""
    r = client().chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=temperature, seed=SEED if seed is None else seed,
    )
    return r.choices[0].message.content or ""


def embed_raw(model: str, texts: list[str]) -> list[list[float]]:
    if PROVIDER == "gemini":
        r = client().models.embed_content(model=model, contents=texts)
        return [e.values for e in r.embeddings]
    r = client().embeddings.create(model=model, input=texts)
    return [d.embedding for d in r.data]


# ------------------------------------------------------------------- 캐시

def _key_hash(key: dict) -> str:
    blob = json.dumps(key, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _cached(kind: str, key: dict, compute):
    """호출 원장 겸 캐시. 같은 단어는 항상 같은 결과 -> 그래프가 고정된다."""
    h = _key_hash(key)
    got = db.cache_get(conn(), kind, h)
    if got is not None:
        return got
    if OFFLINE:
        raise CacheMiss(f"{kind} {h}")
    value = compute()
    rest = dict(key)
    model = rest.pop("model", None)
    temp = rest.pop("temperature", None)
    params = {x: rest.pop(x) for x in ("k", "v", "seed") if x in rest}
    db.cache_put(conn(), kind, h, value, model=model, temperature=temp,
                 params=params, inp=rest)
    return value


# ------------------------------------------------------------- 단어 적격성

# 프롬프트만으로는 새는 것이 있어 실측으로 모은 안전망.
GENERIC = {
    "종류", "방법", "특징", "개념", "요소", "결과", "과정", "상황", "맥락",
    "목표", "계획", "정보", "내용", "예시", "설명", "활용", "중요성", "구체적",
    "다양성", "필요성", "관련", "부분", "경우", "수준", "정도", "질문", "답변",
    "요청", "안내", "대화", "궁금증", "궁금", "도움", "제공", "참고", "추가",
    "문의", "이해", "의미", "적용", "사용", "문제", "주제", "표현", "역할",
    "products", "types",
}

_HANGUL_OR_WORD = re.compile(r"^[가-힣A-Za-z0-9]+$")


def is_generic(word: str) -> bool:
    w = word.strip().lower()
    if w in GENERIC:
        return True
    n = len(w)  # "복수복수" 같은 정규화 아티팩트 (같은 말이 두 번)
    return n >= 4 and n % 2 == 0 and w[: n // 2] == w[n // 2 :]


def is_valid_word(word: str) -> bool:
    """노드가 될 만한 단어인가. 판정은 형태소 분석기가 한다 (number.tokens).
    여기서는 길이와 총칭어만 걸러 순환 참조를 피한다."""
    w = word.strip()
    return bool(w) and 2 <= len(w) <= 30 and not is_generic(w)


# ------------------------------------------------------------------ 생성·추출

def respond(word: str, temperature: float = 0.0) -> str:
    """맨 단어 하나만 던진다. 시스템 프롬프트 없음 - 실험의 본질이 되는 호출.

    캐시 키에 temperature 를 넣지 않는다. seed 를 고정하면 temperature 는 응답에
    영향이 없음을 실측했으므로(seed=7 에서 T=0/1/2 가 동일), 키에 넣으면 같은 응답을
    여러 벌 저장하고 캐시 미스만 늘어난다."""
    key = {"model": GEN_MODEL, "word": word, "seed": SEED}
    return _cached("respond", key, lambda: chat(GEN_MODEL, word, temperature))


# 맨 단어를 던지면 LLM 은 흔히 "더 구체적인 맥락을 알려주시면 안내해 드리겠습니다"
# 같은 상투구를 붙인다. 이를 막지 않으면 추출기가 본문이 아니라 상투구를 캐서
# 종류·계획·구체적·안내 같은 내용 없는 허브 단어가 쏟아지고, 그래프가 의미 없는
# 지름길로 가짜 small-world 가 된다.
_EXTRACT = (
    "다음 텍스트에서 핵심 개념을 정확히 {k}개 뽑아라.\n"
    "규칙:\n"
    "- **띄어쓰기 없는 한 단어 명사만**. 두 단어 이상이면 버리고 다른 것을 골라라.\n"
    "  (X: '에너지 생성', '세포 소기관', '산화적 인산화'  /  O: '에너지', '소기관', '인산화')\n"
    "- 입력 주제어 자신은 제외\n"
    "- 서로 최대한 다양하게 (같은 것의 동의어 나열 금지)\n"
    "- **내용어만**. 그 주제에 고유한 것이어야 한다.\n"
    "- 대화 상투구에서 뽑지 마라 (질문·안내·요청·추가 설명 제안 등)\n"
    "- 아무 주제에나 붙는 총칭어 금지: 종류, 방법, 특징, 개념, 요소, 결과,\n"
    "  과정, 상황, 맥락, 목표, 계획, 정보, 내용, 예시, 설명, 활용, 중요성\n"
    "- 쉼표로만 구분한 한 줄. 번호·설명·따옴표 금지.\n\n"
    "텍스트:\n{text}"
)


def extract_words(text: str, k: int = 12) -> list[str]:
    """긴 응답 -> 이웃 K개. 노드 하나의 차수를 고정해야 탐색이 성립한다."""
    snippet = text[:6000]
    key = {"model": PICK_MODEL, "v": PROMPT_VERSION, "k": k, "text": snippet,
           "seed": SEED}

    def compute() -> list[str]:
        raw = chat(PICK_MODEL, _EXTRACT.format(k=k, text=snippet))
        out, seen = [], set()
        for part in raw.replace("\n", ",").split(","):
            w = part.strip().strip("\"'·-*0123456789. ").strip()
            if w and w.lower() not in seen and is_valid_word(w):
                seen.add(w.lower())
                out.append(w)
        return out[:k]

    return _cached("extract", key, compute)


_CANON = (
    "다음 각 항목을 한국어 표준 용어로 정규화하라.\n"
    "- 영어·약어·이표기는 가장 널리 쓰이는 한국어 표기로 (단 ATP, DNA 처럼 "
    "한국어에서도 약어로 굳은 것은 약어 그대로)\n"
    "- **띄어쓰기 없는 한 단어**로. 붙여 쓸 수 없으면 핵심 명사 하나만 남겨라.\n"
    "- 이미 표준 한국어 한 단어면 그대로\n"
    "- 입력과 같은 개수를, 입력 순서대로, 한 줄에 하나씩. 번호·설명 금지.\n\n"
    "{items}"
)


def canonical(words: list[str]) -> list[str]:
    """같은 개념이 언어·표기 때문에 다른 노드가 되는 것을 막는다.
    임베딩 코사인은 번역쌍(ATP~아데노신 삼인산 0.11)과 별개 개념(ATP~NADH 0.51)을
    구분하지 못하므로, 표기 정규화를 임베딩보다 앞단에서 해야 한다."""
    if not words:
        return []
    key = {"model": PICK_MODEL, "v": PROMPT_VERSION, "words": words, "seed": SEED}

    def compute() -> list[str]:
        raw = chat(PICK_MODEL, _CANON.format(items="\n".join(words)))
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if len(lines) != len(words):  # 개수가 어긋나면 원본 유지가 안전
            return words
        return lines

    return _cached("canon", key, compute)


# ------------------------------------------------------------------ 정책·판정

_PICK = (
    "'{current}' 에서 출발해 '{target}' 로 가는 연상 사슬을 만들고 있다.\n"
    "아래 후보 중 '{target}' 에 가장 빨리 다가갈 수 있는 단어 하나만 골라라.\n"
    "후보: {cands}\n\n"
    "고른 단어 하나만 그대로 출력. 설명 금지."
)


def pick_toward(current: str, target: str, candidates: list[str]) -> str:
    """aware 정책: LLM 이 목표어를 알고 다리 단어를 고른다."""
    key = {"model": PICK_MODEL, "cur": current, "tgt": target,
           "cands": candidates, "seed": SEED}
    return _cached("pick", key, lambda: chat(PICK_MODEL, _PICK.format(
        current=current, target=target, cands=", ".join(candidates))).strip())


_JUDGE = (
    "두 표현이 같은 대상·개념을 가리키는가?\n"
    "A: {a}\nB: {b}\n\n"
    "표기·언어·축약이 달라도 같은 것을 가리키면 YES.\n"
    "상위/하위 개념이거나 단지 관련이 있을 뿐이면 NO.\n"
    "YES 또는 NO 한 단어만 출력."
)


def same_concept(a: str, b: str) -> bool:
    """도달 판정. 임베딩 코사인은 짧은 단어에서 척도가 압축돼(동의어도 ~0.30)
    절대 임계값으로 쓸 수 없다. 순위용으로만 쓰고 판정은 여기서 한다."""
    key = {"model": PICK_MODEL, "a": a, "b": b, "seed": SEED}
    return _cached("judge", key, lambda: chat(
        PICK_MODEL, _JUDGE.format(a=a, b=b)).strip().upper().startswith("YES"))


# 후보를 <c>태그로 감싸고 번호로 답하게 한다. 예전엔 "목표:/후보:" 라벨을 썼는데
# 후보 단어 자체가 "목표"일 때 모델이 라벨과 혼동해 거짓 양성을 냈다.
_FIND = (
    "<찾는것>{target}</찾는것>\n\n"
    "<후보목록>\n{cands}\n</후보목록>\n\n"
    "후보 중 <찾는것>과 **같은 대상**을 가리키는 것이 있으면 그 번호만 출력.\n"
    "표기·언어·약어만 다른 경우만 해당 (예: Berserk = 베르세르크).\n"
    "상위 범주(애니메이션·만화), 하위 사례, 창작자, 소재, 단순 연관은 모두 해당 없음.\n"
    "없으면 NONE 만 출력. 숫자 하나 또는 NONE 외에는 아무것도 출력하지 마라."
)


def find_target(cands: list[str], target: str) -> str | None:
    """후보 전체를 한 번에 훑는 1차 판정. 재현율은 높지만 정밀도가 낮아
    (상위 범주를 통과시킨다) 반드시 same_concept 으로 2차 확인해야 한다."""
    if not cands:
        return None
    key = {"model": PICK_MODEL, "v": 2, "cands": cands, "target": target,
           "seed": SEED}
    numbered = "\n".join(f"{i+1}. <c>{c}</c>" for i, c in enumerate(cands))
    got = _cached("find", key, lambda: chat(
        PICK_MODEL, _FIND.format(target=target, cands=numbered)).strip())
    m = re.match(r"^\s*(\d+)", got or "")
    if not m:
        return None
    i = int(m.group(1)) - 1
    return cands[i] if 0 <= i < len(cands) else None


def confirmed_target(cands: list[str], target: str) -> str | None:
    """2단 게이트. 배치 판정이 지목한 뒤 짝 판정이 동의해야만 도달로 친다.
    배치는 '애니메이션 = 베르세르크' 같은 상위 범주를 통과시키지만
    짝 판정은 이를 정확히 걸러낸다."""
    hit = find_target(cands, target)
    if hit is None:
        return None
    return hit if same_concept(hit, target) else None


_PRED = (
    "어떤 단어 하나만 입력받으면 사람들은 <대상>{word}</대상> 을 떠올리거나 언급하게 된다.\n"
    "그런 입력 단어 후보를 {k}개 대라.\n"
    "- **띄어쓰기 없는 한 단어 명사만**\n"
    "- <대상> 을 설명할 때 자연스럽게 함께 나오는 단어, 상위 주제, 인접 분야\n"
    "- 서로 최대한 다른 방향에서 (한 분야에 몰지 마라)\n"
    "- <대상> 자신과 그 표기 변형은 제외\n"
    "- 종류·방법·의미 같은 아무데나 붙는 총칭어 금지\n"
    "- 쉼표로만 구분한 한 줄. 번호·설명 금지."
)


def predecessors(word: str, k: int = 8) -> list[str]:
    """역방향 탐색용 선행어 후보. 어떤 단어의 '들어오는 이웃'은 열거할 수 없으므로
    생성해서 제안받고, 호출한 쪽이 실제 확장으로 검증한다.
    실측 정확도 45% — 니치한 대상일수록 지어낸다."""
    key = {"model": PICK_MODEL, "v": PROMPT_VERSION, "word": word, "k": k,
           "seed": SEED}

    def compute() -> list[str]:
        raw = chat(PICK_MODEL, _PRED.format(word=word, k=k))
        out, seen = [], set()
        for part in raw.replace("\n", ",").split(","):
            w = part.strip().strip("\"'·-*0123456789. ").strip()
            if w and w.lower() not in seen and is_valid_word(w):
                seen.add(w.lower())
                out.append(w)
        return out[:k]

    return _cached("pred", key, compute)


# ------------------------------------------------------------------- 임베딩

def embed(words: list[str]) -> np.ndarray:
    """L2 정규화된 임베딩 행렬. 벡터는 float32 BLOB 으로 저장한다."""
    c = conn()
    missing = [w for w in dict.fromkeys(words)
               if db.embed_get(c, EMBED_MODEL, w) is None]
    if missing and OFFLINE:
        raise CacheMiss(f"embed {missing[:3]}")
    for i in range(0, len(missing), 64):
        batch = missing[i : i + 64]
        for w, vec in zip(batch, embed_raw(EMBED_MODEL, batch)):
            v = np.array(vec, dtype=np.float32)
            db.embed_put(c, EMBED_MODEL, w, v.tobytes(), len(v))
    c.commit()
    m = np.array([np.frombuffer(db.embed_get(c, EMBED_MODEL, w), dtype=np.float32)
                  for w in words])
    return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)


def similarity(words: list[str], target: str) -> np.ndarray:
    """각 단어와 목표어의 코사인 유사도. 순위용으로만 쓴다."""
    if not words:
        return np.zeros(0, dtype=np.float32)
    m = embed(words + [target])
    return m[:-1] @ m[-1]
