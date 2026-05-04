#!/usr/bin/env python3
"""
Overvåker Romerike og Glåmdal tingrett for TVI-saker.
Kjører automatisk via GitHub Actions hver dag kl 11:00.
"""

import os
import json
import logging
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup

# --- KONFIGURASJON ---
URL = "https://www.domstol.no/no/nar-gar-rettssaken/?fraDato=2026-01-30&tilDato=2026-12-30&domstolid=AAAA2103291207189142069FYGVMW_EJBOrgUnit&sortTerm=rettsmoete&sortAscending=true&pageSize=1000"

# Slack webhooks (fra miljøvariabler eller GitHub Secrets)
SLACK_WEBHOOK_URLS = []
for i in range(1, 10):  # Støtter opptil 9 webhooks
    webhook = os.environ.get(f'SLACK_WEBHOOK_{i}')
    if webhook:
        SLACK_WEBHOOK_URLS.append(webhook)

# Logging-konfigurasjon
LOG_FILE = Path("domstol.log")
STATUS_FILE = Path("siste_kjoring.txt")
CACHE_FILE = Path("cache.json")

# Roter logger (maks 5MB, behold 10 filer)
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5*1024*1024,  # 5MB
    backupCount=10
)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Logg også til konsoll
console = logging.StreamHandler()
console.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console)


