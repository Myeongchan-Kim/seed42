"""저장 계층. 모든 LLM 호출을 파라미터와 함께 남기고, 그 위에 그래프를 세운다.

설계의 중심 사실 하나: **그래프는 파라미터에 종속적이다.** 같은 단어라도
k, 모델, temperature, 프롬프트 버전이 다르면 이웃이 달라진다. 그래서 엣지는
'세계에 대한 사실'이 아니라 특정 graph_config 에 속한 관측이다.

k 를 rank 로 접어 넣는 최적화는 쓰지 않는다. 실측 결과 k=12 집합은 k=40 집합에
포함되지만(12/12) 순서는 65% 만 일치해서, k=40 의 앞 12개가 k=12 그래프가 아니다.
"""
from __future__ import annotations

import functools
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "number.db"

SCHEMA = """

-- 모든 LLM 호출의 원장. 캐시이자 감사 기록.
CREATE TABLE IF NOT EXISTS llm_call (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,      -- respond|extract|canon|judge|find|pick|pred|embed
  cache_key   TEXT NOT NULL,      -- 호출을 결정하는 모든 것의 해시
  model       TEXT,
  temperature REAL,
  params      TEXT NOT NULL,      -- 호출별 파라미터 JSON (k 등)
  input       TEXT NOT NULL,
  output      TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  UNIQUE(kind, cache_key)
);
CREATE INDEX IF NOT EXISTS ix_call_kind ON llm_call(kind, created_at);

-- 개념 하나 = 노드 하나. key 는 정규화된 형태라 mitochondria 와 미토콘드리아가 합쳐진다.
CREATE TABLE IF NOT EXISTS node (
  id        INTEGER PRIMARY KEY,
  key       TEXT NOT NULL UNIQUE,
  word      TEXT NOT NULL,
  canonical TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  lang      TEXT,             -- ko | en | zh | ja | mix. 정규화하지 않으므로 갈린다
  ok        INTEGER            -- 1=현 토크나이저가 명사로 인정. 0 이면 표시에서 뺀다
);
CREATE INDEX IF NOT EXISTS ix_node_ok ON node(ok);
CREATE INDEX IF NOT EXISTS ix_node_lang ON node(lang);

-- 그 노드로 관측된 원표기들
CREATE TABLE IF NOT EXISTS surface (
  node_id INTEGER NOT NULL REFERENCES node(id),
  text    TEXT NOT NULL,
  PRIMARY KEY (node_id, text)
);

-- 엣지의 정체성을 정하는 파라미터 묶음.
-- seed 가 들어가고 temperature 는 기록만 한다. 실측상 seed 를 고정하면
-- temperature 는 응답에 영향이 없다 (seed=7 에서 T=0/1/2 가 모두 동일).
CREATE TABLE IF NOT EXISTS graph_config (
  id             INTEGER PRIMARY KEY,
  gen_model      TEXT NOT NULL,
  temperature    REAL NOT NULL,
  extract_model  TEXT NOT NULL,
  k              INTEGER NOT NULL,
  prompt_version TEXT NOT NULL,
  seed           INTEGER NOT NULL DEFAULT -1,
  UNIQUE(gen_model, extract_model, k, prompt_version, seed)
);

-- 맨 단어를 던져 받은 긴 답변. 비싸고 권위 있는 산출물이라 config 와 무관하게 보관.
CREATE TABLE IF NOT EXISTS response (
  id             INTEGER PRIMARY KEY,
  node_id        INTEGER NOT NULL REFERENCES node(id),
  gen_model      TEXT NOT NULL,
  temperature    REAL NOT NULL,
  prompt_version TEXT NOT NULL,
  call_id        INTEGER REFERENCES llm_call(id),
  text           TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  UNIQUE(node_id, gen_model, temperature, prompt_version)
);

CREATE TABLE IF NOT EXISTS edge (
  config_id   INTEGER NOT NULL REFERENCES graph_config(id),
  src_id      INTEGER NOT NULL REFERENCES node(id),
  dst_id      INTEGER NOT NULL REFERENCES node(id),
  rank        INTEGER NOT NULL,
  response_id INTEGER REFERENCES response(id),
  created_at  TEXT NOT NULL,
  PRIMARY KEY (config_id, src_id, dst_id)
);
CREATE INDEX IF NOT EXISTS ix_edge_src ON edge(config_id, src_id);
CREATE INDEX IF NOT EXISTS ix_edge_dst ON edge(config_id, dst_id);

-- 검증에서 부정된 관계. 'A 를 던지면 B 가 나온다'가 거짓이라는 관측으로,
-- LLM 의 자기 연상 내성이 틀린 지점을 그대로 남긴다 (실측 정확도 45%).
CREATE TABLE IF NOT EXISTS nonedge (
  config_id  INTEGER NOT NULL REFERENCES graph_config(id),
  src_id     INTEGER NOT NULL REFERENCES node(id),
  dst_id     INTEGER NOT NULL REFERENCES node(id),
  source     TEXT NOT NULL,       -- predecessor_proposal 등, 어디서 나온 주장인지
  created_at TEXT NOT NULL,
  PRIMARY KEY (config_id, src_id, dst_id)
);

-- 탐색 실행 기록
CREATE TABLE IF NOT EXISTS run (
  id         INTEGER PRIMARY KEY,
  config_id  INTEGER REFERENCES graph_config(id),
  start_word TEXT NOT NULL,
  target_word TEXT NOT NULL,
  mode       TEXT NOT NULL,       -- uni | bi
  policy     TEXT NOT NULL,
  budget     INTEGER, max_depth INTEGER, seed INTEGER, basin_depth INTEGER,
  found      INTEGER NOT NULL,
  hops       INTEGER,
  path       TEXT,                -- JSON
  expanded   INTEGER, verify_cost INTEGER, basin_nodes INTEGER,
  seconds    REAL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_run_pair ON run(start_word, target_word);

-- 사람들이 무엇을 찾았는가. 대시보드(인기 경로·실시간 검색어)의 재료다.
CREATE TABLE IF NOT EXISTS search_log (
  id         INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL,          -- path | word
  a          TEXT NOT NULL,
  b          TEXT,                   -- path 일 때만
  status     TEXT,                   -- ok | nolink | unseen
  hops       INTEGER,
  lang       TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_log_kind ON search_log(kind, id);
CREATE INDEX IF NOT EXISTS ix_log_pair ON search_log(a, b);

-- 두 단어 사이 최단 기록. BFS 는 늘 현재 그래프의 최단을 주므로, 기록이 깨지는 것은
-- 그래프가 자랐다는 뜻이다 (누군가 클릭으로 엣지를 만들었다). 그래서 이것은
-- "이 거리를 누가 처음 달성했나" 의 기록이다.
CREATE TABLE IF NOT EXISTS record (
  pair       TEXT PRIMARY KEY,      -- norm(a) 와 norm(b) 를 NUL 로 이은 키
  a          TEXT NOT NULL,
  b          TEXT NOT NULL,
  hops       INTEGER NOT NULL,
  path       TEXT NOT NULL,         -- JSON
  finder     TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_record_time ON record(created_at DESC);

-- 임베딩은 숫자 색인이라 원장에 JSON 으로 넣으면 비대해진다. float32 BLOB 으로 따로.
CREATE TABLE IF NOT EXISTS embedding (
  model TEXT NOT NULL,
  text  TEXT NOT NULL,
  dim   INTEGER NOT NULL,
  vec   BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (model, text)
);
"""


