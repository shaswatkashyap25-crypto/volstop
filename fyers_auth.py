"""
Fyers headless authentication script.
Runs on GitHub Actions daily at 8:30 AM IST.
Generates access token and stores in Cloudflare KV.
"""

import os
import base64
import hashlib
import time
import pyotp
import requests
from urllib.parse import parse_qs, urlparse

# Credentials from environment
CLIENT_ID    = os.environ['FYERS_CLIENT_ID']      # FAJ38819
APP_ID       = os.environ['FYERS_APP_ID']          # NXQC7TYDP8
APP_SECRET   = os.environ['FYERS_APP_SECRET']      # YKCQL45MSN
TOTP_SECRET  = os.environ['FYERS_TOTP_SECRET']
PIN          = os.environ.get('FYERS_PIN', '')     # 4-digit PIN (optional)
REDIRECT_URI = 'https://shaswatkashyap25-crypto.github.io/volstop/'

CF_ACCOUNT_ID     = os.environ['CF_ACCOUNT_ID']
CF_KV_NAMESPACE_ID = os.environ['CF_KV_NAMESPACE_ID']
CF_API_TOKEN      = os.environ['CF_API_TOKEN']

BASE_URL   = "https://api-t2.fyers.in/vagator/v2"
BASE_URL_2 = "https://api-t1.fyers.in/api/v3"

def b64(s):
    return base64.b64encode(s.encode()).decode()

def wait_for_fresh_totp():
    """Wait until we have at least 5 seconds left in the TOTP window."""
    t = time.time()
    remaining = 30 - (t % 30)
    if remaining < 5:
        print(f"Waiting {remaining:.1f}s for fresh TOTP window...")
        time.sleep(remaining + 1)

def send_login_otp():
    wait_for_fresh_totp()
    url = BASE_URL + "/send_login_otp"
    payload = {"fy_id": b64(CLIENT_ID), "app_id": "2"}
    r = requests.post(url, json=payload)
    print(f"send_login_otp: {r.status_code} {r.text}")
    if r.status_code != 200 or r.json().get('s') == 'error':
        raise Exception(f"send_login_otp failed: {r.text}")
    return r.json()['request_key']

def verify_totp(request_key):
    totp = pyotp.TOTP(TOTP_SECRET).now()
    print(f"TOTP: {totp}")
    url = BASE_URL + "/verify_otp"
    payload = {"request_key": request_key, "otp": totp}
    r = requests.post(url, json=payload)
    print(f"verify_totp: {r.status_code} {r.text}")
    if r.status_code != 200 or r.json().get('s') == 'error':
        raise Exception(f"verify_totp failed: {r.text}")
    return r.json()['request_key']

def verify_pin(request_key):
    if not PIN:
        print("No PIN provided, skipping pin verification")
        return request_key
    url = BASE_URL + "/verify_pin_v2"
    payload = {"request_key": request_key, "identity_type": "pin", "identifier": b64(PIN)}
    r = requests.post(url, json=payload)
    print(f"verify_pin: {r.status_code} {r.text}")
    if r.status_code != 200 or r.json().get('s') == 'error':
        raise Exception(f"verify_pin failed: {r.text}")
    return r.json()['data']['token']

def get_auth_code(token):
    url = BASE_URL_2 + "/token"
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
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(url, json=payload, headers=headers)
    print(f"get_auth_code: {r.status_code} {r.text}")
    if r.status_code != 308 and r.status_code != 200:
        # Try to extract from URL
        pass
    data = r.json()
    if 'Url' in data:
        parsed = urlparse(data['Url'])
        auth_code = parse_qs(parsed.query).get('auth_code', [None])[0]
        if auth_code:
            return auth_code
    raise Exception(f"Could not get auth_code: {r.text}")

def get_access_token(auth_code):
    url = BASE_URL_2 + "/validate-authcode"
    app_id_hash = hashlib.sha256(f"{APP_ID}-100:{APP_SECRET}".encode()).hexdigest()
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash,
        "code": auth_code
    }
    r = requests.post(url, json=payload)
    print(f"get_access_token: {r.status_code} {r.text}")
    if r.status_code != 200:
        raise Exception(f"get_access_token failed: {r.text}")
    token = r.json().get('access_token')
    if not token:
        raise Exception(f"No access_token in response: {r.text}")
    return token

def store_in_kv(key, value):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{key}"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "text/plain"}
    r = requests.put(url, headers=headers, data=value)
    print(f"KV store [{key}]: {r.status_code} {r.text}")
    if r.status_code not in [200, 201]:
        raise Exception(f"KV store failed: {r.text}")

if __name__ == "__main__":
    print("Starting Fyers auth...")
    rk1 = send_login_otp()
    rk2 = verify_totp(rk1)
    token = verify_pin(rk2)
    auth_code = get_auth_code(token)
    print(f"Auth code: {auth_code[:15]}...")
    access_token = get_access_token(auth_code)
    print(f"Access token: {access_token[:15]}...")
    # Store token as APP_ID:access_token format (Fyers standard)
    full_token = f"{APP_ID}-100:{access_token}"
    store_in_kv('fyers_token', full_token)
    print("Done! Token stored in Cloudflare KV.")
