"""
Fyers headless authentication script.
Runs on GitHub Actions daily at 8:30 AM IST.
Generates access token and stores in Cloudflare KV.
"""

import os
import json
import pyotp
import requests
import hashlib
import base64

# Credentials from environment variables (GitHub Secrets)
CLIENT_ID = os.environ['FYERS_CLIENT_ID']
APP_ID = os.environ['FYERS_APP_ID']
APP_SECRET = os.environ['FYERS_APP_SECRET']
TOTP_SECRET = os.environ['FYERS_TOTP_SECRET']
CF_ACCOUNT_ID = os.environ['CF_ACCOUNT_ID']
CF_KV_NAMESPACE_ID = os.environ['CF_KV_NAMESPACE_ID']
CF_API_TOKEN = os.environ['CF_API_TOKEN']

def generate_totp():
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.now()

def get_auth_code():
    """Step 1: Get auth code via Fyers API v3"""
    session = requests.Session()
    
    # Generate TOTP
    totp_code = generate_totp()
    print(f"Generated TOTP: {totp_code}")
    
    # Send login request
    login_url = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
    payload = {
        "fy_id": CLIENT_ID,
        "app_id": "2"
    }
    r = session.post(login_url, json=payload)
    print(f"Login OTP response: {r.status_code} {r.text}")
    
    if r.status_code != 200:
        raise Exception(f"Login failed: {r.text}")
    
    request_key = r.json().get("request_key")
    
    # Verify TOTP
    verify_url = "https://api-t2.fyers.in/vagator/v2/verify_otp"
    payload = {
        "request_key": request_key,
        "otp": totp_code
    }
    r = session.post(verify_url, json=payload)
    print(f"Verify OTP response: {r.status_code} {r.text}")
    
    if r.status_code != 200:
        raise Exception(f"TOTP verification failed: {r.text}")
    
    request_key = r.json().get("request_key")
    
    # Verify PIN (if needed - try without first)
    # Get auth code
    auth_url = "https://api-t2.fyers.in/vagator/v2/verify_hmac"  
    payload = {
        "request_key": request_key,
        "fyers_client_id": f"{APP_ID}-100",
        "redirect_uri": "https://shaswatkashyap25-crypto.github.io/volstop/",
        "response_type": "code",
        "state": "volstop"
    }
    r = session.post(auth_url, json=payload)
    print(f"Auth code response: {r.status_code} {r.text}")
    
    auth_code = r.json().get("auth_code")
    if not auth_code:
        raise Exception(f"No auth code: {r.text}")
    
    return auth_code

def get_access_token(auth_code):
    """Step 2: Exchange auth code for access token"""
    # Generate app_id_hash
    app_id_hash = hashlib.sha256(f"{APP_ID}:{APP_SECRET}".encode()).hexdigest()
    
    token_url = "https://api-t1.fyers.in/api/v3/validate-authcode"
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash,
        "code": auth_code
    }
    r = requests.post(token_url, json=payload)
    print(f"Token response: {r.status_code} {r.text}")
    
    if r.status_code != 200:
        raise Exception(f"Token exchange failed: {r.text}")
    
    return r.json().get("access_token")

def store_token_in_kv(access_token):
    """Store token in Cloudflare KV"""
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/fyers_token"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "text/plain"
    }
    r = requests.put(url, headers=headers, data=access_token)
    print(f"KV store response: {r.status_code} {r.text}")
    
    if r.status_code not in [200, 201]:
        raise Exception(f"KV store failed: {r.text}")
    
    print("Token stored successfully in Cloudflare KV")

if __name__ == "__main__":
    print("Starting Fyers auth...")
    try:
        auth_code = get_auth_code()
        print(f"Auth code obtained: {auth_code[:10]}...")
        access_token = get_access_token(auth_code)
        print(f"Access token obtained: {access_token[:10]}...")
        store_token_in_kv(access_token)
        print("Auth complete!")
    except Exception as e:
        print(f"Auth failed: {e}")
        raise
