#!/bin/bash
# WB日报数据刷新脚本（多店铺）
# 刷新昨日MSK数据 (MSK = UTC+3)
cd /opt/wb-dashboard || exit 1
YESTERDAY=$(python3 -c "
from datetime import datetime, timezone, timedelta
msk_tz = timezone(timedelta(hours=3))
yesterday = (datetime.now(timezone.utc).astimezone(msk_tz) - timedelta(days=1)).strftime('%Y-%m-%d')
print(yesterday)
")
for STORE in wb1 wb2; do
  if [ "$STORE" = "wb1" ]; then
    OUT="data/wb-daily-$YESTERDAY.json"
  else
    mkdir -p "data/$STORE"
    OUT="data/$STORE/wb-daily-$YESTERDAY.json"
  fi
  echo "=== refresh $STORE $YESTERDAY $(date) ===" >> logs/refresh.log
  python3 wb-dashboard-data.py --store "$STORE" --start "$YESTERDAY" --end "$YESTERDAY" --output "$OUT" >> logs/refresh.log 2>&1
  echo "Done $STORE at $(date)" >> logs/refresh.log
done
