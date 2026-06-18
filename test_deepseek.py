import os
import json

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[*] Loaded environment variables using python-dotenv.")
except ImportError:
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    print("[!] Error: DEEPSEEK_API_KEY not found in .env file.")
    exit(1)

masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "..."
print(f"[*] API Key detected: {masked_key}")

proxy_url = os.getenv("PROXY_URL")
if proxy_url:
    print(f"[*] Proxy enabled: {proxy_url}")
else:
    print("[*] No proxy configured (PROXY_URL not set in .env).")

# Import our zero-dependency SOCKS5 helper
from socks5_helper import make_https_request

url = "https://api.deepseek.com/chat/completions"
payload = {
    "model": "deepseek-chat",
    "messages": [
        {"role": "system", "content": "You are a translator. Translate to Thai."},
        {"role": "user", "content": "Hello! Testing the DeepSeek API connection."}
    ],
    "stream": False
}

body = json.dumps(payload).encode("utf-8")
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

print(f"[*] Sending POST request to {url}...")

try:
    status_code, response_text = make_https_request(
        url=url,
        method="POST",
        headers=headers,
        body=body,
        proxy_url=proxy_url,
        timeout=20
    )
    print(f"[✓] Connection successful! HTTP Status: {status_code}")
    res_json = json.loads(response_text)
    reply = res_json["choices"][0]["message"]["content"]
    print(f"\n[✓] Response: {reply}")

except ConnectionError as e:
    print(f"[!] Connection Error: {e}")
    if "10054" in str(e) or "forcibly closed" in str(e).lower():
        print("\n[!] Diagnosis: Connection Reset (WinError 10054).")
        print("    The connection was forcibly closed by ISP/Firewall/Antivirus.")
        if not proxy_url:
            print("    Try: add PROXY_URL=socks5://127.0.0.1:9150 in .env (with Tor Browser open)")
except Exception as e:
    print(f"[!] Unexpected error: {type(e).__name__}: {e}")
