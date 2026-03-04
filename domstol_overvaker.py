import os
import json
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
import requests

# --- KONFIGURASJON ---
API_BASE = "https://www.domstol.no/api/episerver/v3/beramming"
CACHE_FILE = Path("cache.json")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_1")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.domstol.no/no/nar-gar-rettssaken/",
}

def lag_api_params():
    i_dag = datetime.now()
    fra_dato = (i_dag - timedelta(days=13)).strftime("%Y-%m-%d")
    til_dato = (i_dag + timedelta(days=365)).strftime("%Y-%m-%d")
    return {
        "fraDato": fra_dato,
        "tilDato": til_dato,
        "domstolid": "AAAA2103291207189142069FYGVMW_EJBOrgUnit",
        "sortTerm": "rettsmoete",
        "sortAscending": "true",
        "pageSize": "1000",
    }

def les_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def skriv_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def send_slack_varsel(sak_info):
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_1 er ikke satt - hopper over varsel")
        return

    mottaker = "romerike.og.glamdal.tingrett@domstol.no"
    emne = "Innsyn i sluttinnlegg"
    innhold = f"Hei\n\nRomerikes Blad ber om innsyn i sluttinnleggene i {sak_info['saksnr']}."

    gmail_url = (
        f"https://mail.google.com/mail/?view=cm&fs=1"
        f"&to={mottaker}"
        f"&su={urllib.parse.quote(emne)}"
        f"&body={urllib.parse.quote(innhold)}"
    )

    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"🚨 *Ny TVI-sak funnet innen 14 dager!* 🚨\n\n"
                        f"*Rettsmøte:* {sak_info['rettsmoete']}\n"
                        f"*Saksnr:* {sak_info['saksnr']}\n"
                        f"*Domstol:* {sak_info['domstol']}\n"
                        f"*Saken gjelder:* {sak_info['saken_gjelder']}\n"
                        f"*Parter:* {sak_info['parter']}"
                    )
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Se saken på Domstol.no"},
                        "url": "https://www.domstol.no/no/nar-gar-rettssaken/",
                        "style": "primary"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Send innsynskrav (Gmail)"},
                        "url": gmail_url
                    }
                ]
            }
        ]
    }

    response = requests.post(SLACK_WEBHOOK_URL, json=message, timeout=10)
    print(f"Varsel sendt for: {sak_info['saksnr']} (HTTP {response.status_code})")

def main():
    sendte_saker = les_cache()

    response = requests.get(API_BASE, params=lag_api_params(), headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()

    saker = data.get("hits", [])
    print(f"Antall saker hentet: {len(saker)} (totalt i basen: {data.get('count', '?')})")

    i_dag = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    grense = i_dag + timedelta(days=14)

    for sak in saker:
        saksnr = sak.get("saksnummer", "")

        if "TVI" not in saksnr:
            continue
        if saksnr in sendte_saker:
            continue

        sak_dato = datetime.strptime(sak["startdato"][:10], "%Y-%m-%d")

        if i_dag <= sak_dato <= grense:
            rettsmoete_intervaller = sak.get("rettsmoeteIntervaller", [{}])
            if rettsmoete_intervaller:
                intervall = rettsmoete_intervaller[0]
                rettsmoete_str = f"{intervall.get('start', '')} – {intervall.get('end', '')}"
            else:
                rettsmoete_str = sak["startdato"][:10]

            send_slack_varsel({
                'rettsmoete': rettsmoete_str,
                'saksnr': saksnr,
                'domstol': sak.get("domstol", ""),
                'saken_gjelder': sak.get("sakenGjelder") or "–",
                'parter': sak.get("parter") or sak.get("AdvokaterLang") or "–",
            })
            sendte_saker[saksnr] = datetime.now().isoformat()

    skriv_cache(sendte_saker)

if __name__ == "__main__":
    main()
