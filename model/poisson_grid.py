"""
Poisson-rutnat: delar upp modellens TOT-prognos i mu_hemma/mu_borta
(proportionellt mot matchens DNB-sannolikheter) och raknar ut hela
resultatfordelningen -> 1X2, Draw-No-Bet, med mera. Anvands for att
hitta value aven pa 1X2-marknaden, inte bara Totals.

mu_hemma = TOT * p_hemma_DNB
mu_borta = TOT * p_borta_DNB

P(hemma=i, borta=j) = Poisson_pmf(i, mu_hemma) * Poisson_pmf(j, mu_borta)
"""

import math


def poisson_pmf(k, rate):
    return math.exp(-rate) * rate**k / math.factorial(k)


def split_mu(tot, p_home_dnb_pct, p_away_dnb_pct):
    """DNB-sannolikheter i procent (0-100) -> mu_hemma, mu_borta"""
    p_home = p_home_dnb_pct / 100
    p_away = p_away_dnb_pct / 100
    return tot * p_home, tot * p_away


def score_grid(mu_home, mu_away, max_goals=10):
    grid = {}
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            grid[(i, j)] = poisson_pmf(i, mu_home) * poisson_pmf(j, mu_away)
    return grid


def match_probabilities(grid):
    p_home = sum(p for (i, j), p in grid.items() if i > j)
    p_draw = sum(p for (i, j), p in grid.items() if i == j)
    p_away = sum(p for (i, j), p in grid.items() if i < j)
    total = p_home + p_draw + p_away  # normalisera bort svansen (>max_goals)
    return p_home / total, p_draw / total, p_away / total


def value_1x2(tot, p_home_dnb, p_away_dnb, odds_home, odds_draw, odds_away, min_edge=0.0):
    mu_home, mu_away = split_mu(tot, p_home_dnb, p_away_dnb)
    grid = score_grid(mu_home, mu_away)
    p_home, p_draw, p_away = match_probabilities(grid)

    results = []
    for sida, p_modell, odds in [
        ("Hemma", p_home, odds_home),
        ("Oavgjort", p_draw, odds_draw),
        ("Borta", p_away, odds_away),
    ]:
        implied = 1 / odds
        edge = p_modell - implied
        if edge >= min_edge:
            results.append({
                "sida": sida,
                "bet365_odds": odds,
                "modell_sannolikhet": round(p_modell * 100, 2),
                "bet365_implicerad": round(implied * 100, 2),
                "edge_procentenheter": round(edge * 100, 2),
            })
    return {
        "mu_home": round(mu_home, 4),
        "mu_away": round(mu_away, 4),
        "p_home": round(p_home * 100, 2),
        "p_draw": round(p_draw * 100, 2),
        "p_away": round(p_away * 100, 2),
        "value": results,
    }


if __name__ == "__main__":
    r = value_1x2(2.7232, 47.92, 52.08, 2.500, 3.600, 2.300, min_edge=0.0)
    import json
    print(json.dumps(r, indent=2, ensure_ascii=False))
