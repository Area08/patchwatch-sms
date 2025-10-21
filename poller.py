import hashlib, json, os, sys
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import yaml

# Miljövariabler från GitHub (Secrets)
SMS_PROVIDER = "46ELKS"  # vi använder 46elks i den här guiden
ELKS_USERNAME = os.getenv("ELKS_USERNAME")
ELKS_PASSWORD = os.getenv("ELKS_PASSWORD")
SMS_FROM = os.getenv("SMS_FROM")
SMS_TO_RAW = os.getenv("SMS_TO", "")
RECIPIENTS = [x.strip() for x in SMS_TO_RAW.split(",") if x.strip()]

if not all([ELKS_USERNAME, ELKS_PASSWORD, SMS_FROM]) or not RECIPIENTS:
    print("Saknar ELKS_USERNAME/ELKS_PASSWORD/SMS_FROM eller SMS_TO", file=sys.stderr)
    sys.exit(1)

# Läs config
with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)
STATE_FILE = Path(CFG.get("state_file", "state.json"))
SOURCES = CFG.get("sources", [])
MESSAGE_PREFIX = CFG.get("message_prefix", "🔔 Uppdatering upptäckt")

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def fetch(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (PatchWatch SMS bot)"}
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    return r.text

def page_hash(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.extract()
    text = soup.get_text(separator=" ", strip=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def send_sms_via_46elks(to: str, message: str):
    data = {"from": SMS_FROM, "to": to, "message": message}
    r = requests.post(
        "https://api.46elks.com/a1/SMS",
        auth=(ELKS_USERNAME, ELKS_PASSWORD),
        data=data,
        timeout=20
    )
    if r.status_code >= 300:
        raise RuntimeError(f"46elks fel: {r.status_code} {r.text}")

def send_sms(message: str):
    for to in RECIPIENTS:
        send_sms_via_46elks(to, message)

def notify(title: str, url: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"{MESSAGE_PREFIX}: {title}\n{url}\n{ts}"
    if len(msg) > 300:
        msg = msg[:297] + "..."
    send_sms(msg)

def check_source(src: dict, state: dict):
    name = src["name"]; url = src["url"]; kind = src.get("kind", "page_hash")
    print(f"Kollar: {name} – {url}")
    try:
        html = fetch(url)
    except Exception as e:
        print(f"[VARNING] Kunde inte hämta {url}: {e}", file=sys.stderr)
        return

    new_sig = page_hash(html) if kind == "page_hash" else hashlib.sha256(html.encode("utf-8")).hexdigest()
    state.setdefault("sources", {})
    old_sig = state["sources"].get(url)

    if old_sig is None:
        # Första gången: spara men skicka inte sms
        print("Första körningen – sparar signatur utan SMS.")
        state["sources"][url] = new_sig
        return

    if new_sig != old_sig:
        print(f"ÄNDRING upptäckt för {name}! Skickar SMS.")
        try:
            notify(name, url)
        except Exception as e:
            print(f"[FEL] SMS misslyckades: {e}", file=sys.stderr)
        state["sources"][url] = new_sig
    else:
        print("Ingen ändring.")

def main():
    state = load_state()
    for src in SOURCES:
        check_source(src, state)
    save_state(state)
    print("Klar.")

if __name__ == "__main__":
    main()
