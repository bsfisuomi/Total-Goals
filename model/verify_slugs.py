"""
Hjalpskript: hamtar ALLA fotbollsligor som odds-api.io faktiskt kanner till
(via /leagues-endpointen) och jamfor mot de gissade sluggarna i
LEAGUE_SLUGS (scan_league.py), sa ni kan ratta eventuella felgissningar.

Maste koras i en miljo med riktig natverksatkomst till api.odds-api.io
(fungerar INTE i Claudes sandlada - kor detta lokalt eller pa er egen
server/VPS, precis som scan_league.py).

Miljovariabel som kravs: ODDS_API_KEY (las in fran .env, se telegram_bot.load_env)

Anvandning:
    python3 verify_slugs.py
"""

import os
import sys
import json
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from scan_league import LEAGUE_SLUGS, API_BASE

try:
    from telegram_bot import load_env
    load_env()
except Exception:
    pass


def get_all_football_leagues():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Satt miljovariabeln ODDS_API_KEY forst (se .env)")
    params = {"sport": "football", "apiKey": key}
    url = f"{API_BASE}/leagues?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode())


def main():
    leagues = get_all_football_leagues()
    real_slugs = {lg["slug"]: lg.get("name", "") for lg in leagues}
    print(f"Hittade {len(real_slugs)} fotbollsligor totalt hos odds-api.io.\n")

    guessed_slugs = set()
    for slugs in LEAGUE_SLUGS.values():
        guessed_slugs.update(slugs)

    print("=== Gissade slugs som STAMMER (finns hos odds-api.io) ===")
    for slug in sorted(guessed_slugs):
        if slug in real_slugs:
            print(f"  OK   {slug}  ({real_slugs[slug]})")

    print("\n=== Gissade slugs som INTE stammer (matte rattas) ===")
    for key, slugs in LEAGUE_SLUGS.items():
        missing = [s for s in slugs if s not in real_slugs]
        if missing and len(missing) == len(slugs):
            print(f"  SAKNAS  {key}: {slugs}")

    print("\n=== Mojliga traffar via fritextsokning (for de saknade ovan) ===")
    search_terms = {
        "poland-i-liga": "poland",
        "poland-iii-liga-1": "poland",
        "poland-iii-liga-2": "poland",
        "poland-iii-liga-3": "poland",
        "germany-3-liga": "germany",
        "germany-regionalliga-nord": "germany",
        "germany-regionalliga-west": "germany",
        "germany-regionalliga-sudwest": "germany",
        "germany-regionalliga-nordost": "germany",
        "germany-regionalliga-bayern": "germany",
        "wales-cymru-premier": "wales",
        "wales-cymru-north": "wales",
        "wales-cymru-south": "wales",
        "japan-j1": "japan",
        "uae-league": "arab",
        "uae-division-1": "arab",
        "scotland-premiership": "scotland",
        "scotland-championship": "scotland",
        "scotland-league-one": "scotland",
        "scotland-league-two": "scotland",
        "scotland-highland": "scotland",
        "scotland-lowland": "scotland",
        "slovakia-nike-liga": "slovakia",
        "slovakia-2-liga": "slovakia",
        "slovakia-3-liga-central": "slovakia",
        "slovakia-3-liga-east": "slovakia",
        "slovakia-3-liga-west": "slovakia",
        "slovenia-prva-liga": "slovenia",
        "slovenia-2-snl": "slovenia",
        "slovenia-3-snl-east": "slovenia",
        "slovenia-3-snl-west": "slovenia",
    }
    printed_countries = set()
    for key, slugs in LEAGUE_SLUGS.items():
        missing = [s for s in slugs if s not in real_slugs]
        if not missing or len(missing) != len(slugs):
            continue
        term = search_terms.get(key)
        if not term or term in printed_countries:
            continue
        printed_countries.add(term)
        matches = [f"{s}  ({n})" for s, n in real_slugs.items() if term in s.lower() or term in n.lower()]
        print(f"\n  Traffar for '{term}' (relevant for t.ex. {key}):")
        for m in matches:
            print(f"    {m}")
        if not matches:
            print("    (inga traffar)")

    print("\nUppdatera LEAGUE_SLUGS i scan_league.py manuellt utifran listan ovan.")


if __name__ == "__main__":
    main()
