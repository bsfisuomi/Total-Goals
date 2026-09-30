"""
Total Goals-modell (TOT-modell)

Formel:
    TOT_forvantad = (b0 + b1 * ABS(p1_DNB - p2_DNB)) * ((snitt1 + snitt2) / 2 / regressionssnitt)

dar:
    p1_DNB, p2_DNB   = lagens Draw-No-Bet-sannolikheter for JUST DENNA match (i procentenheter, 0-100)
    snitt1, snitt2   = lagens egna snittmal TOT (hemma+borta) over de senaste N matcherna
    b0, b1           = koefficienter fran ProbDiff/TOT-regressionen
    regressionssnitt = medelvardet av TOT i det data regressionen tranades pa

Anvandning:
    python3 tot_model.py <csv-fil> <lag1> <lag2> <hemmaodds> <oavgjortodds> <bortaodds>

Exempel:
    python3 tot_model.py "Sweden Ettan Norra/ettan-norra.csv" "FBK Karlstad" "AFC Eskilstuna" 2.500 3.600 2.300
"""

import csv
import sys

# Globala regressionskoefficienter (ProbDiff -> TOT)
B0 = 3.281111905
B1 = 0.008833483
REGRESSIONSSNITT = 3.6247

LAST_N = 20  # antal matcher per lag som ingar i snittet (minimum om sasongen har farre)

# Sasongsstart per liga ("YYYY-MM-DD"). Anvands for att avgora vilka matcher
# som racknas som "denna sasong" kontra "forra sasongen". Ligor utan
# tidigare-sasongsdata i sin CSV behover ingen post har - da fungerar allt
# som forut (bara de N senaste matcherna totalt, oavsett sasong).
SEASON_START = {
    "poland": "2026-06-01",
    "sweden-norra": "2026-04-03",   # hela filen ar en sasong - satts sa att
    "sweden-sodra": "2026-04-03",   # ">20 matcher -> anvand alla" gäller aven har
}


def load_matches(csv_path):
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    # sakerstall kronologisk ordning (aldst forst)
    rows.sort(key=lambda r: r["datum"])
    return rows


def team_matches(matches, team):
    """Alla matcher for ett lag, kronologiskt, aldst forst."""
    return [m for m in matches if m["hemmalag"] == team or m["bortalag"] == team]


def team_tot_snitt(matches, team, last_n=LAST_N, season_start=None):
    """
    Snitt TOT-mal (hemma+borta) for laget.

    Om season_start ar satt:
        - Om laget har spelat FLER an (eller lika med) last_n matcher DENNA
          sasong (datum >= season_start) -> anvand ALLA matcher fran denna
          sasong (ingen cap uppat).
        - Om laget har spelat FARRE matcher denna sasong (t.ex. 17) ->
          fyll pa med de senaste matcherna fran FORRA sasongen (datum <
          season_start) tills totalt last_n matcher (om det finns sa manga
          tillgangliga - annars anvands sa manga som finns).
    Om season_start ar None (eller ligan saknar tidigare-sasongsdata):
        - Gamla beteendet: de last_n senaste matcherna totalt, oavsett sasong.
    """
    tm = team_matches(matches, team)

    if season_start is None:
        tm = tm[-last_n:]  # de N senaste (listan ar kronologisk, aldst forst)
    else:
        current = [m for m in tm if m["datum"] >= season_start]
        if len(current) >= last_n:
            tm = current
        else:
            previous = [m for m in tm if m["datum"] < season_start]
            shortfall = last_n - len(current)
            fill = previous[-shortfall:]  # de senaste fran forra sasongen
            tm = fill + current

    if not tm:
        raise ValueError(f"Inga matcher hittades for '{team}'")
    tots = [int(m["hemmamal"]) + int(m["bortamal"]) for m in tm]
    return sum(tots) / len(tots), len(tm)


def dnb_probabilities(odds_home, odds_away):
    """Normaliserar 1X2-oddsen (exkl X) till Draw-No-Bet-sannolikheter, i procent (0-100)."""
    p_home_raw = 1 / odds_home
    p_away_raw = 1 / odds_away
    total = p_home_raw + p_away_raw
    p_home = p_home_raw / total * 100
    p_away = p_away_raw / total * 100
    return p_home, p_away


def predict_tot(snitt1, snitt2, p1_dnb, p2_dnb):
    """Racknar ut forvantat TOT-mal for matchen enligt modellen."""
    prob_diff = abs(p1_dnb - p2_dnb)
    regression_term = B0 + B1 * prob_diff
    baseline = (snitt1 + snitt2) / 2 / REGRESSIONSSNITT
    return regression_term * baseline


def predict_match(csv_path, team1, team2, odds_home, odds_draw, odds_away, last_n=LAST_N, season_start=None):
    """Kor hela flodet for en match: laddar data, raknar snitt + DNB, returnerar resultat."""
    matches = load_matches(csv_path)

    snitt1, n1 = team_tot_snitt(matches, team1, last_n, season_start)
    snitt2, n2 = team_tot_snitt(matches, team2, last_n, season_start)

    p1_dnb, p2_dnb = dnb_probabilities(odds_home, odds_away)

    tot = predict_tot(snitt1, snitt2, p1_dnb, p2_dnb)

    return {
        "team1": team1,
        "team2": team2,
        "snitt1": round(snitt1, 4),
        "snitt2": round(snitt2, 4),
        "matcher1": n1,
        "matcher2": n2,
        "p1_dnb": round(p1_dnb, 2),
        "p2_dnb": round(p2_dnb, 2),
        "prob_diff": round(abs(p1_dnb - p2_dnb), 2),
        "tot_forvantad": round(tot, 4),
    }


def main():
    if len(sys.argv) != 7:
        print(__doc__)
        sys.exit(1)

    csv_path = sys.argv[1]
    team1 = sys.argv[2]
    team2 = sys.argv[3]
    odds_home = float(sys.argv[4])
    odds_draw = float(sys.argv[5])
    odds_away = float(sys.argv[6])

    result = predict_match(csv_path, team1, team2, odds_home, odds_draw, odds_away)

    print(f"\n{result['team1']} - {result['team2']}")
    print(f"  Snitt TOT {result['team1']}: {result['snitt1']}  ({result['matcher1']} matcher)")
    print(f"  Snitt TOT {result['team2']}: {result['snitt2']}  ({result['matcher2']} matcher)")
    print(f"  DNB {result['team1']}: {result['p1_dnb']}%   DNB {result['team2']}: {result['p2_dnb']}%")
    print(f"  ProbDiff: {result['prob_diff']} procentenheter")
    print(f"  --> Forvantat TOT-mal: {result['tot_forvantad']}\n")


if __name__ == "__main__":
    main()
