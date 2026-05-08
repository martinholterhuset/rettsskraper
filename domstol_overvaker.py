#!/usr/bin/env python3
"""
Overvåker Romerike og Glåmdal tingrett for TVI-saker.
Bruker domstol.no sitt API direkte - raskere og mer pålitelig enn Selenium!
"""

import os
import json
import logging
import urllib.parse
import requests
from datetime import datetime, timedelta
from pathlib import Path

# --- KONFIGURASJON ---
API_URL = "https://www.domstol.no/api/episerver/v3/beramming"
DOMSTOL_ID = "AAAA2103291207189142069FYGVMW_EJBOrgUnit"

# Slack webhooks
SLACK_WEBHOOK_URLS = []
for i in range(1, 10):
    webhook = os.environ.get(f'SLACK_WEBHOOK_{i}')
    if webhook:
        SLACK_WEBHOOK_URLS.append(webhook)

# Logging
LOG_FILE = Path("domstol.log")
STATUS_FILE = Path("siste_kjoring.txt")
CACHE_FILE = Path("cache.json")

from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=10)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

console = logging.StreamHandler()
console.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console)


def les_cache():
    """Leser cache."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                cutoff = datetime.now() - timedelta(days=60)
                return {k: v for k, v in data.items() 
                       if datetime.fromisoformat(v) > cutoff}
        except Exception as e:
            logger.warning(f"Kunne ikke lese cache: {e}")
    return {}


def skriv_cache(sendte_saker):
    """Lagrer cache."""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(sendte_saker, f, indent=2)
        logger.info(f"✅ Cache lagret ({len(sendte_saker)} saker)")
    except Exception as e:
        logger.error(f"Kunne ikke skrive cache: {e}")


def oppdater_status(melding):
    """Skriver status."""
    try:
        with open(STATUS_FILE, 'w') as f:
            f.write(f"{datetime.now().isoformat()}: {melding}\n")
    except Exception as e:
        logger.warning(f"Kunne ikke skrive status: {e}")


def send_slack_varsel(sak_info):
    """Sender varsel til Slack."""
    
    if not SLACK_WEBHOOK_URLS:
        logger.warning("Ingen Slack webhooks konfigurert")
        return False
    
    mottaker = "romerike.og.glamdal.tingrett@domstol.no"
    
    # Sjekk om det er planleggingsmøte eller hovedforhandling
    saken_gjelder = sak_info.get('sakenGjelder', '').lower()
    er_planleggingsmoete = 'planleggingsmøte' in saken_gjelder or 'planleggings møte' in saken_gjelder
    
    if er_planleggingsmoete:
        emne = "Innsyn i rettsbok/referat fra planleggingsmøte"
        innhold = f"Hei\n\nRomerikes Blad ber om innsyn i rettsbok/referat fra planleggingsmøte i {sak_info['saksnummer']}."
        moete_type = "Planleggingsmøte"
    else:
        emne = "Innsyn i sluttinnlegg"
        innhold = f"Hei\n\nRomerikes Blad ber om innsyn i sluttinnleggene i {sak_info['saksnummer']}."
        moete_type = "Hovedforhandling"
    
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
                        f"*Type:* {moete_type}\n"
                        f"*Rettsmøte:* {sak_info['rettsmoete']}\n"
                        f"*Saksnr:* {sak_info['saksnummer']}\n"
                        f"*Domstol:* {sak_info['domstol']}\n"
                        f"*Saken gjelder:* {sak_info['sakenGjelder']}\n"
                        f"*Parter:* {sak_info['parter']}"
                    )
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Se saken på Domstol.no",
                            "emoji": True
                        },
                        "url": sak_info['sakslenke'],
                        "style": "primary"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Send innsynskrav (Gmail)",
                            "emoji": True
                        },
                        "url": gmail_url
                    }
                ]
            }
        ]
    }
    
    suksess_totalt = True
    for i, webhook_url in enumerate(SLACK_WEBHOOK_URLS, 1):
        try:
            response = requests.post(webhook_url, json=message, timeout=10)
            response.raise_for_status()
            logger.info(f"✓ Slack-varsel sendt for {sak_info['saksnummer']} til kanal {i}")
        except Exception as e:
            logger.error(f"✗ Feil ved Slack-sending til kanal {i}: {e}")
            suksess_totalt = False
    
    return suksess_totalt


def send_status_varsel(antall_saker, antall_nye):
    """Sender status-melding."""
    
    if not SLACK_WEBHOOK_URLS:
        return False
    
    if antall_nye > 0:
        return True
    
    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"✅ *Domstol-overvåker kjørte vellykket*\n\n"
                        f"Tidspunkt: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                        f"TVI-saker innen 14 dager: {antall_saker}\n"
                        f"Nye saker: {antall_nye}\n\n"
                        f"_Ingen nye saker å varsle om i dag._"
                    )
                }
            }
        ]
    }
    
    for i, webhook_url in enumerate(SLACK_WEBHOOK_URLS, 1):
        try:
            response = requests.post(webhook_url, json=message, timeout=10)
            response.raise_for_status()
            logger.info(f"✓ Status-varsel sendt til kanal {i}")
        except Exception as e:
            logger.error(f"✗ Feil ved status-sending til kanal {i}: {e}")
            return False
    
    return True


def hent_og_analyser_saker():
    """Henter saker fra API."""
    
    relevante_saker = []
    
    # Beregn datoer
    i_dag = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    fra_dato = i_dag.strftime('%Y-%m-%d')
    til_dato = (i_dag + timedelta(days=365)).strftime('%Y-%m-%d')
    grense = i_dag + timedelta(days=14)
    
    # Bygg API-forespørsel
    params = {
        'fraDato': fra_dato,
        'tilDato': til_dato,
        'domstolid': DOMSTOL_ID,
        'sortTerm': 'rettsmoete',
        'sortAscending': 'true',
        'pageSize': '1000',
        'query': 'TVI'
    }
    
    try:
        logger.info(f"Henter TVI-saker fra API...")
        response = requests.get(API_URL, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        hits = data.get('hits', [])
        
        logger.info(f"📊 API returnerte {len(hits)} TVI-saker totalt")
        
        # Filtrer saker innen 14 dager
        for sak in hits:
            try:
                # Parse startdato
                startdato_str = sak['startdato']  # Format: "2026-04-24T08:30:00"
                sak_dato = datetime.fromisoformat(startdato_str.replace('Z', '+00:00'))
                sak_dato = sak_dato.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
                
                if i_dag <= sak_dato <= grense:
                    # Formater rettsmoete-dato
                    rettsmoete = sak_dato.strftime('%d.%m.%Y')
                    
                    # Bygg direkte sakslenke
                    sakslenke = f"https://www.domstol.no/no/nar-gar-rettssaken/?saksid={sak['sakId']}"
                    
                    relevante_saker.append({
                        'rettsmoete': rettsmoete,
                        'saksnummer': sak['saksnummer'],
                        'domstol': sak['domstol'],
                        'sakenGjelder': sak['sakenGjelder'],
                        'parter': sak.get('parter') or sak.get('ParterLang') or 'Ikke oppgitt',
                        'sakslenke': sakslenke
                    })
                    logger.info(f"✓ Funnet relevant sak: {sak['saksnummer']} ({rettsmoete})")
                    
            except (KeyError, ValueError) as e:
                logger.debug(f"Hoppet over sak: {e}")
                continue
        
        return relevante_saker
        
    except requests.RequestException as e:
        logger.error(f"❌ Feil ved API-kall: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Uventet feil: {e}")
        return []


def main():
    """Hovedfunksjon."""
    logger.info("="*70)
    logger.info("🔍 DOMSTOL-OVERVÅKER STARTER (API-versjon)")
    logger.info(f"Tidspunkt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Konfigurert med {len(SLACK_WEBHOOK_URLS)} Slack-kanal(er)")
    logger.info("="*70)
    
    sendte_saker = les_cache()
    logger.info(f"📋 Cache inneholder {len(sendte_saker)} tidligere sendte saker")
    
    nye_saker = hent_og_analyser_saker()
    
    if not nye_saker:
        melding = "Ingen TVI-saker funnet innen 14 dager"
        logger.info(f"✓ {melding}")
        oppdater_status(melding)
        send_status_varsel(0, 0)
        return
    
    logger.info(f"📊 Fant {len(nye_saker)} TVI-saker innen 14 dager")
    
    antall_sendt = 0
    for sak in nye_saker:
        if sak['saksnummer'] not in sendte_saker:
            logger.info(f"📤 Sender varsel for NY sak: {sak['saksnummer']}")
            if send_slack_varsel(sak):
                sendte_saker[sak['saksnummer']] = datetime.now().isoformat()
                antall_sendt += 1
        else:
            logger.debug(f"Sak {sak['saksnummer']} allerede varslet")
    
    if antall_sendt > 0:
        skriv_cache(sendte_saker)
        melding = f"Sendt {antall_sendt} nye varsler"
        logger.info(f"✅ {melding}")
        oppdater_status(melding)
    else:
        melding = "Ingen nye saker å varsle om"
        logger.info(f"✓ {melding}")
        oppdater_status(melding)
        send_status_varsel(len(nye_saker), antall_sendt)
    
    logger.info("="*70)
    logger.info("🏁 DOMSTOL-OVERVÅKER FERDIG")
    logger.info("="*70)


if __name__ == "__main__":
    main()
