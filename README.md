# Domstol TVI-overvåker

Automatisk overvåking av sivile saker (TVI) ved Romerike og Glåmdal tingrett. Sender varsel til Slack når nye saker er berammet innen 14 dager.

## Hvordan det fungerer

Et Python-script kjører daglig via GitHub Actions og henter saker fra domstol.no sitt API. Nye TVI-saker som starter innen 14 dager varsles i Slack med direktelenke til saken og en ferdig Gmail-knapp for innsynskrav.

Saker som allerede er varslet lagres i `cache.json` slik at samme sak ikke varsles flere ganger.

## Slack-varselet inneholder

- Rettsmøteperiode
- Saksnummer
- Domstol
- Hva saken gjelder
- Parter / advokater
- Knapp: direkte til saken på domstol.no
- Knapp: åpner Gmail med ferdig utfylt innsynskrav

## Oppsett

### 1. GitHub Secret
Legg til Slack webhook-URL som secret i repoet:

- Gå til **Settings → Secrets and variables → Actions**
- Legg til secret med navn `SLACK_WEBHOOK_1` og din Slack webhook-URL som verdi

### 2. Filer i repoet
| Fil | Beskrivelse |
|-----|-------------|
| `domstol_overvaker.py` | Hovedscriptet |
| `.github/workflows/overvaker.yml` | GitHub Actions workflow |
| `cache.json` | Oversikt over allerede varslede saker (autogenerert) |
| `test_overvaker.py` | Testscript for lokal kjøring uten Slack-varsling |

## Lokal testing

Installer avhengighet og kjør testscriptet:

```bash
pip install requests
python test_overvaker.py
```

Testscriptet henter ekte data fra API-et og printer all info som ville blitt sendt til Slack – uten å faktisk sende noe.

## Kjøretidspunkt

Scriptet kjører automatisk kl. 10:00 norsk tid hver dag. Det kan også kjøres manuelt via **Actions → Domstol TVI-overvåker → Run workflow**.
