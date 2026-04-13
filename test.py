import httpx
import json

ECOWIT_APP_KEY = "3A97A4F04494D4E5EADEB20300175203"
ECOWIT_API_KEY = "075b743d-e408-4df3-b9ef-fde8e71b36fb"
TEST_MAC = "30:83:98:A5:F0:12"

url = "https://api.ecowit.net/api/v3/device/history"
params = {
    "application_key": ECOWIT_APP_KEY,
    "api_key": ECOWIT_API_KEY,
    "mac": TEST_MAC,
    "call_back": "rainfall",
    "cycle_type": "1day",
    "start_date": "2026-03-01 00:00:00",
    "end_date": "2026-03-31 23:59:59"
}

# The ultimate stealth disguise: Mimicking a modern Chrome browser perfectly
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.ecowit.net",
    "Referer": "https://www.ecowit.net/"
}

try:
    print("Launching stealth request...")
    # httpx with HTTP/2 enabled is incredibly hard for firewalls to detect
    with httpx.Client(http2=True) as client:
        response = client.get(url, params=params, headers=headers, timeout=15.0)

    print(f"\nStatus Code: {response.status_code}")

    # Try to parse JSON
    try:
        data = response.json()
        print("\n✅ SUCCESS! Bypassed firewall. JSON Data Received:")
        print(json.dumps(data, indent=2))
    except Exception:
        print("\n❌ FAILED: Still blocked. Raw text:")
        print(response.text)

except Exception as e:
    print(f"\n🚨 Error: {e}")