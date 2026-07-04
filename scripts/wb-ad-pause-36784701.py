#!/usr/bin/env python3
"""
WB 广告暂停脚本（带二次确认+群通知）
每天07:10 由系统cron执行
暂停广告ID 36784701
"""
import json
import subprocess
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LOG_DIR
from lib.feishu import get_tenant_token, send_text_to_group

LOG_FILE = f"{LOG_DIR}/wb-ad-pause.log"
AD_ID = 36784701


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")


def get_wb_token():
    import config
    token_file = config.WB_TOKEN_FILE
    with open(token_file) as f:
        return json.load(f)["jwt"]


def get_ad_name(ad_id):
    token = get_wb_token()
    try:
        r = subprocess.run(
            ["curl", "-s", "-H", f"Authorization: {token}",
             f"https://advert-api.wildberries.ru/api/advert/v2/adverts?ids={ad_id}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=15
        )
        data = json.loads(r.stdout)
        return data["adverts"][0]["settings"]["name"]
    except Exception as e:
        log(f"获取广告名称失败: {e}")
        return str(ad_id)


def check_status(ad_id, expected, retries=3):
    token = get_wb_token()
    for i in range(retries):
        time.sleep(2)
        try:
            r = subprocess.run(
                ["curl", "-s", "-H", f"Authorization: {token}",
                 f"https://advert-api.wildberries.ru/api/advert/v2/adverts?ids={ad_id}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=15
            )
            data = json.loads(r.stdout)
            status = data["adverts"][0]["status"]
            if status == expected:
                log(f"广告 {ad_id} 状态确认: {status} ✅")
                return True
            else:
                log(f"广告 {ad_id} 状态不符: 期望{expected}, 实际{status} (重试{i+1}/{retries})")
        except Exception as e:
            log(f"广告 {ad_id} 查询异常: {e} (重试{i+1}/{retries})")
    return False


def pause_ad(ad_id):
    token = get_wb_token()
    r = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: {token}",
         f"https://advert-api.wildberries.ru/adv/v0/pause?id={ad_id}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, timeout=15
    )
    if r.stdout.strip():
        log(f"广告 {ad_id} 暂停API异常: {r.stdout[:100]}")
        return False
    log(f"广告 {ad_id} 暂停API成功，正在确认状态...")
    return check_status(ad_id, 11)


def main():
    log("=== WB广告暂停开始 ===")
    try:
        ad_name = get_ad_name(AD_ID)
        log(f"广告名称: {ad_name}")
        ok = pause_ad(AD_ID)
        token = get_tenant_token()
        if ok:
            send_text_to_group(token, f"⏸️ WB广告暂停\n📌 {ad_name}（{AD_ID}）\n✅ 已确认暂停（status=11）")
        else:
            send_text_to_group(token, f"⚠️ WB广告暂停异常\n📌 {ad_name}（{AD_ID}）\n❌ 状态确认失败，请手动检查")
        log("=== WB广告暂停完成 ===")
    except Exception as e:
        log(f"❌ 异常: {e}")
        try:
            send_text_to_group(get_tenant_token(), f"❌ WB广告暂停异常\n广告 {AD_ID}: {str(e)[:200]}")
        except:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
