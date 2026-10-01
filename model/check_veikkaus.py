"""
Diagnostik: kollar om odds-api.io har Veikkaus som bookmaker, och om sa,
exakt vilket namn den anvander (skiftlage spelar roll i bookmakers-parametern).

Kor detta FORST, en gang, innan du kor arb_scan.py - sa vi vet att
Veikkaus-namnet stammer innan vi bygger hela scanningen kring det.

OBS: odds-api.io kraver att man anger VILKA bookmakers man vill ha odds for
(att inte ange nagot alls ger "400 Bad Request") - vi kan alltsa inte bara
be om "alla bookmakers" och se vad som finns. Istallet provar det har
skriptet flera troliga namnvarianter av Veikkaus, en i taget, och visar
vilka som faktiskt ger traff.

Anvandning:
    python3 model/check_veikkaus.py <liga-nyckel>

Exempel:
    python3 model/check_veikkaus.py sweden-norra
"""

import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(__file__))
from scan_league import LEAGUE_SLUGS, api_get

# Troliga namnvarianter att prova - odds-api.io verkar vara skiftlageskansligt
CANDIDATES = [
    "Veikkaus", "veikkaus", "VEIKKAUS", "Veikkaus.fi", "Veikkaus Oy",
]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    league_key = sys.argv[1]
    if league_key not in LEAGUE_SLUGS or not LEAGUE_SLUGS[league_key]:
        print(f"Okand liga-nyckel eller ingen odds-api.io-slug registrerad: {league_key}")
        sys.exit(1)
    slug = LEAGUE_SLUGS[league_key][0]

    events = api_get("/events", {"sport": "football", "league": slug})
    if not events:
        print(f"Inga kommande matcher hittades for {slug} just nu - prova en annan liga.")
        sys.exit(1)

    ev = events[0]
    print(f"Testar mot: {ev['home']} - {ev['away']} (id={ev['id']})\n")

    # Steg 1: kontrollkoll - Bet365 vet vi fungerar (scan_league.py anvander den
    # redan). Om den har failar ar natverket/nyckeln problemet, inte Veikkaus-namnet.
    print("Steg 1: kontrollerar att Bet365 (som vi vet fungerar) svarar...")
    try:
        data = api_get("/odds", {"eventId": ev["id"], "bookmakers": "Bet365"})
        bet365 = data.get("bookmakers", {}).get("Bet365")
        if bet365:
            print(f"  OK - Bet365 svarade med {len(bet365)} marknad(er).\n")
        else:
            print(f"  Bet365 gav svar men inget data for just den har matchen just nu (kan vara okej).\n")
    except urllib.error.HTTPError as e:
        print(f"  FEL: Bet365-anropet gav {e.code} {e.reason} - nat/nyckel-problem, inte Veikkaus-relaterat.")
        sys.exit(1)

    # Steg 2: prova varje namnvariant av Veikkaus, en i taget, tillsammans med Bet365
    # (sa vi far ett svar vi kan jamfora med, och sa vi inte skickar en tom bookmakers-lista).
    print("Steg 2: provar namnvarianter for Veikkaus...\n")
    found_name = None
    for candidate in CANDIDATES:
        try:
            data = api_get("/odds", {"eventId": ev["id"], "bookmakers": f"Bet365,{candidate}"})
            bookmakers = data.get("bookmakers", {})
            hit = bookmakers.get(candidate)
            if hit:
                print(f"  '{candidate}'  ->  TRAFF! ({len(hit)} marknad(er))")
                found_name = candidate
                break
            else:
                print(f"  '{candidate}'  ->  inget fel, men ingen data under det namnet")
        except urllib.error.HTTPError as e:
            print(f"  '{candidate}'  ->  {e.code} {e.reason} (troligen fel/okant namn)")

    print()
    if found_name:
        print(f"Veikkaus hittad! Exakt namn att anvanda i arb_scan.py: '{found_name}'")
        data = api_get("/odds", {"eventId": ev["id"], "bookmakers": f"Bet365,{found_name}"})
        vk = data["bookmakers"][found_name]
        print(f"Marknader Veikkaus har for den har matchen: {[m['name'] for m in vk]}")
        print(f"\nUppdatera VEIKKAUS_NAME = \"{found_name}\" i model/arb_scan.py om det inte redan stammer.")
    else:
        print("Ingen av namnvarianterna gav traff for den har matchen/ligan.")
        print("Prova en annan liga (storre liga/land kan ha battre tackning), t.ex.:")
        print("  python model/check_veikkaus.py poland")
        print("Om det fortfarande inte funkar nagonstans har odds-api.io troligen inte Veikkaus")
        print("alls pa er plan, och vi behover hitta en annan datakalla for Veikkaus-odds.")


if __name__ == "__main__":
    main()