def _repair_fk(conn: sqlite3.Connection) -> None:
    """존재하지 않는 graph_config_old 를 가리키는 외래키를 고친다.

    ALTER TABLE ... RENAME 은 기본 동작으로 *참조하는 쪽* 테이블들의 FK 정의까지
    따라 고친다. 마이그레이션 도중 실패해도 그 스키마 재작성은 남아서, 이후 모든
    INSERT 가 "FOREIGN KEY constraint failed" 로 죽는다. 해당 테이블만 다시 만든다."""
    # SCHEMA 에 정의된 테이블만 고친다. graph_config_old 자신은 정의에 자기 이름이
    # 들어 있어 여기 걸리는데, 재생성 대상이 아니라 그냥 버려야 할 잔해다.
    known = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA))
    bad = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND sql LIKE '%graph_config_old%'") if r["name"] in known]
    if not bad:
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA legacy_alter_table=ON")
    for t in bad:
        conn.execute(f"ALTER TABLE {t} RENAME TO {t}_bak")
    conn.executescript(SCHEMA)          # 올바른 FK 로 다시 만든다
    for t in bad:
        conn.execute(f"INSERT INTO {t} SELECT * FROM {t}_bak")
        conn.execute(f"DROP TABLE {t}_bak")
    conn.commit()
    conn.execute("PRAGMA legacy_alter_table=OFF")
    conn.execute("PRAGMA foreign_keys=ON")


