"""
Skannar en hel liga: hamtar kommande matcher + Bet365-odds via odds-api.io,
kor TOT-modellen + Goal Line-value-scan pa varje match som HAR odds, och
hoppar tyst over matcher som saknar odds an (de tas upp igen nasta korning).

Anvander ENDAST Bet365s Goal Line-marknad (Asian totals), inte 2.5-linjen
och inte 1X2 - se find_goal_line_value() i value_scan.py for metoden.

OBS: Detta skript gor riktiga API-anrop och kravs kora i en miljo med
natverksatkomst till api.odds-api.io och api.telegram.org (fungerar INTE
i Claudes sandlada just nu pga natverksfilter - kor detta lokalt eller pa
din egen server/VPS, t.ex. som ett timvis cron-jobb).

Miljovariabler som kravs (las in fran .env i projektroten, se telegram_bot.load_env):
    ODDS_API_KEY
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

Anvandning:
    python3 scan_league.py <liga-nyckel> [<liga-nyckel> ...]

Exempel:
    python3 scan_league.py poland sweden-norra sweden-sodra
    python3 scan_league.py poland sweden-norra sweden-sodra --send   # skickar till Telegram

Liga-nycklar: se LEAGUES i tot_model.py (poland, sweden-norra, sweden-sodra, japan-j1).
"""

import os
import sys
import time
import json
import gzip
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from tot_model import load_league, team_tot_snitt, dnb_probabilities, predict_tot, LAST_N, LEAGUES
from value_scan import find_goal_line_value
from telegram_bot import format_value_bet, format_report, send_message, load_env

API_BASE = "https://api.odds-api.io/v3"

# odds-api.io liga-slug per liga-nyckel (OBS: odds-api.io:s egen league-
# taggning ar opalitlig for de svenska lagen - en match taggad "sweden-
# ettan-norra" eller "sweden-ettan-sodra" kan innehalla lag fran bada
# ligorna. Vi loser det genom att normalisera lagnamn mot BADA CSV:erna
# (se resolve_team) istallet for att lita pa taggen.
#
# Verifierat 2026-09-30 mot odds-api.io:s faktiska /leagues-lista (884
# fotbollsligor, se verify_slugs.py) - alla slugs nedan ar bekraftat
# korrekta UTOM scotland-lowland, som saknas helt hos odds-api.io (ingen
# traff, inte ens pa fritextsokning efter "scotland") - den ligan gar
# alltsa inte att skanna mot Bet365 via den har tjansten, listan lamnas
# tom sa skriptet bara hoppar over den (ger 0 traffar, inget fel).
LEAGUE_SLUGS = {
    "poland": ["poland-ii-liga"],
    "sweden-norra": ["sweden-ettan-norra", "sweden-ettan-sodra"],
    "sweden-sodra": ["sweden-ettan-norra", "sweden-ettan-sodra"],

    "poland-i-liga": ["poland-1-liga"],
    "poland-iii-liga-1": ["poland-iii-liga-group-1"],
    "poland-iii-liga-2": ["poland-iii-liga-group-2"],
    "poland-iii-liga-3": ["poland-iii-liga-group-3"],

    "germany-3-liga": ["germany-3-liga"],
    "germany-regionalliga-nord": ["germany-amateur-regionalliga-north"],
    "germany-regionalliga-west": ["germany-amateur-regionalliga-west"],
    "germany-regionalliga-sudwest": ["germany-amateur-regionalliga-southwest"],
    "germany-regionalliga-nordost": ["germany-amateur-regionalliga-northeast"],
    "germany-regionalliga-bayern": ["germany-amateur-regionalliga-bavaria"],

    "wales-cymru-premier": ["wales-cymru-premier"],
    "wales-cymru-north": ["wales-cymru-championship-north"],
    "wales-cymru-south": ["wales-cymru-championship-south"],

    "japan-j1": ["japan-jleague"],

    "uae-league": ["united-arab-emirates-pro-league"],
    "uae-division-1": ["united-arab-emirates-division-1"],

    "scotland-premiership": ["scotland-premiership"],
    "scotland-championship": ["scotland-championship"],
    "scotland-league-one": ["scotland-league-one"],
    "scotland-league-two": ["scotland-league-two"],
    "scotland-highland": ["scotland-highland-league"],
    "scotland-lowland": [],  # saknas hos odds-api.io, gar inte att skanna

    "slovakia-nike-liga": ["slovakia-superliga"],
    "slovakia-2-liga": ["slovakia-2-liga"],
    "slovakia-3-liga-central": ["slovakia-3-liga-center"],
    "slovakia-3-liga-east": ["slovakia-3-liga-east"],
    "slovakia-3-liga-west": ["slovakia-3-liga-west"],

    "slovenia-prva-liga": ["slovenia-prvaliga"],
    "slovenia-2-snl": ["slovenia-2nd-snl"],
    "slovenia-3-snl-east": ["slovenia-3-snl-east"],
    "slovenia-3-snl-west": ["slovenia-3-snl-west"],
}

MIN_EV = 0.10  # minsta EV for att trigga en Telegram-alert (se find_goal_line_value)

