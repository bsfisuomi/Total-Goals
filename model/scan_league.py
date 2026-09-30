"""
Skannar en hel liga: hamtar kommande matcher + Bet365-odds via odds-api.io,
kor TOT-modellen + Poisson-value-scan pa varje match som HAR odds, och
hoppar tyst over matcher som saknar odds an (de tas upp igen nasta korning).

OBS: Detta skript gor riktiga API-anrop och kravs kora i en miljo med
natverksatkomst till api.odds-api.io (fungerar INTE i Claudes sandlada
just nu pga natverksfilter - kor detta lokalt eller pa din framtida server).

Miljovariabel som kravs:
    ODDS_API_KEY

Anvandning:
    export ODDS_API_KEY="din-nyckel"
    python3 scan_league.py "Sweden Ettan Norra/ettan-norra.csv" sweden-ettan-norra
"""

import csv
import os
import sys
import time
import json
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from tot_model import load_matches, team_tot_snitt, dnb_probabilities, predict_tot, LAST_N
from value_scan import find_value
from poisson_grid import value_1x2

API_BASE = "https://api.odds-api.io/v3"

# Kanda namnvarianter: API-namn -> namn i var historik-CSV
NAME_ALIASES = {
    "Karlbergs BK": "Karlbergs",
    "Vasalunds IF": "Vasalund",
    "IF Karlstad Fotbol": "Karlstad",
    "FC Arlanda": "Arlanda",
    "FC Stockholm Internazionale": "Stockholm Internazionale",
    "Piteaa IF": "Pitea",
    "Enkopings SK": "Enkoping SK",
    # Poland II Liga (Bet365-namn -> vart historik-namn)
    "Rekord Bielsko-Biala": "Bielsko-Biala",
    "Resovia Rzeszow": "R. Rzeszow",
    "GKS Tychy": "Tychy",
    "Sokol Kleczew": "Kleczew",
    "Legia Warsaw II": "Legia II",
    "Lechia Zielona Gora": "Zielona Gora",
    "Znicz Pruszkow": "Pruszkow",
    "Stal Stalowa Wola": "S. Wola",
    "Gornik Leczna": "Leczna",
    "Chojniczanka Chojnice": "Chojniczanka",
    "Zawisza Bydgoszcz": "Zawisza",
    "Olimpia Grudziadz": "Ol. Grudziadz",
    "Sandecja Nowy Sacz": "Sandecja Nowy S.",
}


def normalize_name(name, known_teams):
    if name in known_teams:
        return name
    if name in NAME_ALIASES and NAME_ALIASES[name] in known_teams:
        return NAME_ALIASES[name]
    return None


def api_get(path, params):
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Satt miljovariabeln ODDS_API_KEY forst")
    params = dict(params)
    params["apiKey"] = key
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())


def get_upcoming_events(league_slug):
    return api_get("/events", {"sport": "football", "league": league_slug})


def get_event_odds(event_id):
    return api_get("/odds", {"eventId": event_id, "bookmakers": "Bet365"})


def scan_league(csv_path, league_slug, min_edge_totals=0.04, min_edge_1x2=0.03):
    matches = load_matches(csv_path)
    known_teams = set(m["hemmalag"] for m in matches) | set(m["bortalag"] for m in matches)

    events = get_upcoming_events(league_slug)
    print(f"{len(events)} kommande matcher hittade i {league_slug}")

    results = []
    for ev in events:
        home = normalize_name(ev["home"], known_teams)
        away = normalize_name(ev["away"], known_teams)

        if not home or not away:
            print(f"  Hoppar over {ev['home']} - {ev['away']}: saknar historik")
            continue

        odds_data = get_event_odds(ev["id"])
        bookmakers = odds_data.get("bookmakers", {})
        bet365 = bookmakers.get("Bet365")

        if not bet365:
            print(f"  Hoppar over {ev['home']} - {ev['away']}: inga Bet365-odds an (forsok igen senare)")
            continue

        ml = next((m for m in bet365 if m["name"] == "ML"), None)
        totals = next((m for m in bet365 if m["name"] == "Totals"), None)

        if not ml:
            print(f"  Hoppar over {ev['home']} - {ev['away']}: ingen ML-marknad")
            continue

        odds_home = float(ml["odds"][0]["home"])
        odds_draw = float(ml["odds"][0]["draw"])
        odds_away = float(ml["odds"][0]["away"])

        snitt1, n1 = team_tot_snitt(matches, home, LAST_N)
        snitt2, n2 = team_tot_snitt(matches, away, LAST_N)
        p1_dnb, p2_dnb = dnb_probabilities(odds_home, odds_away)
        tot = predict_tot(snitt1, snitt2, p1_dnb, p2_dnb)

        match_result = {
            "match": f"{ev['home']} - {ev['away']}",
            "datum": ev["date"],
            "tot_forvantad": round(tot, 3),
            "value_totals": [],
            "value_1x2": [],
        }

        if totals:
            totals_odds = [
                {"hdp": o["hdp"], "over": float(o["over"]), "under": float(o["under"])}
                for o in totals["odds"]
            ]
            match_result["value_totals"] = find_value(tot, totals_odds, min_edge=min_edge_totals)

        oneXtwo = value_1x2(tot, p1_dnb, p2_dnb, odds_home, odds_draw, odds_away, min_edge=min_edge_1x2)
        match_result["value_1x2"] = oneXtwo["value"]

        results.append(match_result)

        # var snall mot API:t (free tier: 100 req/h)
        time.sleep(0.5)

    return results


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    csv_path = sys.argv[1]
    league_slug = sys.argv[2]

    results = scan_league(csv_path, league_slug)

    print("\n=== VALUE HITTAT ===")
    any_value = False
    for r in results:
        if r["value_totals"] or r["value_1x2"]:
            any_value = True
            print(f"\n{r['match']} ({r['datum']}) — TOT-prognos: {r['tot_forvantad']}")
            for v in r["value_totals"]:
                print(f"  Totals {v['line']} {v['sida']}: odds {v['bet365_odds']}  edge +{v['edge_procentenheter']}pp")
            for v in r["value_1x2"]:
                print(f"  1X2 {v['sida']}: odds {v['bet365_odds']}  edge +{v['edge_procentenheter']}pp")

    if not any_value:
        print("Ingen value hittad i den har korningen.")


if __name__ == "__main__":
    main()