def les_cache():
    """Leser cache av tidligere sendte varsler."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                # Rens gamle oppføringer (eldre enn 60 dager)
                cutoff = datetime.now() - timedelta(days=60)
                return {k: v for k, v in data.items() 
                       if datetime.fromisoformat(v) > cutoff}
        except Exception as e:
            logger.warning(f"Kunne ikke lese cache: {e}")
    return {}


def skriv_cache(sendte_saker):
    """Lagrer cache."""
    try:
        logger.info(f"💾 Skriver cache til {CACHE_FILE}")
        logger.info(f"📊 Cache inneholder {len(sendte_saker)} saker")
        with open(CACHE_FILE, 'w') as f:
            json.dump(sendte_saker, f, indent=2)
        logger.info(f"✅ Cache lagret vellykket")
        
        # Verifiser at filen ble opprettet
        if os.path.exists(CACHE_FILE):
            file_size = os.path.getsize(CACHE_FILE)
            logger.info(f"✓ Cache-fil bekreftet: {file_size} bytes")
        else:
            logger.error(f"❌ Cache-fil ble IKKE opprettet!")
    except Exception as e:
        logger.error(f"Kunne ikke skrive cache: {e}")


def oppdater_status(melding):
    """Skriver status til fil."""
    try:
        with open(STATUS_FILE, 'w') as f:
            f.write(f"{datetime.now().isoformat()}: {melding}\n")
    except Exception as e:
        logger.warning(f"Kunne ikke skrive statusfil: {e}")


def send_slack_varsel(sak_info):
    """Sender varsel til alle Slack-kanaler med Block Kit formatting."""
    
    if not SLACK_WEBHOOK_URLS:
        logger.warning("Ingen Slack webhooks konfigurert - hopper over sending")
        return False
    
    mottaker = "romerike.og.glamdal.tingrett@domstol.no"
    
    # Sjekk om det er planleggingsmøte eller hovedforhandling
    saken_gjelder = sak_info.get('saken_gjelder', '').lower()
    er_planleggingsmoete = 'planleggingsmøte' in saken_gjelder or 'planleggings møte' in saken_gjelder
    
    if er_planleggingsmoete:
        emne = "Innsyn i rettsbok/referat fra planleggingsmøte"
        innhold = f"Hei\n\nRomerikes Blad ber om innsyn i rettsbok/referat fra planleggingsmøte i {sak_info['saksnr']}."
        moete_type = "Planleggingsmøte"
    else:
        emne = "Innsyn i sluttinnlegg"
        innhold = f"Hei\n\nRomerikes Blad ber om innsyn i sluttinnleggene i {sak_info['saksnr']}."
        moete_type = "Hovedforhandling"
    
    gmail_url = (
        f"https://mail.google.com/mail/?view=cm&fs=1"
        f"&to={mottaker}"
        f"&su={urllib.parse.quote(emne)}"
        f"&body={urllib.parse.quote(innhold)}"
    )

    # Bygg meldingen med Block Kit
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
            logger.info(f"✓ Slack-varsel sendt for {sak_info['saksnr']} til kanal {i}")
        except Exception as e:
            logger.error(f"✗ Feil ved Slack-sending til kanal {i}: {e}")
            suksess_totalt = False
    
    return suksess_totalt


def send_status_varsel(antall_saker, antall_nye):
    """Sender daglig status-melding til Slack med Block Kit."""
    
    if not SLACK_WEBHOOK_URLS:
        return False
    
    if antall_nye > 0:
        # Ikke send status hvis vi allerede har sendt varsler
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
    """Henter og analyserer saker fra Domstol.no med Selenium."""
    
    relevante_saker = []
    
    # Sett opp Chrome options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    driver = None
    
    try:
        logger.info("Starter Chrome...")
        driver = webdriver.Chrome(options=options)
        
        # Last siden
        logger.info(f"Laster side: {URL[:100]}...")
        driver.get(URL)
        
        # Vent på at tabellen lastes (maks 30 sekunder)
        logger.info("Venter på tabell...")
        wait = WebDriverWait(driver, 30)
        tabell = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # Parse HTML
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        tabell = soup.find("table")
        if not tabell:
            logger.error("Fant ikke tabell i parsed HTML")
            return []
        
        rader = tabell.find_all("tr")[1:]  # Hopp over header
        logger.info(f"Fant {len(rader)} rader i tabellen")
        
        i_dag = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        grense = i_dag + timedelta(days=14)
        
        for rad in rader:
            kolonner = rad.find_all("td")
            if len(kolonner) < 5:
                continue
            
            try:
                rettsmoete = kolonner[0].text.strip()
                saksnr_col = kolonner[1]
                saksnr = saksnr_col.text.strip()
                domstol = kolonner[2].text.strip()
                saken_gjelder = kolonner[3].text.strip()
                parter = kolonner[4].text.strip()
                
                # Hent lenke til saken
                saksnr_lenke = saksnr_col.find('a')
                if saksnr_lenke and saksnr_lenke.get('href'):
                    href = saksnr_lenke['href']
                    if href.startswith('/'):
                        sakslenke = f"https://www.domstol.no{href}"
                    else:
                        sakslenke = href
                else:
                    sakslenke = URL
                
                if "TVI" not in saksnr:
                    continue
                
                dato_str = rettsmoete.split()[0]
                sak_dato = datetime.strptime(dato_str, "%d.%m.%Y")
                
                if i_dag <= sak_dato <= grense:
                    relevante_saker.append({
                        'rettsmoete': rettsmoete,
                        'saksnr': saksnr,
                        'domstol': domstol,
                        'saken_gjelder': saken_gjelder,
                        'parter': parter,
                        'sakslenke': sakslenke
                    })
                    logger.info(f"✓ Funnet relevant sak: {saksnr} ({dato_str})")
                    
            except (ValueError, IndexError) as e:
                logger.debug(f"Hoppet over rad: {e}")
                continue
    
    except TimeoutException:
        logger.error("Timeout - tabellen lastet ikke i tide")
    except Exception as e:
        logger.error(f"Feil med Selenium: {e}")
    finally:
        if driver:
            driver.quit()
            logger.info("Chrome lukket")
    
    return relevante_saker


def main():
    """Hovedfunksjon."""
    logger.info("="*70)
    logger.info("🔍 DOMSTOL-OVERVÅKER STARTER (GitHub Actions)")
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
        if sak['saksnr'] not in sendte_saker:
            logger.info(f"📤 Sender varsel for NY sak: {sak['saksnr']}")
            if send_slack_varsel(sak):
                sendte_saker[sak['saksnr']] = datetime.now().isoformat()
                antall_sendt += 1
        else:
            logger.debug(f"Sak {sak['saksnr']} allerede varslet tidligere")
    
    if antall_sendt > 0:
        skriv_cache(sendte_saker)
        melding = f"Sendt {antall_sendt} nye varsler"
        logger.info(f"✅ {melding}")
        oppdater_status(melding)
    else:
        melding = "Ingen nye saker å varsle om"
        logger.info(f"✓ {melding}")
        oppdater_status(melding)
        # Send daglig status-varsel når ingen nye saker
        send_status_varsel(len(nye_saker), antall_sendt)
    
    logger.info("="*70)
    logger.info("🏁 DOMSTOL-OVERVÅKER FERDIG")
    logger.info("="*70)


if __name__ == "__main__":
    main()
