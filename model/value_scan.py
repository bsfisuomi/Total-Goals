"""
Value-scanner: jamfor modellens TOT-prognos mot Bet365s Totals-marknad (over/under)
och flaggar var det finns value.

Matematik:
    Om mal_hemma ~ Poisson(mu_h) och mal_borta ~ Poisson(mu_a) oberoende,
    sa ar totalmal i matchen ~ Poisson(mu_h + mu_a) = Poisson(TOT).
    Vi behover alltsa INTE dela upp TOT i mu_h/mu_a for att prissatta
    Totals-marknaden - TOT-prognosen anvands direkt som Poisson-rate.

Kvartslinjer (t.ex. 2.25, 2.75) hanteras som i Asian Handicap: halva insatsen
pa vardera av de tva narmaste halv-/heltalslinjerna (samma metod som
AH-kalkylatorn tidigare i projektet).
"""

import math
import sys
import json


def poisson_pmf(k, rate):
    return math.exp(-rate) * rate**k / math.factorial(k)


def poisson_cdf(k, rate):
    """P(X <= k)"""
    return sum(poisson_pmf(i, rate) for i in range(0, k + 1))


def over_under_prob(rate, line, max_goals=25):
    """
    Returnerar (p_over, p_under) for en given totals-linje.
    Hanterar heltalslinjer (push mojlig -> pushen exkluderas, prop.
    fordelas), halvlinjer (rena) och kvartslinjer (medelvarde av
    tva narliggande halv-/heltalslinjer, Asian-stil).
    """
    frac = line - math.floor(line)

    if abs(frac - 0.5) < 1e-9:
        # ren halvlinje, t.ex. 2.5
        threshold = math.floor(line)
        p_under = poisson_cdf(threshold, rate)
        p_over = 1 - p_under
        return p_over, p_under

    if abs(frac) < 1e-9:
        # heltalslinje, t.ex. 3.0 -> push mojlig vid exakt 3 mal
        p_push = poisson_pmf(int(line), rate)
        p_under = poisson_cdf(int(line) - 1, rate)
        p_over = 1 - p_under - p_push
        # normalisera bort pushen (andelen av aterstoden)
        remaining = p_over + p_under
        return p_over / remaining, p_under / remaining

    # kvartslinje: medelvarde av de tva narmaste "rena" linjerna
    lower = math.floor(line * 2) / 2   # narmaste halv-/heltal under
    upper = lower + 0.5
    p_over_l, p_under_l = over_under_prob(rate, lower, max_goals)
    p_over_u, p_under_u = over_under_prob(rate, upper, max_goals)
    return (p_over_l + p_over_u) / 2, (p_under_l + p_under_u) / 2


def find_value(model_tot, bet365_totals, min_edge=0.04):
    """
    bet365_totals: lista av dict {"hdp": float, "over": odds, "under": odds}
    (samma format som API:ts "Totals"-marknad)

    min_edge: minsta skillnad (i sannolikhet, 0-1) for att raknas som value

    Returnerar lista av value-traffar: [{"line":..., "sida":"Over"/"Under",
        "bet365_odds":..., "modell_sannolikhet":..., "bet365_implicerad":..., "edge":...}]
    """
    hits = []
    for row in bet365_totals:
        line = row["hdp"]
        odds_over = float(row["over"])
        odds_under = float(row["under"])

        p_over, p_under = over_under_prob(model_tot, line)

        implied_over = 1 / odds_over
        implied_under = 1 / odds_under

        edge_over = p_over - implied_over
        edge_under = p_under - implied_under

        if edge_over >= min_edge:
            hits.append({
                "line": line, "sida": "Over", "bet365_odds": odds_over,
                "modell_sannolikhet": round(p_over * 100, 2),
                "bet365_implicerad": round(implied_over * 100, 2),
                "edge_procentenheter": round(edge_over * 100, 2),
            })
        if edge_under >= min_edge:
            hits.append({
                "line": line, "sida": "Under", "bet365_odds": odds_under,
                "modell_sannolikhet": round(p_under * 100, 2),
                "bet365_implicerad": round(implied_under * 100, 2),
                "edge_procentenheter": round(edge_under * 100, 2),
            })
    return hits


def find_goal_line_value(model_tot, goal_line_odds, min_ev=0.10):
    """
    Filter for Telegram-alerts. Anvander ENDAST Bet365s "Goal Line"-marknad
    (odds-api.io kallar den "Goals Over/Under") - Bet365s asiatiska
    totalmalsmarknad med en central linje per match (t.ex. 2.5, ibland en
    kvartslinje som 2.75). Detta ar INTE samma marknad som "Totals"
    (som har manga alternativa linjer och ibland saknar den centrala helt),
    och 1X2-marknaden anvands inte alls for dessa alerts.

    goal_line_odds: lista av dict {"hdp": float, "over": odds, "under": odds}
    fran Bet365s "Goals Over/Under"-marknad (vanligtvis bara EN rad, men
    funktionen hanterar flera om de skulle finnas - valjer den narmast 50%).

    min_ev: minsta EV (som andel, 0.10 = 10%) for att raknas som en trigger

    Returnerar None om ingen sida triggar, annars en dict:
        {"line", "sida", "bet365_odds", "modell_sannolikhet", "fair_odds",
         "edge_procentenheter", "ev_procent"}
    """
    if not goal_line_odds:
        return None

    # hitta linjen vars over-sannolikhet ligger narmast 50% (normalt bara en rad)
    best_row = None
    best_dist = None
    best_p_over = None
    best_p_under = None
    for row in goal_line_odds:
        line = row["hdp"]
        p_over, p_under = over_under_prob(model_tot, line)
        dist = abs(p_over - 0.5)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_row = row
            best_p_over = p_over
            best_p_under = p_under

    line = best_row["hdp"]
    odds_over = float(best_row["over"])
    odds_under = float(best_row["under"])

    ev_over = best_p_over * odds_over - 1
    ev_under = best_p_under * odds_under - 1

    if ev_over >= ev_under and ev_over >= min_ev:
        p, odds, sida = best_p_over, odds_over, "Over"
        ev = ev_over
    elif ev_under > ev_over and ev_under >= min_ev:
        p, odds, sida = best_p_under, odds_under, "Under"
        ev = ev_under
    else:
        return None

    implied = 1 / odds
    return {
        "line": line, "sida": sida, "bet365_odds": odds,
        "modell_sannolikhet": round(p * 100, 2),
        "fair_odds": round(1 / p, 3),
        "bet365_implicerad": round(implied * 100, 2),
        "edge_procentenheter": round((p - implied) * 100, 2),
        "ev_procent": round(ev * 100, 2),
    }


if __name__ == "__main__":
    # Exempel/test: TOT=2.84, en typisk Totals-marknad
    example_totals = [
        {"hdp": 2.5, "over": 1.900, "under": 1.900},
        {"hdp": 2.75, "over": 2.100, "under": 1.700},
        {"hdp": 3.0, "over": 2.375, "under": 1.533},
    ]
    result = find_value(2.84, example_totals, min_edge=0.0)
    print(json.dumps(result, indent=2, ensure_ascii=False))
