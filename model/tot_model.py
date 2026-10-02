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
    python3 tot_model.py <csv-fil-eller-liga-nyckel> <lag1> <lag2> <hemmaodds> <oavgjortodds> <bortaodds>

Exempel:
    python3 tot_model.py sweden-norra "FBK Karlstad" "AFC Eskilstuna" 2.500 3.600 2.300

Mappstruktur (en mapp per land, en fil per sasong):
    Poland/II Liga/2025.csv, Poland/II Liga/2026.csv
    Sweden/Ettan Norra/2026.csv
    Sweden/Ettan Sodra/2026.csv
    Japan/J1/2025.csv
"""

import csv
import os
import sys

# Globala regressionskoefficienter (ProbDiff -> TOT)
B0 = 3.281111905
B1 = 0.008833483
REGRESSIONSSNITT = 3.6247

LAST_N = 20  # antal matcher per lag som ingar i snittet (minimum om sasongen har farre)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p(*parts):
    return os.path.join(_ROOT, *parts)


# Register per liga: vilka CSV-filer (en per sasong) som hor till ligan, och
# fran vilket datum ("YYYY-MM-DD") matcher racknas som "denna sasong". Filerna
# listas aldst-sasong-forst; det spelar ingen roll for load_matches (den
# sorterar om), men hall ordningen konsekvent for lasbarhetens skull.
LEAGUES = {
    "poland": {
        # II Liga 2025+2026, plus FORRA sasongens I Liga och III Liga (bada
        # grupperna) som fallback-kallor for lag som BYTTE NIVA i sommar:
        #   - GKS Tychy, Gornik Leczna: NEDFLYTTADE fran I Liga -> II Liga
        #   - Legia Warszawa II: UPPFLYTTADE fran III Liga Grupp 1 -> II Liga
        #   - Zawisza (Bydgoszcz): UPPFLYTTADE fran III Liga Grupp 2 -> II Liga
        #   - Zielona Gora (Lechia): UPPFLYTTADE fran III Liga Grupp 3 -> II Liga
        #     (enda overlappet mellan Grupp 3 forra sasongen och II Liga 2026;
        #     geografiskt rimligt - Grupp 3 tacker Nedre Schlesien/Lubusz, samma
        #     region som Lechia Zielona Gora, men klubbnamnet ar inte unikt pa
        #     samma satt som "Legia II"/"Zawisza" sa detta bygger pa geografisk
        #     plausibilitet snarare an 100% sakerhet)
        # De fa matcherna laget har spelat i II Liga hittills i ar fylls da
        # pa med sina gamla matcher fran ratt niva, istallet for att tunnas
        # ut till bara nagra fa matcher. Ingen namnkollision finns mellan
        # nivaerna forutom just dessa overgangslag (kontrollerat manuellt).
        # 2026-filerna for I Liga / III Liga racknas INTE in har - de ar
        # andra ligor just nu och skulle bara blanda in lag som aldrig
        # spelar i II Liga den har sasongen.
        "files": [
            _p("Poland", "II Liga", "2025.csv"),
            _p("Poland", "I Liga", "2025.csv"),
            _p("Poland", "III Liga Grupp 1", "2025.csv"),
            _p("Poland", "III Liga Grupp 2", "2025.csv"),
            _p("Poland", "III Liga Grupp 3", "2025.csv"),
            _p("Poland", "II Liga", "2026.csv"),
        ],
        "season_start": "2026-06-01",
    },
    "poland-i-liga": {
        "files": [_p("Poland", "I Liga", "2025.csv"), _p("Poland", "I Liga", "2026.csv")],
        "season_start": "2026-06-01",
    },
    "poland-iii-liga-1": {
        "files": [_p("Poland", "III Liga Grupp 1", "2025.csv"), _p("Poland", "III Liga Grupp 1", "2026.csv")],
        "season_start": "2026-06-01",
    },
    "poland-iii-liga-2": {
        "files": [_p("Poland", "III Liga Grupp 2", "2025.csv"), _p("Poland", "III Liga Grupp 2", "2026.csv")],
        "season_start": "2026-06-01",
    },
    "poland-iii-liga-3": {
        "files": [_p("Poland", "III Liga Grupp 3", "2025.csv"), _p("Poland", "III Liga Grupp 3", "2026.csv")],
        "season_start": "2026-06-01",
    },
    "poland-iii-liga-4": {
        "files": [_p("Poland", "III Liga Grupp 4", "2025.csv"), _p("Poland", "III Liga Grupp 4", "2026.csv")],
        "season_start": "2026-06-01",
    },
    "germany-3-liga": {
        # Uppflyttade fran Regionalliga i sommar (bekraftat via kollisionskoll,
        # bara ett overlapp per grupp): Meppen (North), Fortuna Koln (West),
        # Grossaspach (Sudwest), Wurzburger Kickers (Bayern). Dusseldorf och
        # Preussen Munster hittades inte i nagon Regionalliga-grupp - troligen
        # nedflyttade fran 2. Bundesliga istallet, ingen fallback-data for dem.
        "files": [
            _p("Germany", "3. Liga", "2025-26.csv"),
            _p("Germany", "Regionalliga North", "2025-26.csv"),
            _p("Germany", "Regionalliga West", "2025-26.csv"),
            _p("Germany", "Regionalliga Sudwest", "2025-26.csv"),
            _p("Germany", "Regionalliga Bayern", "2025-26.csv"),
            _p("Germany", "3. Liga", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "germany-regionalliga-north": {
        "files": [_p("Germany", "Regionalliga North", "2025-26.csv"), _p("Germany", "Regionalliga North", "2026-27.csv")],
        "season_start": "2026-07-01",
    },
    "germany-regionalliga-west": {
        "files": [_p("Germany", "Regionalliga West", "2025-26.csv"), _p("Germany", "Regionalliga West", "2026-27.csv")],
        "season_start": "2026-07-01",
    },
    "germany-regionalliga-sudwest": {
        # Ulm akte ner fran 3. Liga i sommar - 3. Ligas forra sasong laggs till
        # som fallback for dess TOT-snitt (enda overlappet, kollisionskollat).
        "files": [
            _p("Germany", "Regionalliga Sudwest", "2025-26.csv"),
            _p("Germany", "3. Liga", "2025-26.csv"),
            _p("Germany", "Regionalliga Sudwest", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "germany-regionalliga-nordost": {
        # Aue akte ner fran 3. Liga i sommar - samma fallback-logik som Sudwest.
        "files": [
            _p("Germany", "Regionalliga Nordost", "2025-26.csv"),
            _p("Germany", "3. Liga", "2025-26.csv"),
            _p("Germany", "Regionalliga Nordost", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "germany-regionalliga-bayern": {
        # Schweinfurt och Munich 1860 akte ner fran 3. Liga i sommar - samma
        # fallback-logik som Sudwest/Nordost.
        "files": [
            _p("Germany", "Regionalliga Bayern", "2025-26.csv"),
            _p("Germany", "3. Liga", "2025-26.csv"),
            _p("Germany", "Regionalliga Bayern", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "wales-cymru-premier": {
        # Cymru Premier expanderade fran 12 till 16 lag infor 2026/27: Airbus,
        # Llandudno, Holywell kom upp fran Cymru North och Ammanford, Trefelin,
        # Cambrian United fran Cymru South (bekraftat - enda overlappen mellan
        # North/South forra sasongen och Premier denna sasong). Bala och
        # Llanelli akte ner till North respektive South. North/South forra
        # sasongens filer laggs till som fallback for de uppflyttade lagens
        # TOT-snitt.
        "files": [
            _p("Wales", "Cymru Premier", "2025-26.csv"),
            _p("Wales", "Cymru North", "2025-26.csv"),
            _p("Wales", "Cymru South", "2025-26.csv"),
            _p("Wales", "Cymru Premier", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "wales-cymru-north": {
        # Bala akte ner fran Premier till North i sommar - Premier forra
        # sasongens fil laggs till som fallback for Balas TOT-snitt.
        "files": [
            _p("Wales", "Cymru North", "2025-26.csv"),
            _p("Wales", "Cymru Premier", "2025-26.csv"),
            _p("Wales", "Cymru North", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "wales-cymru-south": {
        # Llanelli akte ner fran Premier till South i sommar - samma fallback-
        # logik som for North/Bala.
        "files": [
            _p("Wales", "Cymru South", "2025-26.csv"),
            _p("Wales", "Cymru Premier", "2025-26.csv"),
            _p("Wales", "Cymru South", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "sweden-norra": {
        "files": [_p("Sweden", "Ettan Norra", "2026.csv")],
        "season_start": "2026-04-03",  # hela filen ar en sasong - "fler an
                                        # 20 matcher -> anvand alla" galler har med
    },
    "sweden-sodra": {
        "files": [_p("Sweden", "Ettan Sodra", "2026.csv")],
        "season_start": "2026-04-03",
    },
    "japan-j1": {
        "files": [_p("Japan", "J1", "2025.csv")],
        "season_start": None,  # bara en sasong i datan, ingen uppdelning behovs
    },
    # Kollisionskoll Japan J2: Albirex Niigata, Shonan Bellmare och Yokohama FC
    # ner fran J1 (2025) till J2 (sasongen 2026-27, ny host-vinter-kalender);
    # Chiba, Ehime, Kumamoto, Mito, Renofa Yamaguchi och V-Varen Nagasaki
    # lamnade J2 (sannolikt upp till J1 eller ner till J3, ospargat). Tegevajaro
    # Miyazaki, Tochigi City och Vanraure nya i J2 utan matchande roster i nagon
    # sparad liga (sannolikt uppflyttade fran J3, som vi inte har data for).
    "japan-j2": {
        "files": [
            _p("Japan", "J2", "2026.csv"),
            _p("Japan", "J2", "2025.csv"),
            _p("Japan", "J1", "2025.csv"),
        ],
        "season_start": "2026-08-08",
    },
    "czech-chance-liga": {
        # 2025-26.csv ar BARA slutspelsgrupperna (maj 2026, efter serien delats
        # upp) - inte hela sasongen - sa historiken ar tunn for lag som byttes
        # ut (uppflyttade/nedflyttade mellan sasongerna). Cupmatcher (Mol Cupen)
        # exkluderade medvetet - annan tavling, skulle snedvrida malsnittet.
        "files": [
            _p("Czech Republic", "Chance Liga", "2025-26.csv"),
            _p("Czech Republic", "Chance Liga", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-chnl": {
        "files": [
            _p("Czech Republic", "ChNL", "2025-26.csv"),
            _p("Czech Republic", "ChNL", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-3-cfl-group-a": {
        "files": [
            _p("Czech Republic", "3. CFL Group A", "2025-26.csv"),
            _p("Czech Republic", "3. CFL Group A", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-3-cfl-group-b": {
        "files": [
            _p("Czech Republic", "3. CFL Group B", "2025-26.csv"),
            _p("Czech Republic", "3. CFL Group B", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-3-msfl": {
        "files": [
            _p("Czech Republic", "3. MSFL", "2025-26.csv"),
            _p("Czech Republic", "3. MSFL", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-4-liga-group-a": {
        "files": [
            _p("Czech Republic", "4. Liga Group A", "2025-26.csv"),
            _p("Czech Republic", "4. Liga Group A", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-4-liga-group-b": {
        "files": [
            _p("Czech Republic", "4. Liga Group B", "2025-26.csv"),
            _p("Czech Republic", "4. Liga Group B", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-4-liga-group-c": {
        "files": [
            _p("Czech Republic", "4. Liga Group C", "2025-26.csv"),
            _p("Czech Republic", "4. Liga Group C", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-4-liga-group-d": {
        "files": [
            _p("Czech Republic", "4. Liga Group D", "2025-26.csv"),
            _p("Czech Republic", "4. Liga Group D", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-4-liga-group-e": {
        "files": [
            _p("Czech Republic", "4. Liga Group E", "2025-26.csv"),
            _p("Czech Republic", "4. Liga Group E", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    "czech-4-liga-group-f": {
        "files": [
            _p("Czech Republic", "4. Liga Group F", "2025-26.csv"),
            _p("Czech Republic", "4. Liga Group F", "2026-27.csv"),
        ],
        "season_start": "2026-07-01",
    },
    # Kollisionskoll UAE: Hatta + United FC upp fran Division 1 till UAE League;
    # Al Bataeh + Dibba Al Fujairah ner fran UAE League till Division 1.
    # Forte Virtus + Palm City nya i Division 1 utan matchande roster i nagon
    # av forra sasongens ligor (sannolikt uppflyttade fran en lag vi inte har data for).
    "uae-league": {
        "files": [
            _p("United Arab Emirates", "UAE League", "2025-26.csv"),
            _p("United Arab Emirates", "Division 1", "2025-26.csv"),
            _p("United Arab Emirates", "UAE League", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "uae-division-1": {
        "files": [
            _p("United Arab Emirates", "Division 1", "2025-26.csv"),
            _p("United Arab Emirates", "UAE League", "2025-26.csv"),
            _p("United Arab Emirates", "Division 1", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    # Skottland: Premiership - Championship - League One - League Two - (Highland/Lowland).
    # Kollisionskoll bekraftade: St Johnstone upp Championship->Premiership, Livingston ner
    # motsatt hall; Inverness + Stenhousemuir upp League One->Championship, Queen of South +
    # Airdrieonians + Ross County + Alloa ner motsatt hall; East Kilbride upp League Two->
    # League One, Hamilton likasa (League Two->League One); Kelty Hearts ner League One->
    # League Two; Brora Rangers ner League Two->Highland League. Invergordon (Highland) och
    # ett antal nya lag i Lowland League saknar matchande roster i nagon sparad liga forra
    # sasongen (sannolikt uppflyttade fran en lagre, ospargad liga - ingen fallback-data finns).
    "scotland-premiership": {
        "files": [
            _p("Scotland", "Premiership", "2025-26.csv"),
            _p("Scotland", "Championship", "2025-26.csv"),
            _p("Scotland", "Premiership", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "scotland-championship": {
        "files": [
            _p("Scotland", "Championship", "2025-26.csv"),
            _p("Scotland", "Premiership", "2025-26.csv"),
            _p("Scotland", "League One", "2025-26.csv"),
            _p("Scotland", "Championship", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "scotland-league-one": {
        "files": [
            _p("Scotland", "League One", "2025-26.csv"),
            _p("Scotland", "Championship", "2025-26.csv"),
            _p("Scotland", "League Two", "2025-26.csv"),
            _p("Scotland", "League One", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "scotland-league-two": {
        "files": [
            _p("Scotland", "League Two", "2025-26.csv"),
            _p("Scotland", "League One", "2025-26.csv"),
            _p("Scotland", "Highland League", "2025-26.csv"),
            _p("Scotland", "Lowland League", "2025-26.csv"),
            _p("Scotland", "League Two", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "scotland-highland": {
        "files": [
            _p("Scotland", "Highland League", "2025-26.csv"),
            _p("Scotland", "League Two", "2025-26.csv"),
            _p("Scotland", "Lowland League", "2025-26.csv"),
            _p("Scotland", "Highland League", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "scotland-lowland": {
        "files": [
            _p("Scotland", "Lowland League", "2025-26.csv"),
            _p("Scotland", "League Two", "2025-26.csv"),
            _p("Scotland", "Highland League", "2025-26.csv"),
            _p("Scotland", "Lowland League", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    # Slovakien: Nike liga - 2. Liga - (3. Liga Central/East/West, tre parallella
    # regionala grupper under 2. Liga). Kollisionskoll bekraftade: Banska Bystrica +
    # Komarno upp 2.Liga->Nike liga, Presov ner motsatt hall; MFK Bytca upp 3.Liga
    # Central->2.Liga; FK Humenne upp 3.Liga East->2.Liga, Slavia TU Kosice + Lubovna
    # ner motsatt hall; Galanta upp 3.Liga West->2.Liga, Puchov ner motsatt hall.
    "slovakia-nike-liga": {
        "files": [
            _p("Slovakia", "Nike Liga", "2025-26.csv"),
            _p("Slovakia", "2. Liga", "2025-26.csv"),
            _p("Slovakia", "Nike Liga", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "slovakia-2-liga": {
        "files": [
            _p("Slovakia", "2. Liga", "2025-26.csv"),
            _p("Slovakia", "Nike Liga", "2025-26.csv"),
            _p("Slovakia", "3. Liga Central", "2025-26.csv"),
            _p("Slovakia", "3. Liga East", "2025-26.csv"),
            _p("Slovakia", "3. Liga West", "2025-26.csv"),
            _p("Slovakia", "2. Liga", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "slovakia-3-liga-central": {
        "files": [
            _p("Slovakia", "3. Liga Central", "2025-26.csv"),
            _p("Slovakia", "2. Liga", "2025-26.csv"),
            _p("Slovakia", "3. Liga Central", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "slovakia-3-liga-east": {
        "files": [
            _p("Slovakia", "3. Liga East", "2025-26.csv"),
            _p("Slovakia", "2. Liga", "2025-26.csv"),
            _p("Slovakia", "3. Liga East", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    "slovakia-3-liga-west": {
        "files": [
            _p("Slovakia", "3. Liga West", "2025-26.csv"),
            _p("Slovakia", "2. Liga", "2025-26.csv"),
            _p("Slovakia", "3. Liga West", "2026-27.csv"),
        ],
        "season_start": "2026-07-15",
    },
    # Slovenien: Prva liga - 2. SNL - (3. SNL East/West). Kollisionskoll bekraftade:
    # Nafta + Grosuplje upp 2.SNL->Prva liga, Primorje ner motsatt hall; Brezice upp
    # 3.SNL East->2.SNL; Vrhnika upp 3.SNL West->2.SNL. Domzale (lamnade Prva liga),
    # ND Gorica (lamnade 2.SNL), samt flera nya lag i 3.SNL East (NK Ormoz, Odranci,
    # Sampion Celje, Limbus-Pekre) och West (NK Adria, Litija) saknar matchande
    # roster nagonstans - sannolikt fran ospargade lagre ligor eller nedflyttade dit.
    "slovenia-prva-liga": {
        "files": [
            _p("Slovenia", "Prva Liga", "2025-26.csv"),
            _p("Slovenia", "2. SNL", "2025-26.csv"),
            _p("Slovenia", "Prva Liga", "2026-27.csv"),
        ],
        "season_start": "2026-07-10",
    },
    "slovenia-2-snl": {
        "files": [
            _p("Slovenia", "2. SNL", "2025-26.csv"),
            _p("Slovenia", "Prva Liga", "2025-26.csv"),
            _p("Slovenia", "3. SNL East", "2025-26.csv"),
            _p("Slovenia", "3. SNL West", "2025-26.csv"),
            _p("Slovenia", "2. SNL", "2026-27.csv"),
        ],
        "season_start": "2026-07-10",
    },
    "slovenia-3-snl-east": {
        "files": [
            _p("Slovenia", "3. SNL East", "2025-26.csv"),
            _p("Slovenia", "2. SNL", "2025-26.csv"),
            _p("Slovenia", "3. SNL East", "2026-27.csv"),
        ],
        "season_start": "2026-07-10",
    },
    "slovenia-3-snl-west": {
        "files": [
            _p("Slovenia", "3. SNL West", "2025-26.csv"),
            _p("Slovenia", "2. SNL", "2025-26.csv"),
            _p("Slovenia", "3. SNL West", "2026-27.csv"),
        ],
        "season_start": "2026-07-10",
    },
    # Belgien. Historiken skrapades utan 1X2-odds (anvandaren bad om det) -
    # hemmaodds/oavgjortodds/bortaodds ar tomma i alla dessa CSV-filer, men det
    # paverkar inte value-bet-scanningen - se LEAGUE_SLUGS i scan_league.py,
    # som sedan 2026-10-02 hamtar LIVE-odds fran odds-api.io for de flesta av
    # dessa ligor (nagra mindre divisioner saknas helt hos odds-api.io).
    "belgium-jupiler-pro-league": {
        "files": [
            _p("Belgium", "Jupiler Pro League", "2025-26.csv"),
            _p("Belgium", "Jupiler Pro League", "2026-27.csv"),
        ],
        "season_start": "2026-08-07",
    },
    "belgium-challenger-pro-league": {
        "files": [
            _p("Belgium", "Challenger Pro League", "2025-26.csv"),
            _p("Belgium", "Challenger Pro League", "2026-27.csv"),
        ],
        "season_start": "2026-08-14",
    },
    "belgium-national-division-1-acff": {
        "files": [
            _p("Belgium", "National Division 1 - ACFF", "2025-26.csv"),
            _p("Belgium", "National Division 1 - ACFF", "2026-27.csv"),
        ],
        "season_start": "2026-08-26",
    },
    "belgium-national-division-1-vv": {
        "files": [
            _p("Belgium", "National Division 1 - VV", "2025-26.csv"),
            _p("Belgium", "National Division 1 - VV", "2026-27.csv"),
        ],
        "season_start": "2026-08-28",
    },
    "belgium-second-amateur-division-acff": {
        "files": [
            _p("Belgium", "Second Amateur Division Group ACFF", "2025-26.csv"),
            _p("Belgium", "Second Amateur Division Group ACFF", "2026-27.csv"),
        ],
        "season_start": "2026-08-22",
    },
    "belgium-second-amateur-division-vfv-a": {
        "files": [
            _p("Belgium", "Second Amateur Division Group VFV A", "2025-26.csv"),
            _p("Belgium", "Second Amateur Division Group VFV A", "2026-27.csv"),
        ],
        "season_start": "2026-08-29",
    },
    "belgium-second-amateur-division-vfv-b": {
        "files": [
            _p("Belgium", "Second Amateur Division Group VFV B", "2025-26.csv"),
            _p("Belgium", "Second Amateur Division Group VFV B", "2026-27.csv"),
        ],
        "season_start": "2026-08-29",
    },
    "belgium-super-league-women": {
        "files": [
            _p("Belgium", "Super League Women", "2025-26.csv"),
            _p("Belgium", "Super League Women", "2026-27.csv"),
        ],
        "season_start": "2026-09-05",
    },
    "belgium-1st-national-women": {
        "files": [
            _p("Belgium", "1st National Women", "2025-26.csv"),
            _p("Belgium", "1st National Women", "2026-27.csv"),
        ],
        "season_start": "2026-08-29",
    },
    # Danmark. Historiken skrapades utan 1X2-odds (samma upplagg som Belgien
    # ovan), men alla fyra ligorna far nu LIVE-odds fran odds-api.io - se
    # LEAGUE_SLUGS i scan_league.py (verifierat 2026-10-02).
    "denmark-superliga": {
        "files": [
            _p("Denmark", "Superliga", "2025-26.csv"),
            _p("Denmark", "Superliga", "2026-27.csv"),
        ],
        "season_start": "2026-07-24",
    },
    "denmark-1st-division": {
        "files": [
            _p("Denmark", "1st Division", "2025-26.csv"),
            _p("Denmark", "1st Division", "2026-27.csv"),
        ],
        "season_start": "2026-07-24",
    },
    "denmark-2nd-division": {
        "files": [
            _p("Denmark", "2nd Division", "2025-26.csv"),
            _p("Denmark", "2nd Division", "2026-27.csv"),
        ],
        "season_start": "2026-07-31",
    },
    "denmark-3rd-division": {
        "files": [
            _p("Denmark", "3rd Division", "2025-26.csv"),
            _p("Denmark", "3rd Division", "2026-27.csv"),
        ],
        "season_start": "2026-07-31",
    },
}

# Bakatkompatibel genvag: SEASON_START["poland"] etc.
SEASON_START = {key: cfg["season_start"] for key, cfg in LEAGUES.items()}


def load_matches(csv_paths):
    """
    Laddar matcher fran en eller flera CSV-filer (en fil per sasong).
    csv_paths kan vara en enda sokvag (str) eller en lista av sokvagar -
    filerna slas ihop och sorteras kronologiskt tillsammans.
    """
    if isinstance(csv_paths, str):
        csv_paths = [csv_paths]

    rows = []
    for path in csv_paths:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    # sakerstall kronologisk ordning (aldst forst) over ALLA sasonger
    rows.sort(key=lambda r: r["datum"])
    return rows


def load_league(league_key):
    """Laddar alla matcher (samtliga registrerade sasongsfiler) for en liga."""
    return load_matches(LEAGUES[league_key]["files"])


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
    """
    Kor hela flodet for en match: laddar data, raknar snitt + DNB, returnerar resultat.
    csv_path kan vara en enda fil, eller en lista av filer (t.ex. bade forra
    och denna sasongens CSV) - se load_matches().
    """
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


def predict_league_match(league_key, team1, team2, odds_home, odds_draw, odds_away, last_n=LAST_N):
    """Bekvam genvag: slar upp filer + season_start automatiskt fran LEAGUES[league_key]."""
    cfg = LEAGUES[league_key]
    return predict_match(cfg["files"], team1, team2, odds_home, odds_draw, odds_away,
                          last_n=last_n, season_start=cfg["season_start"])


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

    # Om forsta argumentet matchar en registrerad liga-nyckel, anvand den
    # (med ratt filer + season_start automatiskt). Annars: tolka som en
    # vanlig CSV-sokvag (gammalt beteende, ingen season-uppdelning).
    if csv_path in LEAGUES:
        result = predict_league_match(csv_path, team1, team2, odds_home, odds_draw, odds_away)
    else:
        result = predict_match(csv_path, team1, team2, odds_home, odds_draw, odds_away)

    print(f"\n{result['team1']} - {result['team2']}")
    print(f"  Snitt TOT {result['team1']}: {result['snitt1']}  ({result['matcher1']} matcher)")
    print(f"  Snitt TOT {result['team2']}: {result['snitt2']}  ({result['matcher2']} matcher)")
    print(f"  DNB {result['team1']}: {result['p1_dnb']}%   DNB {result['team2']}: {result['p2_dnb']}%")
    print(f"  ProbDiff: {result['prob_diff']} procentenheter")
    print(f"  --> Forvantat TOT-mal: {result['tot_forvantad']}\n")


if __name__ == "__main__":
    main()
