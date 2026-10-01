"""
Jamfor Bet365 mot Veikkaus direkt (INTE via var TOT-modell) och flaggar
stora avvikelser mellan de tva bookmakarna - bade rena arbitrage-mojligheter
(garanterad vinst oavsett utfall) och enskilda stora oddsskillnader som kan
vara varda att titta pa manuellt.

OBS: kor FORST check_veikkaus.py for att bekrafta att odds-api.io faktiskt
har Veikkaus, och under exakt vilket namn - uppdatera VEIKKAUS_NAME nedan om
det inte ar "Veikkaus".

Metod:
    1X2 (ML):
        - Arbitrage: 1/basta_hemma + 1/basta_oavgjort + 1/basta_borta < 1
          (anvander det BASTA oddset for varje utfall, oavsett vilken av de
          tva bookmakarna som ger det)
        - Stor avvikelse: samma utfall har >MIN_DIVERGENCE skillnad i
          implicerad sannolikhet mellan de tva bookmakarna

    Totals (Goal Line), per matchande linje (hdp):
        - Samma logik, for Over/Under

Anvandning:
    python3 arb_scan.py <liga-nyckel> [<liga-nyckel> ...]
    python3 arb_scan.py sweden-norra sweden-sodra --send
    python3 arb_scan.py all              # skannar bara de ~30 ligor var modell kanner till
    python3 arb_scan.py all-leagues      # skannar ALLA fotbollsligor odds-api.io har (se varning nedan)
    python3 arb_scan.py all-leagues --send

OBS om "all-leagues": den hamtar forst HELA ligalistan fran odds-api.io
(forvantat nagra hundra ligor over hela varlden - inte bara de vi redan
foljer), och kollar varje liga for kommande matcher dar bade Bet365 OCH
Veikkaus har odds. Det ar BETYDLIGT fler API-anrop an "all" (en /events-
anrop per liga, plus ett /odds-anrop per match som har bada bookmakarna).
Kor det forst en gang i smaskala (tex en enskild liga, eller "all") for
att se att allt fungerar, innan du kor hela varlden - annars kan du slosa
en stor del av din dagliga API-kvot pa en kors.

OBS: kravs riktig natverksatkomst (odds-api.io + Telegram), kor lokalt,
inte i Claudes sandlada. Samma .env som scan_league.py anvander.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from scan_league import LEAGUE_SLUGS, api_get
from telegram_bot import send_message, load_env, format_report_chunks

VEIKKAUS_NAME = "Veikkaus"  # uppdatera om check_veikkaus.py visar ett annat namn
MIN_DIVERGENCE = 0.06   # minsta skillnad i implicerad sannolikhet (6pp) for att flagga
MIN_ARB_PROFIT = 0.01   # minsta garanterade vinstmarginal (1%) for att rakna som arbitrage


def get_upcoming_events(league_slug):
    return api_get("/events", {"sport": "football", "league": league_slug})


def get_all_football_league_slugs():
    """Hamtar HELA ligalistan fran odds-api.io (inte bara de vi redan kanner till)."""
    leagues = api_get("/leagues", {"sport": "football"})
    return [(lg["slug"], lg.get("name", lg["slug"])) for lg in leagues]


def get_both_odds(event_id):
    return api_get("/odds", {"eventId": event_id, "bookmakers": f"Bet365,{VEIKKAUS_NAME}"})


def implied_probs_1x2(odds_home, odds_draw, odds_away):
    return 1 / odds_home, 1 / odds_draw, 1 / odds_away


def check_1x2(bet365_ml, veikkaus_ml, match_label):
    """Returnerar lista av fynd (arbitrage och/eller stora avvikelser) for 1X2-marknaden."""
    hits = []
    if not bet365_ml or not veikkaus_ml:
        return hits
    b = bet365_ml["odds"][0]
    v = veikkaus_ml["odds"][0]

    for outcome, key in [("Hemma", "home"), ("Oavgjort", "draw"), ("Borta", "away")]:
        o_b, o_v = float(b[key]), float(v[key])
        p_b, p_v = 1 / o_b, 1 / o_v
        diff = abs(p_b - p_v)
        if diff >= MIN_DIVERGENCE:
            better_book, better_odds = ("Bet365", o_b) if o_b > o_v else ("Veikkaus", o_v)
            worse_book, worse_odds = ("Veikkaus", o_v) if o_b > o_v else ("Bet365", o_b)
            hits.append({
                "type": "divergence",
                "market": f"1X2 - {outcome}",
                "match": match_label,
                "better_book": better_book, "better_odds": better_odds,
                "worse_book": worse_book, "worse_odds": worse_odds,
                "diff_pp": round(diff * 100, 1),
            })

    # Arbitrage-check: basta oddset per utfall, oavsett bookmaker
    best_home = max(float(b["home"]), float(v["home"]))
    best_draw = max(float(b["draw"]), float(v["draw"]))
    best_away = max(float(b["away"]), float(v["away"]))
    implied_sum = 1/best_home + 1/best_draw + 1/best_away
    if implied_sum < 1 - MIN_ARB_PROFIT:
        profit_pct = (1/implied_sum - 1) * 100
        hits.append({
            "type": "arbitrage",
            "market": "1X2",
            "match": match_label,
            "profit_pct": round(profit_pct, 2),
            "best_home": best_home, "best_draw": best_draw, "best_away": best_away,
        })
    return hits


def check_totals(bet365_totals, veikkaus_totals, match_label):
    """Jamfor Goal Line/Totals for matchande hdp-linjer mellan de tva bookmakarna."""
    hits = []
    if not bet365_totals or not veikkaus_totals:
        return hits
    v_by_hdp = {row["hdp"]: row for row in veikkaus_totals["odds"]}

    for row_b in bet365_totals["odds"]:
        hdp = row_b["hdp"]
        row_v = v_by_hdp.get(hdp)
        if not row_v:
            continue  # bookmakarna har inte samma linje - hoppa over, inte jamforbart

        for side, key in [("Over", "over"), ("Under", "under")]:
            o_b, o_v = float(row_b[key]), float(row_v[key])
            p_b, p_v = 1/o_b, 1/o_v
            diff = abs(p_b - p_v)
            if diff >= MIN_DIVERGENCE:
                better_book, better_odds = ("Bet365", o_b) if o_b > o_v else ("Veikkaus", o_v)
                worse_book, worse_odds = ("Veikkaus", o_v) if o_b > o_v else ("Bet365", o_b)
                hits.append({
                    "type": "divergence",
                    "market": f"Goal Line {hdp} - {side}",
                    "match": match_label,
                    "better_book": better_book, "better_odds": better_odds,
                    "worse_book": worse_book, "worse_odds": worse_odds,
                    "diff_pp": round(diff * 100, 1),
                })

        best_over = max(float(row_b["over"]), float(row_v["over"]))
        best_under = max(float(row_b["under"]), float(row_v["under"]))
        implied_sum = 1/best_over + 1/best_under
        if implied_sum < 1 - MIN_ARB_PROFIT:
            profit_pct = (1/implied_sum - 1) * 100
            hits.append({
                "type": "arbitrage",
                "market": f"Goal Line {hdp}",
                "match": match_label,
                "profit_pct": round(profit_pct, 2),
                "best_over": best_over, "best_under": best_under,
            })
    return hits


def scan_slugs(label, slugs):
    """Skannar en lista odds-api.io-ligaslugar (oavsett om de kommer fran var egen
    LEAGUE_SLUGS eller fran hela /leagues-listan) och letar efter Bet365+Veikkaus-
    avvikelser pa deras kommande matcher."""
    seen_ids = set()
    events = []
    for slug in slugs:
        for ev in get_upcoming_events(slug):
            if ev["id"] in seen_ids:
                continue
            seen_ids.add(ev["id"])
            events.append(ev)
        time.sleep(0.2)

    if not events:
        return []

    print(f"  -> {len(events)} kommande matcher for {label}", file=sys.stderr)

    all_hits = []
    for ev in events:
        match_label = f"{ev['home']} - {ev['away']}"
        odds_data = get_both_odds(ev["id"])
        bookmakers = odds_data.get("bookmakers", {})
        bet365 = bookmakers.get("Bet365")
        veikkaus = bookmakers.get(VEIKKAUS_NAME)
        if not bet365 or not veikkaus:
            time.sleep(0.3)
            continue

        bet365_ml = next((m for m in bet365 if m["name"] == "ML"), None)
        veikkaus_ml = next((m for m in veikkaus if m["name"] == "ML"), None)
        bet365_totals = next((m for m in bet365 if m["name"] == "Totals"), None)
        veikkaus_totals = next((m for m in veikkaus if m["name"] == "Totals"), None)

        all_hits.extend(check_1x2(bet365_ml, veikkaus_ml, match_label))
        all_hits.extend(check_totals(bet365_totals, veikkaus_totals, match_label))

        time.sleep(0.3)

    print(f"  -> {len(all_hits)} avvikelser/arbitrage hittade i {label}", file=sys.stderr)
    return all_hits


def scan_league(league_key):
    return scan_slugs(league_key, LEAGUE_SLUGS.get(league_key, []))


def format_hit(h):
    if h["type"] == "arbitrage":
        if "best_home" in h:
            return (
                f"*ARBITRAGE* ({h['match']})\n"
                f"{h['market']} — garanterad vinst: {h['profit_pct']}%\n"
                f"Hemma {h['best_home']}  /  Oavgjort {h['best_draw']}  /  Borta {h['best_away']}\n"
            )
        else:
            return (
                f"*ARBITRAGE* ({h['match']})\n"
                f"{h['market']} — garanterad vinst: {h['profit_pct']}%\n"
                f"Over {h['best_over']}  /  Under {h['best_under']}\n"
            )
    else:
        return (
            f"*Avvikelse* ({h['match']})\n"
            f"{h['market']}\n"
            f"{h['better_book']}: {h['better_odds']}  vs  {h['worse_book']}: {h['worse_odds']}"
            f"  (skillnad: {h['diff_pp']}pp)\n"
        )


def main():
    args = sys.argv[1:]
    send = "--send" in args
    league_keys = [a for a in args if a != "--send"]

    if not league_keys:
        print(__doc__)
        sys.exit(1)

    all_hits = []

    if league_keys == ["all-leagues"]:
        # Skanna HELA odds-api.io:s ligalista, inte bara de ~30 vi kanner till
        # fran var egen modell. Detta ar mycket storre an "all" - se varningen
        # i filens docstring innan du kor detta.
        print("Hamtar hela ligalistan fran odds-api.io...", file=sys.stderr)
        all_slugs = get_all_football_league_slugs()
        print(f"Hittade {len(all_slugs)} fotbollsligor totalt - skannar alla...", file=sys.stderr)
        for i, (slug, name) in enumerate(all_slugs, 1):
            print(f"[{i}/{len(all_slugs)}] {name} ({slug})", file=sys.stderr)
            all_hits.extend(scan_slugs(name, [slug]))
    elif league_keys == ["all"]:
        # skanna varenda liga vi har en odds-api.io-slug registrerad for
        for key in [k for k, slugs in LEAGUE_SLUGS.items() if slugs]:
            print(f"Skannar {key}...", file=sys.stderr)
            all_hits.extend(scan_league(key))
            time.sleep(0.3)
    else:
        for key in league_keys:
            if key not in LEAGUE_SLUGS or not LEAGUE_SLUGS[key]:
                print(f"Hoppar over {key} (ingen odds-api.io-slug registrerad)", file=sys.stderr)
                continue
            print(f"Skannar {key}...", file=sys.stderr)
            all_hits.extend(scan_league(key))
            time.sleep(0.3)

    # sortera: arbitrage forst (storst vinst forst), sedan storsta avvikelser
    arb_hits = sorted([h for h in all_hits if h["type"] == "arbitrage"], key=lambda h: -h["profit_pct"])
    div_hits = sorted([h for h in all_hits if h["type"] == "divergence"], key=lambda h: -h["diff_pp"])

    report_lines = [f"*Bet365 vs Veikkaus - {len(arb_hits)} arbitrage, {len(div_hits)} stora avvikelser*\n"]
    for h in arb_hits + div_hits:
        report_lines.append(format_hit(h))
    report = "\n".join(report_lines)
    print(report)

    if send and (arb_hits or div_hits):
        text = report
        if len(text) > 3500:
            # enkel chunkning pa samma satt som format_report_chunks, fast har
            chunks, current = [], report_lines[0]
            for block in report_lines[1:]:
                if len(current) + len(block) > 3500:
                    chunks.append(current)
                    current = ""
                current += block
            if current:
                chunks.append(current)
        else:
            chunks = [text]
        for chunk in chunks:
            send_message(chunk)
        print(f"Skickat till Telegram ({len(chunks)} meddelande(n)).", file=sys.stderr)


if __name__ == "__main__":
    main()