# Kanda namnvarianter: API-namn -> namn i var historik-CSV
NAME_ALIASES = {
    "Karlbergs BK": "Karlbergs", "Vasalunds IF": "Vasalund",
    "IF Karlstad Fotbol": "Karlstad", "FC Arlanda": "Arlanda",
    "FC Stockholm Internazionale": "Stockholm Internazionale",
    "Piteaa IF": "Pitea", "Enkopings SK": "Enkoping SK",
    "Gefle IF": "Gefle", "IFK Stocksund": "Stocksund",
    "FC Jarfalla": "Jarfalla", "Sollentuna FK": "Sollentuna",
    "Hammarby Talang FF": "Hammarby TFF",
    "Kristianstad FC": "Kristianstad", "Ariana FC": "AFC Malmo",
    "Lunds BK": "Lunds", "Laholms FK": "Laholms",
    "Angelholms FF": "Angelholm", "FC Rosengaard 1917": "Rosengard",
    "Tvaakers IF": "Tvaaker", "Aatvidabergs FF": "Atvidaberg",
    "FC Trollhattan": "Trollhattan", "Jonkopings Sodra IF": "Jonkoping",
    "Eskilsminne IF": "Eskilsminne", "Utsiktens BK": "Utsikten",
    "BK Olympic": "Olympic", "Trelleborgs FF": "Trelleborg",
    # Poland II Liga (Bet365-namn -> vart historik-namn)
    "Rekord Bielsko-Biala": "Bielsko-Biala", "Rekord Bielsko Biala": "Bielsko-Biala",
    "CWKS Resovia": "R. Rzeszow", "Resovia Rzeszow": "R. Rzeszow",
    "GKS Tychy": "Tychy", "Sokol Kleczew": "Kleczew",
    "Legia Warsaw II": "Legia II", "Legia Warszawa II": "Legia II",
    "KS Lechia Zielona Gora": "Zielona Gora", "Lechia Zielona Gora": "Zielona Gora",
    "MKS Znicz Pruszkow": "Pruszkow", "Znicz Pruszkow": "Pruszkow",
    "ZKS Stal Stalowa Wola": "S. Wola", "Stal Stalowa Wola": "S. Wola",
    "Gornik Leczna": "Leczna", "MKS Chojniczanka Chojnice": "Chojniczanka",
    "Chojniczanka Chojnice": "Chojniczanka", "Zawisza Bydgoszcz": "Zawisza",
    "Olimpia Grudziadz": "Ol. Grudziadz", "Sandecja Nowy Sacz": "Sandecja Nowy S.",
    "KS Hutnik Krakow SSA": "Hutnik Krakow", "OKS Swit Szczecin": "Swit Szczecin",
}


def resolve_team(name, known_teams):
    if name in known_teams:
        return name
    if name in NAME_ALIASES and NAME_ALIASES[name] in known_teams:
        return NAME_ALIASES[name]
    return None


def api_get(path, params):
    key = os.environ.get("ODDS_API_KEY") or load_env().get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Satt miljovariabeln ODDS_API_KEY forst (eller lagg den i .env i projektroten)")
    params = dict(params)
    params["apiKey"] = key
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def get_upcoming_events(league_slug):
    return api_get("/events", {"sport": "football", "league": league_slug})


def get_event_odds(event_id):
    return api_get("/odds", {"eventId": event_id, "bookmakers": "Bet365"})


def scan_league(league_key, min_ev=MIN_EV):
    cfg = LEAGUES[league_key]
    matches = load_league(league_key)
    known_teams = set(m["hemmalag"] for m in matches) | set(m["bortalag"] for m in matches)

    seen_ids = set()
    events = []
    for slug in LEAGUE_SLUGS[league_key]:
        for ev in get_upcoming_events(slug):
            if ev["id"] in seen_ids:
                continue
            seen_ids.add(ev["id"])
            events.append(ev)

    hits = []
    for ev in events:
        home = resolve_team(ev["home"], known_teams)
        away = resolve_team(ev["away"], known_teams)
        if not home or not away:
            continue  # laget hor inte till den har ligan (fel slug-tagg) eller saknar historik

        odds_data = get_event_odds(ev["id"])
        bet365 = odds_data.get("bookmakers", {}).get("Bet365")
        if not bet365:
            continue

        ml = next((m for m in bet365 if m["name"] == "ML"), None)
        totals = next((m for m in bet365 if m["name"] == "Totals"), None)
        if not ml or not totals:
            continue

        odds_home = float(ml["odds"][0]["home"])
        odds_draw = float(ml["odds"][0]["draw"])
        odds_away = float(ml["odds"][0]["away"])

        snitt1, n1 = team_tot_snitt(matches, home, LAST_N, cfg["season_start"])
        snitt2, n2 = team_tot_snitt(matches, away, LAST_N, cfg["season_start"])
        p1_dnb, p2_dnb = dnb_probabilities(odds_home, odds_away)
        tot = predict_tot(snitt1, snitt2, p1_dnb, p2_dnb)

        totals_odds = [
            {"hdp": o["hdp"], "over": float(o["over"]), "under": float(o["under"])}
            for o in totals["odds"]
        ]
        hit = find_goal_line_value(tot, totals_odds, min_ev=min_ev)
        if hit:
            hits.append({
                "league": league_key,
                "match": f"{ev['home']} - {ev['away']}",
                "market": "Goal Line",
                "side": hit["sida"],
                "line": hit["line"],
                "model_prob": hit["modell_sannolikhet"],
                "bet365_odds": hit["bet365_odds"],
                "edge_pp": hit["edge_procentenheter"],
            })

        time.sleep(0.3)  # var snall mot API:t (free tier: 100 req/h)

    return hits


def main():
    args = sys.argv[1:]
    send = "--send" in args
    league_keys = [a for a in args if a != "--send"]

    if not league_keys:
        print(__doc__)
        sys.exit(1)

    all_hits = []
    for key in league_keys:
        if key not in LEAGUES:
            print(f"Okand liga-nyckel: {key} (se LEAGUES i tot_model.py)", file=sys.stderr)
            continue
        print(f"Skannar {key} ...", file=sys.stderr)
        all_hits += scan_league(key)

    report = format_report(all_hits)
    print(report)

    if send:
        send_message(report)
        print("Skickat till Telegram.", file=sys.stderr)


if __name__ == "__main__":
    main()
