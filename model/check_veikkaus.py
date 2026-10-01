"""
Diagnostik: kollar om odds-api.io har Veikkaus som bookmaker, och om sa,
exakt vilket namn den anvander (skiftlage spelar roll i bookmakers-parametern).

Kor detta FORST, en gang, innan du kor arb_scan.py - sa vi vet att
Veikkaus-namnet stammer innan vi bygger hela scanningen kring det.

Anvandning:
    python3 model/check_veikkaus.py <liga-nyckel>

Exempel:
    python3 model/check_veikkaus.py sweden-norra
"""

import os
import sys
import json
import gzip
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from telegram_bot import load_env
from scan_league import LEAGUE_SLUGS, api_get

API_BASE = "https://api.odds-api.io/v3"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    league_key = sys.argv[1]
    slug = LEAGUE_SLUGS[league_key][0]

    events = api_get("/events", {"sport": "football", "league": slug})
    if not events:
        print(f"Inga kommande matcher hittades for {slug} just nu - prova en annan liga.")
        sys.exit(1)

    ev = events[0]
    print(f"Testar mot: {ev['home']} - {ev['away']} (id={ev['id']})\n")

    # Be INTE om ett specifikt bookmakers-filter har - hamta ALLA bookmakers
    # odds-api.io har for den har matchen, sa vi kan se exakt vilka namn som finns.
    odds_data = api_get("/odds", {"eventId": ev["id"]})
    bookmakers = odds_data.get("bookmakers", {})

    print(f"Bookmakers odds-api.io har for den har matchen ({len(bookmakers)} st):")
    for name in sorted(bookmakers.keys()):
        print(f"  - {name}")

    veikkaus_candidates = [b for b in bookmakers if "veik" in b.lower()]
    if veikkaus_candidates:
        print(f"\nVeikkaus hittad! Exakt namn att anvanda: '{veikkaus_candidates[0]}'")
        vk = bookmakers[veikkaus_candidates[0]]
        print(f"Marknader Veikkaus har for den har matchen: {[m['name'] for m in vk]}")
    else:
        print("\nVeikkaus hittades INTE bland bookmakers for den har matchen.")
        print("Prova en annan liga/match - Veikkaus kanske bara tackar vissa ligor,")
        print("eller sa har odds-api.io inte Veikkaus alls (da behover vi en annan datakalla).")


if __name__ == "__main__":
    main()
