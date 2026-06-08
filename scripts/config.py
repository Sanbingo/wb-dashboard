"""
定时任务脚本配置文件
"""
import os

# ===== 飞书配置 =====
FEISHU_APP_ID = "cli_aa9f821b6cfcdcb6"
FEISHU_APP_SECRET = "RfQLb3dyReu0fFI9RhkgmhEcdYXOg51T"
FEISHU_USER_ID = "ou_676ea834120797575b86e9d87771d49b"        # 林总私聊
FEISHU_GROUP_ID = "oc_e6483e6b795bb97464ffd3d4923685d2"       # WB订单通知群

# ===== OAS (Ozon分析系统) =====
OAS_BASE = "https://oas.xmaquaman.com"
OAS_USERNAME = "AKM"
OAS_PASSWORD = "000111"

# ===== Ozon店铺API密钥 =====
OZON_STORE_KEYS = {
    "store6": {                          # 店铺6
        "client_id": 3045704,
        "api_key": "7a870b04-18b1-487c-85cb-6c942a0f721a",
    },
}

# ===== WB API =====
WB_TOKEN_FILE = os.path.expanduser("~/.openclaw/workspace/secrets/wb-api.json")

# ===== WB 广告ID =====
WB_AD_IDS = [36921073, 35674574]

# ===== Chrome 截图 =====
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# ===== 代理（WB API可能需要） =====
WB_PROXY = "http://127.0.0.1:7897"

# ===== 日志目录 =====
LOG_DIR = os.path.expanduser("~/.openclaw/workspace/scripts/logs")
os.makedirs(LOG_DIR, exist_ok=True)