def _add_lang_column(conn: sqlite3.Connection) -> None:
    """이미 있는 node 테이블에 lang 을 붙인다. ALTER TABLE ADD COLUMN 은 UNIQUE 나
    외래키를 건드리지 않아 안전하다 (graph_config 때처럼 재구축할 필요가 없다).
    새 DB 라면 node 가 아직 없으므로 아무것도 하지 않는다 - SCHEMA 가 만든다."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(node)")}
    if cols and "lang" not in cols:
        conn.execute("ALTER TABLE node ADD COLUMN lang TEXT")
        conn.commit()


def _add_ok_column(conn: sqlite3.Connection) -> None:
    """node.ok 를 붙인다. 값 채우기는 mark_ok.py 가 한다 (토크나이저가 필요해서
    여기서는 못 한다 - db 는 number.tokens 를 import 하지 않는다)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(node)")}
    if cols and "ok" not in cols:
        conn.execute("ALTER TABLE node ADD COLUMN ok INTEGER")
        conn.commit()


def _fill_lang(conn: sqlite3.Connection) -> None:
    """표기로 언어를 판정해 채운다. 정규화를 하지 않으므로 언어가 그대로 갈린다."""
    conn.execute("""
        UPDATE node SET lang = CASE
          WHEN word GLOB '*[가-힣]*' AND word GLOB '*[A-Za-z]*' THEN 'mix'
          WHEN word GLOB '*[가-힣]*' THEN 'ko'
          WHEN word GLOB '*[A-Za-z]*' THEN 'en'
          ELSE 'other' END
        WHERE lang IS NULL""")
    conn.commit()


