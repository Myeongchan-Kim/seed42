#!/bin/zsh
# launchd 가 부르는 진입점. 로그를 날짜별로 남기고 오래된 것은 지운다.
cd "$(dirname "$0")" || exit 1
mkdir -p logs
LOG="logs/daily-$(date +%Y%m%d).log"
{
  echo "===== $(date '+%F %T') 시작 ====="
  ./.venv/bin/python -u daily.py --hours "${1:-3}"
  echo "===== $(date '+%F %T') 끝 ====="
} >> "$LOG" 2>&1
find logs -name 'daily-*.log' -mtime +30 -delete 2>/dev/null
