#!/bin/bash
# WB日报数据刷新脚本
# 刷新昨日MSK数据 (MSK = UTC+3)
cd /opt/wb-dashboard
YESTERDAY=$(python3 -c "
from datetime import datetime, timezone, timedelta
# 用MSK时区计算昨天，确保6AM/23PM CST都得到正确的\"昨天MSK\"
msk_tz = timezone(timedelta(hours=3))
yesterday = (datetime.now(timezone.utc).astimezone(msk_tz) - timedelta(days=1)).strftime('%Y-%m-%d')
print(yesterday)
")
python3 wb-dashboard-data.py --start "$YESTERDAY" --end "$YESTERDAY" --output "data/wb-daily-$YESTERDAY.json" >> logs/refresh.log 2>&1
echo "Done at $(date)" >> logs/refresh.log
