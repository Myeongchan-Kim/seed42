#!/bin/bash
# 배포 전 문법 검사.
#
# 서버는 파이썬 3.11, 개발 기기는 3.12 다. f-string 안에 같은 종류의 따옴표를
# 중첩하면 3.12 는 통과하고 3.11 은 SyntaxError 를 낸다. 실제로 이것 때문에
# 배포 후 502 가 났다 (앱이 아예 뜨지 못해 Caddy 가 502 를 돌려준다).
#
# ast.parse(feature_version=(3,11)) 로는 잡히지 않는다 - 그 옵션은 토크나이저
# 동작을 바꾸지 않아 3.12 문법을 그대로 통과시킨다. 실제 3.11 로 컴파일해야 한다.
set -uo pipefail
PY311=${PY311:-python3.11}

if ! command -v "$PY311" >/dev/null; then
  echo "  $PY311 없음 - 서버와 같은 버전으로 검사할 수 없다" >&2
  exit 2
fi

FILES=${*:-}
if [ -z "$FILES" ]; then
  FILES=$(git ls-files '*.py')
fi

fail=0
for f in $FILES; do
  out=$("$PY311" -m py_compile "$f" 2>&1)
  if [ -n "$out" ]; then
    echo "  [$f]"
    echo "$out" | grep -E "line |SyntaxError" | head -3 | sed 's/^/    /'
    fail=1
  fi
done
find . -name '__pycache__' -path '*/__pycache__' -prune -exec rm -rf {} + 2>/dev/null

if [ "$fail" = "0" ]; then
  echo "  $($PY311 -V) 컴파일 OK ($(echo "$FILES" | wc -w | tr -d ' ')개 파일)"
else
  echo "  컴파일 실패 - 배포하면 502 가 난다" >&2
fi
exit $fail
