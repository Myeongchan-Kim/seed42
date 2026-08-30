#!/usr/bin/env python
"""매일 조금씩 그래프를 넓힌다. 언어를 돌아가며, 그날의 화제로.

한 언어를 몰아서 파면 그 언어 영역만 두꺼워진다. 게다가 크롤러는 진입차수 순으로
파는데 그래프가 영어 중심이라(ko->en 이 en->ko 의 986배) 제한을 안 걸면 무엇을
넣든 영어로 끌려간다. 그래서 언어별로 시간을 나누고 프론티어도 언어로 묶는다.

시드는 세 갈래를 섞는다.
  - 그날의 화제 (seeds_live.py: 위키 조회수 상위 + 뉴스 헤드라인)
  - 해당 언어의 미확장 프론티어 (진입차수 높은 것부터)
  - 무작위 미확장 노드 (진입차수 편향을 깨는 소금)

  python daily.py --hours 3                 # 5개 언어에 3시간을 나눠 쓴다
  python daily.py --hours 1 --langs ko zh   # 특정 언어만
  python daily.py --hours 3 --dry-run
"""
from __future__ import annotations

import argparse
import random
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from number import db, llm, tokens
from number.tokens import norm

ROOT = Path(__file__).parent
LANGS = ["en", "ko", "zh", "ja", "es"]
SEED_FILE = {"zh": "seeds_zh.txt", "ja": "seeds_ja.txt", "es": "seeds_es.txt",
             "ko": "seeds.txt", "en": "seeds_live.txt"}


def refresh_live_seeds() -> None:
    """그날의 화제를 새로 받는다. 실패해도 크롤은 진행한다."""
    try:
        subprocess.run([sys.executable, str(ROOT / "seeds_live.py"), "--limit", "300"],
                       cwd=ROOT, timeout=180, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("  그날의 화제 갱신 완료")
    except Exception as e:
        print(f"  그날의 화제 갱신 실패 (계속 진행): {str(e)[:60]}")


def pool(conn, lang: str, n: int) -> list[str]:
    """해당 언어의 미확장 노드. 진입차수 상위 절반 + 무작위 절반."""
    cfg = db.find_config(conn, llm.GEN_MODEL, llm.PICK_MODEL, 0,
                         llm.PROMPT_VERSION, llm.SEED)
    if not cfg:
        return []
    base = ("SELECT n.word FROM edge e JOIN node n ON n.id=e.dst_id"
            " WHERE e.config_id=? AND n.lang=? AND NOT EXISTS ("
            "  SELECT 1 FROM response r WHERE r.node_id=n.id AND r.gen_model=?)"
            " GROUP BY e.dst_id ")
    top = [r["word"] for r in conn.execute(
        base + "ORDER BY COUNT(*) DESC LIMIT ?", (cfg, lang, llm.GEN_MODEL, n // 2))]
    rnd = [r["word"] for r in conn.execute(
        base + "ORDER BY RANDOM() LIMIT ?", (cfg, lang, llm.GEN_MODEL, n - n // 2))]
    out, seen = [], set()
    for w in top + rnd:
        if norm(w) not in seen and tokens.is_word(w):
            seen.add(norm(w))
            out.append(w)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=3.0)
    ap.add_argument("--langs", nargs="*", default=LANGS)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    langs = [l for l in a.langs if l in LANGS]
    share = a.hours / len(langs)
    print(f"\n  {time.strftime('%Y-%m-%d %H:%M')}  "
          f"{len(langs)}개 언어 × {share * 60:.0f}분\n")

    refresh_live_seeds()
    conn = db.connect()

    for lang in langs:
        words = pool(conn, lang, 900)
        sf = ROOT / SEED_FILE[lang]
        if sf.exists():
            fixed = [w.strip() for w in sf.read_text().splitlines() if w.strip()]
            random.shuffle(fixed)
            words = fixed[:120] + words          # 시드를 앞에, 프론티어를 뒤에
        path = ROOT / f".daily_{lang}.txt"
        path.write_text("\n".join(words[:1000]) + "\n")
        print(f"  [{lang}] 후보 {len(words[:1000])}단어  {share * 60:.0f}분")
        if a.dry_run:
            print(f"        예: {words[:10]}")
            continue
        subprocess.run(
            [sys.executable, "-u", str(ROOT / "crawl.py"),
             "--seed-file", str(path), "--frontier", "--lang", lang,
             "--limit", "1500", "--workers", str(a.workers),
             "--hours", f"{share:.4f}"],
            cwd=ROOT)
        path.unlink(missing_ok=True)

    print(f"\n  끝  {time.strftime('%H:%M')}")
    subprocess.run([sys.executable, str(ROOT / "crawl.py"), "--status"], cwd=ROOT)


if __name__ == "__main__":
    main()