def _upgrade(conn: sqlite3.Connection) -> None:
    """graph_config 에 seed 를 넣는다. UNIQUE 제약이 바뀌므로 테이블을 다시 만든다.

    edge/nonedge/run 이 graph_config 를 참조하므로 그동안 외래키를 끈다.
    RENAME 이 다른 테이블의 FK 정의를 따라 고치지 않도록 legacy_alter_table 을 켠다.
    옛 행(seed 개념이 없던 관측)은 seed=-1 로 남겨 새 관측과 섞이지 않게 한다."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(graph_config)")}
    if "seed" in cols or not cols:
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA legacy_alter_table=ON")
    conn.executescript("""
        CREATE TABLE graph_config_new (
          id INTEGER PRIMARY KEY, gen_model TEXT NOT NULL, temperature REAL NOT NULL,
          extract_model TEXT NOT NULL, k INTEGER NOT NULL, prompt_version TEXT NOT NULL,
          seed INTEGER NOT NULL DEFAULT -1,
          UNIQUE(gen_model, extract_model, k, prompt_version, seed));
        INSERT INTO graph_config_new (id, gen_model, temperature, extract_model, k,
                                      prompt_version, seed)
          SELECT id, gen_model, temperature, extract_model, k, prompt_version, -1
          FROM graph_config;
        DROP TABLE graph_config;
        ALTER TABLE graph_config_new RENAME TO graph_config;
    """)
    conn.commit()
    conn.execute("PRAGMA legacy_alter_table=OFF")
    conn.execute("PRAGMA foreign_keys=ON")


SCHEMA_VERSION = 7

# SQLite 는 동시 writer 를 못 견딘다. 모든 쓰기를 하나의 락으로 직렬화한다.
#
# 호출부(크롤러)에만 락을 걸면 새는 곳이 남는다 - llm.respond() 안의 캐시 쓰기가
# 락 밖이었다. 게다가 한 스레드가 트랜잭션을 열고 있으면 *다른 연결*의 쓰기가
# 그동안 막히므로, 프로세스 안 락과 열린 트랜잭션을 섞으면 오히려 더 엉킨다.
# 그래서 트랜잭션을 길게 열지 않고, 쓰기 함수 하나하나를 여기서 잠근다.
# 읽기는 WAL 덕에 잠그지 않아도 자유롭다.
WRITE = threading.Lock()


def _serialized(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        with WRITE:
            return fn(*a, **kw)
    return wrapper


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """스레드마다 하나씩 연다. 스키마 적용은 최초 한 번만 - 연결할 때마다
    executescript 를 돌리면 테이블 9개 생성 시도가 매번 쓰기 락을 잡아,
    병렬 크롤러에서 'database is locked' 가 쏟아진다."""
    # isolation_level=None (자동커밋). 기본 모드에서는 읽기로 열린 트랜잭션이
    # 쓰기로 승격될 때 SQLite 가 busy handler 를 부르지 않고 즉시 SQLITE_BUSY 를
    # 낸다(교착 회피). 그래서 busy_timeout 을 아무리 키워도 다른 프로세스에서
    # 'database is locked' 가 그대로 난다. 자동커밋이면 쓰기 락을 처음부터 잡아
    # busy_timeout 이 제대로 동작한다.
    conn = sqlite3.connect(path, timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")   # 락 대기. connect(timeout=) 보다 확실하다
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # WAL 에서는 이걸로 충분하고 훨씬 빠르다
    conn.execute("PRAGMA foreign_keys=ON")
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        _add_lang_column(conn)      # SCHEMA 의 인덱스가 이 컬럼을 참조한다
        _add_ok_column(conn)
        conn.executescript(SCHEMA)
        _upgrade(conn)
        _repair_fk(conn)
        _fill_lang(conn)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.commit()
    return conn


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ------------------------------------------------------------------ 호출 원장

def cache_get(conn: sqlite3.Connection, kind: str, cache_key: str):
    row = conn.execute(
        "SELECT output FROM llm_call WHERE kind=? AND cache_key=?", (kind, cache_key)
    ).fetchone()
    return json.loads(row["output"]) if row else None


def cache_put(conn: sqlite3.Connection, kind: str, cache_key: str, value,
              *, model=None, temperature=None, params=None, inp=None) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO llm_call"
        " (kind, cache_key, model, temperature, params, input, output, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (kind, cache_key, model, temperature,
         json.dumps(params or {}, ensure_ascii=False),
         json.dumps(inp, ensure_ascii=False),
         json.dumps(value, ensure_ascii=False), now()),
    )
    conn.commit()
    if cur.lastrowid:
        return cur.lastrowid
    row = conn.execute("SELECT id FROM llm_call WHERE kind=? AND cache_key=?",
                       (kind, cache_key)).fetchone()
    return row["id"]


# -------------------------------------------------------------------- 그래프

def _script(word: str) -> str:
    """표기로 언어를 가른다. 가나가 있으면 일본어, 한자만 있으면 중국어로 본다
    (일본어 한자 표기는 중국어와 구분되지 않으므로 가나를 표지로 쓴다)."""
    ko = any("\uac00" <= c <= "\ud7a3" for c in word)
    ja = any("\u3040" <= c <= "\u30ff" for c in word)
    zh = any("\u4e00" <= c <= "\u9fff" for c in word)
    en = any(c.isascii() and c.isalpha() for c in word)
    hits = [n for n, f in (("ko", ko), ("ja", ja), ("zh", zh), ("en", en)) if f]
    if not hits:
        return "other"
    if len(hits) > 1 and set(hits) != {"ja", "zh"}:
        return "mix"
    return "ja" if ja else hits[0]


def node_id(conn: sqlite3.Connection, key: str, word: str, canonical: str) -> int:
    lang = _script(word)
    conn.execute(
        "INSERT OR IGNORE INTO node (key, word, canonical, first_seen, lang)"
        " VALUES (?,?,?,?,?)",
        (key, word, canonical, now(), lang),
    )
    conn.execute("INSERT OR IGNORE INTO surface (node_id, text) VALUES"
                 " ((SELECT id FROM node WHERE key=?), ?)", (key, word))
    return conn.execute("SELECT id FROM node WHERE key=?", (key,)).fetchone()["id"]


def config_id(conn: sqlite3.Connection, gen_model: str, temperature: float,
              extract_model: str, k: int, prompt_version: str, seed: int) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO graph_config"
        " (gen_model, temperature, extract_model, k, prompt_version, seed)"
        " VALUES (?,?,?,?,?,?)",
        (gen_model, temperature, extract_model, k, prompt_version, seed),
    )
    return conn.execute(
        "SELECT id FROM graph_config WHERE gen_model=? AND extract_model=?"
        " AND k=? AND prompt_version=? AND seed=?",
        (gen_model, extract_model, k, prompt_version, seed),
    ).fetchone()["id"]


def record_response(conn, node: int, text: str, gen_model: str,
                    temperature: float, prompt_version: str, call_id=None) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO response"
        " (node_id, gen_model, temperature, prompt_version, call_id, text, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (node, gen_model, temperature, prompt_version, call_id, text, now()),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM response WHERE node_id=? AND gen_model=? AND temperature=?"
        " AND prompt_version=?", (node, gen_model, temperature, prompt_version),
    ).fetchone()["id"]


def record_edges(conn, cfg: int, src: int, dsts: list[int], response: int | None) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO edge"
        " (config_id, src_id, dst_id, rank, response_id, created_at) VALUES (?,?,?,?,?,?)",
        [(cfg, src, d, i + 1, response, now()) for i, d in enumerate(dsts)],
    )
    conn.commit()


def record_nonedge(conn, cfg: int, src: int, dst: int, source: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO nonedge (config_id, src_id, dst_id, source, created_at)"
        " VALUES (?,?,?,?,?)", (cfg, src, dst, source, now()))
    conn.commit()


def record_run(conn, **kw) -> int:
    cols = ("config_id start_word target_word mode policy budget max_depth seed "
            "basin_depth found hops path expanded verify_cost basin_nodes seconds").split()
    vals = [kw.get(c) for c in cols]
    if isinstance(vals[cols.index("path")], list):
        vals[cols.index("path")] = json.dumps(vals[cols.index("path")], ensure_ascii=False)
    cur = conn.execute(
        f"INSERT INTO run ({','.join(cols)}, created_at)"
        f" VALUES ({','.join('?' * len(cols))}, ?)", (*vals, now()))
    conn.commit()
    return cur.lastrowid


# ----------------------------------------------------------------- 임베딩

def embed_get(conn: sqlite3.Connection, model: str, text: str):
    row = conn.execute("SELECT vec FROM embedding WHERE model=? AND text=?",
                       (model, text)).fetchone()
    return row["vec"] if row else None


def embed_put(conn: sqlite3.Connection, model: str, text: str, vec: bytes,
              dim: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO embedding (model, text, dim, vec, created_at)"
        " VALUES (?,?,?,?,?)", (model, text, dim, vec, now()))


# 쓰기 경로를 빠짐없이 직렬화한다 (위 WRITE 주석 참조).
for _name in ("cache_put", "embed_put", "node_id", "config_id", "record_response",
              "record_edges", "record_nonedge", "record_run"):
    globals()[_name] = _serialized(globals()[_name])


def find_config(conn: sqlite3.Connection, gen_model: str, extract_model: str,
                k: int, prompt_version: str, seed: int) -> int | None:
    """조회 전용. config_id 와 달리 없으면 만들지 않는다 - 읽기만 하는 곳에서
    쓰기 락을 잡지 않기 위해서다."""
    row = conn.execute(
        "SELECT id FROM graph_config WHERE gen_model=? AND extract_model=?"
        " AND k=? AND prompt_version=? AND seed=?",
        (gen_model, extract_model, k, prompt_version, seed)).fetchone()
    return row["id"] if row else None


def log_search(conn, kind: str, a: str, b: str | None = None,
               status: str | None = None, hops: int | None = None,
               lang: str | None = None) -> None:
    conn.execute(
        "INSERT INTO search_log (kind, a, b, status, hops, lang, created_at)"
        " VALUES (?,?,?,?,?,?,?)", (kind, a, b, status, hops, lang, now()))


log_search = _serialized(log_search)


def get_record(conn, pair: str):
    return conn.execute("SELECT * FROM record WHERE pair=?", (pair,)).fetchone()


def put_record(conn, pair: str, a: str, b: str, hops: int, path_json: str,
               finder: str | None) -> None:
    conn.execute(
        "INSERT INTO record (pair, a, b, hops, path, finder, created_at)"
        " VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(pair) DO UPDATE SET hops=excluded.hops, path=excluded.path,"
        " finder=excluded.finder, created_at=excluded.created_at,"
        " a=excluded.a, b=excluded.b",
        (pair, a, b, hops, path_json, finder, now()))


put_record = _serialized(put_record)
