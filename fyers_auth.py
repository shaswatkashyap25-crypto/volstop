"""
Fyers headless authentication script.
Runs on GitHub Actions daily at 8:30 AM IST (3:00 AM UTC).
"""

import os
import base64
import hashlib
import time
import pyotp
import requests
from urllib.parse import parse_qs, urlparse
from datetime import datetime

# Credentials
CLIENT_ID    = os.environ['FYERS_CLIENT_ID']       # FAJ38819
APP_ID       = os.environ['FYERS_APP_ID']           # NXQC7TYDP8
APP_SECRET   = os.environ['FYERS_APP_SECRET']
TOTP_SECRET  = os.environ['FYERS_TOTP_SECRET']
PIN          = os.environ.get('FYERS_PIN', '')
REDIRECT_URI = 'https://shaswatkashyap25-crypto.github.io/volstop/'

CF_ACCOUNT_ID      = os.environ['CF_ACCOUNT_ID']
CF_KV_NAMESPACE_ID = os.environ['CF_KV_NAMESPACE_ID']
CF_API_TOKEN       = os.environ['CF_API_TOKEN']

def enc(s):
    return base64.b64encode(str(s).encode('ascii')).decode('ascii')

def wait_safe_totp_window():
    """Ensure at least 5 seconds remain in current TOTP window."""
    remaining = 30 - (time.time() % 30)
    if remaining < 5:
        wait = remaining + 2
        print(f"Waiting {wait:.1f}s for safe TOTP window...")
        time.sleep(wait)

def step1_send_otp():
    url = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
    payload = {"fy_id": enc(CLIENT_ID), "app_id": "2"}
    r = requests.post(url, json=payload)
    print(f"step1_send_otp: {r.status_code} {r.text}")
    data = r.json()
    if data.get('s') == 'error':
        raise Exception(f"send_login_otp failed: {r.text}")
    return data['request_key']

def step2_verify_totp(request_key):
    wait_safe_totp_window()
    totp = pyotp.TOTP(TOTP_SECRET).now()
    print(f"TOTP generated: {totp}")
    url = "https://api-t2.fyers.in/vagator/v2/verify_otp"
    r = requests.post(url, json={"request_key": request_key, "otp": totp})
    print(f"step2_verify_totp: {r.status_code} {r.text}")
    data = r.json()
    if data.get('s') == 'error':
        raise Exception(f"verify_totp failed: {r.text}")
    return data['request_key']

def step3_verify_pin(request_key):
    ses = requests.Session()
    if not PIN:
        print("No PIN — skipping, using request_key as token")
        return request_key, ses
    url = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
    payload = {"request_key": request_key, "identity_type": "pin", "identifier": enc(PIN)}
    r = ses.post(url, json=payload)
    print(f"step3_verify_pin: {r.status_code} {r.text}")
    data = r.json()
    if data.get('s') == 'error':
        raise Exception(f"verify_pin failed: {r.text}")
    # Response has access_token directly in data, not token
    token = data['data'].get('token') or data['data'].get('access_token')
    return token, ses

def step4_get_auth_code(token, ses):
    url = "https://api-t1.fyers.in/api/v3/token"
    app_id_hash = hashlib.sha256(f"{APP_ID}-100:{APP_SECRET}".encode()).hexdigest()
    payload = {
        "fyers_id": CLIENT_ID,
        "app_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "appType": "100",
        "code_challenge": "",
        "state": "volstop",
        "scope": "",
        "nonce": "",
        "response_type": "code",
        "create_cookie": True
    }
    ses.headers.update({"Authorization": f"Bearer {token}"})
    r = ses.post(url, json=payload)
    print(f"step4_get_auth_code: {r.status_code} {r.text}")
    data = r.json()
    if 'Url' in data:
        parsed = urlparse(data['Url'])
        auth_code = parse_qs(parsed.query).get('auth_code', [None])[0]
        if auth_code:
            return auth_code
    raise Exception(f"No auth_code in response: {r.text}")

def step5_get_access_token(auth_code):
    url = "https://api-t1.fyers.in/api/v3/validate-authcode"
    app_id_hash = hashlib.sha256(f"{APP_ID}-100:{APP_SECRET}".encode()).hexdigest()
    payload = {"grant_type": "authorization_code", "appIdHash": app_id_hash, "code": auth_code}
    r = requests.post(url, json=payload)
    print(f"step5_get_access_token: {r.status_code} {r.text}")
    data = r.json()
    token = data.get('access_token')
    if not token:
        raise Exception(f"No access_token: {r.text}")
    return token

def store_kv(key, value):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{key}"
    r = requests.put(url, headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "text/plain"}, data=value)
    print(f"KV store [{key}]: {r.status_code} {r.text}")
    if r.status_code not in [200, 201]:
        raise Exception(f"KV store failed: {r.text}")

if __name__ == "__main__":
    print(f"Starting Fyers auth at {datetime.utcnow()} UTC...")
    rk1 = step1_send_otp()
    rk2 = step2_verify_totp(rk1)
    token, ses = step3_verify_pin(rk2)
    auth_code = step4_get_auth_code(token, ses)
    access_token = step5_get_access_token(auth_code)
    full_token = f"{APP_ID}-100:{access_token}"
    store_kv('fyers_token', full_token)
    print("Auth complete! Token stored in Cloudflare KV.")
