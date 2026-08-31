# MC number

두 단어 사이의 **연상 사슬 홉 수**. 에르되시 수·베이컨 수와 같은 구조다.

    MC number("TCA cycle", "베르세르크") = 두 단어를 잇는 최단 연상 사슬의 길이

## 실험이 묻는 것

LLM 에게 맥락 없이 단어 하나만 던지면 긴 답변이 나온다. 그 답변에 등장한 단어를
다시 던지면 사슬이 이어진다. 이 사슬이 **인간관계처럼 발산해서 어디든 닿는가**,
아니면 **주제 안에 갇혀 다른 영역으로 못 넘어가는가?**

밀그램의 6단계 실험과 같은 질문이고, 밀그램이 그랬듯 두 개로 갈린다.

- **연결성(connectivity)** — 짧은 경로가 *존재하는가*
- **탐색가능성(navigability)** — 전체 지도 없이 그 경로를 *찾아낼 수 있는가*

실측 결과 둘은 크게 다르다. `TCA cycle ↔ 베르세르크` 는 8홉으로 이어져 있지만,
온라인 탐색으로는 찾지 못했다. 관측을 쌓은 뒤 BFS 로 재야 실제 거리가 나온다.

## 쓰는 법

    cp .env.example .env      # GEMINI_API_KEY 채우기
    uv venv && uv pip install -r requirements.txt
    .venv/bin/python -m spacy download en_core_web_sm   # es/ja 도 필요하면 함께

    python server.py               # Seed 42 — 클릭 탐색, http://127.0.0.1:5001
    python crawl.py --seed-file seeds.txt --frontier --hours 2 --workers 12
    python crawl.py --status
    python path.py "TCA cycle" "베르세르크"
    python graph_report.py

키는 **`.env` 에서만** 읽는다. 셸 환경변수는 보지 않는다.

## 구조

    number/llm.py      제공자 추상화(Gemini/OpenAI), 호출 원장 겸 캐시
    number/db.py       SQLite 스키마
    number/tokens.py   언어별 형태소 분석기
    number/graph.py    그래프 지표
    server.py          클릭으로 걷는 탐색 (4개 언어 UI)
    crawl.py           병렬 배치 크롤러 (재개 가능)
    retokenize.py      캐시된 응답 재분석 (API 호출 없음)
    path.py            누적 그래프에서 BFS 최단경로
    introspect.py      LLM 의 자기 연상 내성 정확도
    langpull.py        언어별 영어 흡인력
    seeds_live.py      실제로 유통되는 키워드를 시드로 수집

확장 한 단계는 단어 하나를 던져 긴 답변을 받고, 그 본문에 등장한 **모든 명사**를
이웃으로 삼는다. 응답은 `(모델, 단어, seed)` 로 캐싱되므로 그래프는 확률과정이 아니라
고정된 하나의 그래프다. 토크나이저를 바꾸면 API 호출 없이 `retokenize.py` 로 다시
훑을 수 있다.

## 저장 계층

모든 LLM 호출을 파라미터와 함께 `number.db` (SQLite) 에 남긴다. 캐시이자 감사 기록이고,
그 위에 그래프를 세운다.

    llm_call      모든 호출의 원장 (kind, model, temperature, params, input, output)
    embedding     float32 BLOB (JSON 으로 넣으면 비대해진다)
    node          개념 하나 = 노드 하나. key 는 정규화된 형태
    surface       그 노드로 관측된 원표기들 (mitochondria / 미토콘드리아)
    graph_config  엣지의 정체성을 정하는 파라미터 묶음
    response      맨 단어 -> 긴 답변. config 와 무관하게 보관
    edge          config 에 종속. K 마다 따로 저장한다
    nonedge       검증에서 거짓으로 드러난 관계
    run           탐색 실행 기록 = MC number 측정치의 누적

설계의 중심 사실: **그래프는 파라미터에 종속적이다.** 엣지는 '세계에 대한 사실'이
아니라 특정 `graph_config` 에 속한 관측이다. 자세한 근거는 FINDINGS.md 참조.

    python migrate.py              # 옛 파일 캐시 -> DB (여러 번 돌려도 안전)
    python backfill.py 12 40       # 캐시된 응답을 그래프로 펼친다 (API 호출 없음)
    python backfill.py 12 40 --online
    python graph_report.py         # 쌓인 그래프의 현재 상태
    python viewer.py               # 정적 뷰어 (K별 추출 결과 비교)
    python server.py               # 클릭으로 걷는 탐색 -> http://127.0.0.1:5001
    python recache.py              # 캐시 키를 바꾼 뒤 response 로 다시 채운다

`llm.OFFLINE = True` 로 두면 API 를 부르지 않고 캐시에 있는 것만 쓴다.

## 알게 된 것

측정 결과와 기각된 결과는 **FINDINGS.md** 에 모아둔다. 작업하면서 계속 갱신한다.

요약하면 — 원래 질문("발산이냐 그룹핑이냐")은 잘못된 이분법이었고 답은 둘 다였다
(군집계수 0.277 / 밀도 0.021 / 최대강연결성분 65%). 진짜 병목은 니치한 대상의
**진입차수**이고 그것은 K 가 정한다. 그래서 MC number 는 K 없이 말하면 무의미하다.
클러스터 사이의 다리는 의미가 아니라 **중의성**이 놓는다 (숙신산→肅愼山, 마력=馬力/魔力).
그리고 LLM 은 자기 연상 구조를 45% 만 안다.

## 클릭 탐색 (server.py)

응답 본문의 단어를 누르면 그것이 다음 쿼리가 된다. 본문에 등장하는 **모든 명사가
이웃**이므로 니치한 대상도 진입 엣지를 갖는다.

**클릭이 곧 엣지다.** A 의 응답에서 B 를 누르면 A→B 가 기록된다. K 가 정의되지 않는
모드라 `k=0` 인 별도 `graph_config` 로 분리한다. 이미 던져본 단어는 다른 색으로 보인다.

한국어 토큰은 조사·어미를 떼고 명사로 보이는 것만 링크한다. 어미 한 글자로 거르면
`미토콘드리아`(아), `에너지`(지), `은하`(하) 처럼 명사 끝소리와 부딪히므로, 어간까지
포함한 형태(`하며`, `되는`, `한다`)로만 판단한다.

## 배포

Compute Engine VM 한 대에 Caddy + waitress + systemd 로 올린다.
크롤은 systemd timer 가 매일 돌린다 (`deploy/` 참조).

    bash deploy/setup.sh           # VM 초기 설치 (여러 번 실행해도 안전)

`.env` 에 필요한 것:

    GEMINI_API_KEY=...
    PUBLIC_URL=https://<도메인>     # 없으면 공유 버튼을 숨긴다
    CF_API_TOKEN=...               # Caddy 의 DNS-01 인증서 발급용

인증서는 DNS-01 로 받는다. Cloudflare 프록시를 켜면 HTTP-01 검증이 막힐 수 있다.
