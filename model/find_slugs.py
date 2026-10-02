"""
Hjalpskript: hittar odds-api.io:s riktiga slugs for en liga du letar efter,
genom att soka pa ett sokord (t.ex. "belgium" eller "denmark") bland ALLA
fotbollsligor odds-api.io kanner till.

Anvands for att hitta ratta slugs till LEAGUE_SLUGS i scan_league.py nar en
ny liga (t.ex. Belgien/Danmark) ska laggas till for value-bet-skanning.

Maste koras i en miljo med riktig natverksatkomst till api.odds-api.io
(fungerar INTE i Claudes sandlada - kor detta lokalt eller pa din egen
server/VPS, precis som scan_league.py).

Miljovariabel som kravs: ODDS_API_KEY (las in fran .env, se telegram_bot.load_env)

Anvandning:
    python3 find_slugs.py belgium
    python3 find_slugs.py denmark
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from verify_slugs import get_all_football_leagues


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    term = sys.argv[1].lower()
    leagues = get_all_football_leagues()
    print(f"Hittade {len(leagues)} fotbollsligor totalt hos odds-api.io.\n")

    matches = [lg for lg in leagues if term in lg.get("slug", "").lower() or term in lg.get("name", "").lower()]
    if not matches:
        print(f"Inga traffar for '{term}'.")
        return

    print(f"Traffar for '{term}':")
    for lg in matches:
        print(f"  slug={lg['slug']!r:45s}  namn={lg.get('name', '')}")


if __name__ == "__main__":
    main()
