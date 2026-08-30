#!/usr/bin/env python
"""배치 크롤러. 단어를 병렬로 던져 그래프를 넓힌다.

작업이 I/O 바운드다 - CPU 도 메모리도 거의 안 쓰고 6초짜리 응답을 기다리는 게
전부라, 스레드를 늘리는 만큼 그대로 빨라진다. 캐시가 곧 재개 지점이므로
언제 끊어도 다시 돌리면 이어서 간다.

  python crawl.py --seeds 재즈 커피 미토콘드리아 --limit 200
  python crawl.py --frontier --limit 5000 --workers 20
  python crawl.py --status
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from number import db, llm, tokens
from number.tokens import norm

STOP = threading.Event()
_lock = threading.Lock()
_stat = {"done": 0, "new": 0, "fail": 0, "cached": 0}


def click_config(conn) -> int:
    """클릭·크롤 그래프는 K 가 없다. k=0 으로 다른 설정과 구분한다."""
    return db.config_id(conn, llm.GEN_MODEL, 0.0, llm.PICK_MODEL, 0,
                        llm.PROMPT_VERSION, llm.SEED)


def expanded(conn) -> set[str]:
    """이미 던져본 단어."""
    return {norm(r["word"]) for r in conn.execute(
        "SELECT n.word FROM response r JOIN node n ON n.id=r.node_id"
        " WHERE r.gen_model=?", (llm.GEN_MODEL,))}


def frontier(conn, limit: int, langs: list[str] | None = None) -> list[str]:
    """이웃으로만 등장하고 아직 안 던져본 단어. 진입차수 높은 것부터 -
    여러 곳에서 가리키는 단어일수록 그래프의 중심에 가깝다.

    langs 를 주면 그 언어의 노드만 판다. 안 주면 그래프가 영어 중심이라
    다른 언어 시드를 넣어도 곧바로 영어 영역으로 끌려간다 (ko->en 이 en->ko 의
    1,097배라 한번 넘어가면 돌아오지 못한다)."""
    cfg = click_config(conn)
    q = ("SELECT n.word, COUNT(*) AS indeg FROM edge e JOIN node n ON n.id=e.dst_id"
         " WHERE e.config_id=? AND NOT EXISTS ("
         "   SELECT 1 FROM response r WHERE r.node_id=n.id AND r.gen_model=?)")
    args: list = [cfg, llm.GEN_MODEL]
    if langs:
        q += f" AND n.lang IN ({','.join('?' * len(langs))})"
        args += langs
    q += " GROUP BY e.dst_id ORDER BY indeg DESC LIMIT ?"
    args.append(limit)
    return [r["word"] for r in conn.execute(q, args) if tokens.is_word(r["word"])]


def visit(word: str) -> int:
    """한 단어를 던지고 이웃을 엣지로 남긴다. 새로 만든 노드 수를 돌려준다."""
    conn = llm.conn()                      # 스레드별 연결
    cfg = click_config(conn)

    cached = db.cache_get(conn, "respond",
                          llm._key_hash({"model": llm.GEN_MODEL, "word": word,
                                         "seed": llm.SEED})) is not None
    text = llm.respond(word)               # API 호출은 트랜잭션 밖에서
    nbrs = tokens.neighbors(text, exclude=word)   # 언어 자동 감지
    # 트랜잭션을 길게 열지 않는다. 열어두면 다른 스레드의 *다른 연결*이 그동안
    # 못 써서 'database is locked' 가 난다. 쓰기 직렬화는 db.WRITE 가 맡는다.
    src = db.node_id(conn, norm(word), word, word)
    resp = db.record_response(conn, src, text, llm.GEN_MODEL, 0.0,
                              llm.PROMPT_VERSION)
    dsts = [db.node_id(conn, norm(w), w, w) for w in nbrs]
    db.record_edges(conn, cfg, src, dsts, resp)

    with _lock:
        _stat["cached"] += int(cached)
    return len(nbrs)


def work(word: str) -> None:
    if STOP.is_set():
        return
    for attempt in range(3):
        try:
            new = visit(word)
            with _lock:
                _stat["done"] += 1
                _stat["new"] += new
            return
        except Exception as e:
            if attempt == 2 or STOP.is_set():
                with _lock:
                    _stat["fail"] += 1
                print(f"  [실패] {word}: {str(e)[:80]}", file=sys.stderr)
                return
            time.sleep(2 ** attempt)


def status() -> None:
    conn = db.connect()
    cfg = db.find_config(conn, llm.GEN_MODEL, llm.PICK_MODEL, 0,
                         llm.PROMPT_VERSION, llm.SEED)   # 조회만. 쓰기 락 안 잡는다
    q = lambda s, *a: conn.execute(s, a).fetchone()[0]
    done = q("SELECT COUNT(*) FROM response WHERE gen_model=?", llm.GEN_MODEL)
    nodes = q("SELECT COUNT(*) FROM node")
    edges = q("SELECT COUNT(*) FROM edge WHERE config_id=?", cfg) if cfg else 0
    print(f"\n  모델      {llm.GEN_MODEL}  seed {llm.SEED}  prompt {llm.PROMPT_VERSION}")
    print(f"  던져봄    {done:,}")
    print(f"  노드      {nodes:,}   (미확장 프론티어 {nodes - done:,})")
    print(f"  엣지      {edges:,}")
    if done:
        print(f"  평균 차수 {edges/done:.0f}\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", nargs="*", default=[], help="시작 단어들")
    p.add_argument("--seed-file", help="줄바꿈으로 구분된 단어 파일")
    p.add_argument("--frontier", action="store_true",
                   help="기존 그래프의 미확장 노드를 진입차수 순으로 판다")
    p.add_argument("--lang", nargs="*", help="프론티어를 이 언어로 제한 (ko zh ja es en)")
    p.add_argument("--limit", type=int, default=100, help="이번에 던질 단어 수")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--hours", type=float, help="이 시간이 지나면 멈춘다")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()

    if a.status:
        status()
        return

    conn = db.connect()
    words = list(a.seeds)
    if a.seed_file:
        words += [l.strip() for l in open(a.seed_file) if l.strip()]
    if a.frontier:
        words += frontier(conn, a.limit * 3, a.lang)

    seen = expanded(conn)
    todo, dedup = [], set()
    for w in words:
        n = norm(w)
        if n in seen or n in dedup or not llm.is_valid_word(w):
            continue
        dedup.add(n)
        todo.append(w)
    todo = todo[: a.limit]

    if not todo:
        print("던질 단어가 없다. --seeds 를 주거나 --frontier 를 쓴다.")
        return

    signal.signal(signal.SIGINT, lambda *_: (STOP.set(),
                  print("\n  중단 요청 - 진행 중인 것만 마치고 멈춘다...")))

    deadline = time.time() + a.hours * 3600 if a.hours else None
    lim = f", 최대 {a.hours}시간" if a.hours else ""
    print(f"\n  {len(todo)}단어를 {a.workers}병렬로{lim}. Ctrl-C 로 중단(재개 가능).")
    print(f"  시작 {time.strftime('%H:%M:%S')}\n", flush=True)
    t0 = time.time()
    total, round_no = 0, 0

    # 한 배치를 끝내면 프론티어를 다시 채워 시간 상한까지 계속 돈다.
    # 확장할 때마다 이웃이 프론티어로 들어오므로 파는 만큼 다시 차오른다.
    while todo and not STOP.is_set():
        round_no += 1
        total += len(todo)
        print(f"  --- {round_no}회차: {len(todo)}단어 ---", flush=True)
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = [ex.submit(work, w) for w in todo]
            last = 0
            while any(not f.done() for f in futs):
                time.sleep(2)
                d = _stat["done"]
                if d != last:
                    el = time.time() - t0
                    rate = d / el if el else 0
                    rem = (deadline - time.time()) / 60 if deadline else 0
                    print(f"  [{time.strftime('%H:%M:%S')}] {d}/{total}  "
                          f"이웃 {_stat['new']:,}  캐시 {_stat['cached']}  "
                          f"실패 {_stat['fail']}  {rate:.2f}/s  "
                          f"남은 {rem:.0f}분", flush=True)
                    last = d
                if STOP.is_set():
                    break
                if deadline and time.time() > deadline:
                    print("  시간 상한 도달 - 진행 중인 것만 마치고 멈춘다.", flush=True)
                    STOP.set()
                    break
        if STOP.is_set() or (deadline and time.time() > deadline):
            break
        seen = expanded(conn)
        todo = [w for w in frontier(conn, a.limit, a.lang)
                if norm(w) not in seen][: a.limit]
        if not todo:
            print("  프론티어가 비었다.", flush=True)

    el = time.time() - t0
    print(f"\n  {_stat['done']}단어 완료 ({round_no}회차)  이웃 {_stat['new']:,}  "
          f"실패 {_stat['fail']}  {el/60:.1f}분  ({_stat['done']/el:.2f}/s)")
    status()


if __name__ == "__main__":
    main()
