import os
import json
import urllib.parse
import time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# --- KONFIGURASJON ---
URL = "https://www.domstol.no/no/nar-gar-rettssaken/?fraDato=2026-02-14&tilDato=2026-12-31&domstolid=AAAA2103291207189142069FYGVMW_EJBOrgUnit&sortTerm=rettsmoete&sortAscending=true&pageSize=1000"
CACHE_FILE = Path("cache.json")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_1")

def les_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except: return {}
    return {}

def skriv_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def send_slack_varsel(sak_info):
    mottaker = "romerike.og.glamdal.tingrett@domstol.no"
    emne = f"Innsyn i sluttinnlegg - {sak_info['saksnr']}"
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
                        f"🚨 Ny tvistesak funnet! 🚨\n\n"
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
                    {"type": "button", "text": {"type": "plain_text", "text": "Åpne saken"}, "url": sak_info['sakslenke'], "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Send innsynskrav"}, "url": gmail_url}
                ]
            }
        ]
    }
    requests.post(SLACK_WEBHOOK_URL, json=message, timeout=10)

def main():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=options)
    sendte_varsler = les_cache()
    
    try:
        driver.get(URL)
        time.sleep(10)

        wait = WebDriverWait(driver, 30)

        # Lukk cookie-banner
        try:
            cookie_knapp = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Kun nødvendige')]")))
            cookie_knapp.click()
            print("Cookie-banner lukket!")
            time.sleep(3)
        except Exception as e:
            print(f"Første forsøk feilet: {e}")
            try:
                knapper = driver.find_elements(By.TAG_NAME, "button")
                for knapp in knapper:
                    print(f"Fant knapp: '{knapp.text}'")
                    if "nødvendige" in knapp.text.lower():
                        driver.execute_script("arguments[0].click();", knapp)
                        print("Cookie-banner lukket via JavaScript!")
                        time.sleep(3)
                        break
            except Exception as e2:
                print(f"Andre forsøk feilet: {e2}")

        # Ta screenshot før klikk
        driver.save_screenshot("before_click.png")
        print("Side-tittel:", driver.title)

        # Klikk på Søk-knappen i skjemaet (ikke navigasjonssøket)
        try:
            sok_knapp = wait.until(EC.element_to_be_clickable((By.XPATH, "//main//button[contains(@class, 'Button_button--primary')]")))
            sok_knapp.click()
            print("Søk-knappen klikket!")
        except Exception as e:
            print(f"Fant ikke Søk-knappen: {e}")
            knapper = driver.find_elements(By.TAG_NAME, "button")
            for knapp in knapper:
                print(f"Knapp: '{knapp.text}' | class: '{knapp.get_attribute('class')}'")

        time.sleep(10)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        # Ta screenshot etter klikk
        driver.save_screenshot("after_click.png")

        # Vent på tabell
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        rader = driver.find_elements(By.CSS_SELECTOR, "table tr")[1:]
        i_dag = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        grense = i_dag + timedelta(days=14)
        
        for rad in rader:
            cols = rad.find_elements(By.TAG_NAME, "td")
            if len(cols) < 5: continue
            
            saksnr_celle = cols[1]
            saksnr = saksnr_celle.text.strip()
            rettsmoete_full = cols[0].text.strip()
            dato_str = rettsmoete_full.split()[0]
            
            cache_id = f"{saksnr}_{dato_str}"
            
            if "TVI" in saksnr and cache_id not in sendte_varsler:
                try:
                    try:
                        lenke_element = saksnr_celle.find_element(By.TAG_NAME, "a")
                        sakslenke = lenke_element.get_attribute("href")
                    except:
                        sakslenke = URL

                    sak_dato = datetime.strptime(dato_str, "%d.%m.%Y")
                    
                    if i_dag <= sak_dato <= grense:
                        send_slack_varsel({
                            'rettsmoete': rettsmoete_full,
                            'saksnr': saksnr,
                            'domstol': cols[2].text.strip(),
                            'saken_gjelder': cols[3].text.strip(),
                            'parter': cols[4].text.strip(),
                            'sakslenke': sakslenke
                        })
                        sendte_varsler[cache_id] = datetime.now().isoformat()
                except Exception as e:
                    print(f"Feil ved rad: {e}")
                    
        skriv_cache(sendte_varsler)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
