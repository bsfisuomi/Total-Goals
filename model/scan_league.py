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
    python3 scan_league.py all                                     # skannar ALLA ligor

Exempel:
    python3 scan_league.py poland sweden-norra sweden-sodra
    python3 scan_league.py poland sweden-norra sweden-sodra --send   # skickar till Telegram
    python3 scan_league.py all --send

Liga-nycklar: se LEAGUES i tot_model.py.

Med --send: value-fynd som redan skickats till Telegram tidigare (sparas i
sent_bets.json i projektroten) skickas INTE igen - bara nya fynd. De syns
fortfarande i den vanliga utskriften pa skarmen, bara inte i det som gar
till Telegram.
"""

import os
import sys
import time
import json
import gzip
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from tot_model import load_league, team_tot_snitt, dnb_probabilities, predict_tot, LAST_N, LEAGUES
from value_scan import find_goal_line_value
from telegram_bot import format_value_bet, format_report, format_report_chunks, send_message, load_env

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
    "poland-iii-liga-4": ["poland-iii-liga-group-4"],  # OBS: gissad slug, ej verifierad mot /leagues

    "germany-3-liga": ["germany-3-liga"],
    "germany-regionalliga-north": ["germany-amateur-regionalliga-north"],
    "germany-regionalliga-west": ["germany-amateur-regionalliga-west"],
    "germany-regionalliga-sudwest": ["germany-amateur-regionalliga-southwest"],
    "germany-regionalliga-nordost": ["germany-amateur-regionalliga-northeast"],
    "germany-regionalliga-bayern": ["germany-amateur-regionalliga-bavaria"],

    "wales-cymru-premier": ["wales-cymru-premier"],
    "wales-cymru-north": ["wales-cymru-championship-north"],
    "wales-cymru-south": ["wales-cymru-championship-south"],

    "japan-j1": ["japan-jleague"],
    "japan-j2": ["japan-jleague-2"],

    "czech-chance-liga": ["czech-republic-chance-liga"],  # OBS: gissad slug, ej verifierad mot /leagues
    "czech-chnl": ["czech-republic-chnl"],  # OBS: gissad slug, ej verifierad mot /leagues

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

MIN_EV = 0.13  # minsta EV for att trigga en Telegram-alert (se find_goal_line_value)

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

    # Polen I Liga
    "Bruk-Bet Termalica Nieciecza": "Termalica B-B.", "FKS Stal Mielec": "Stal Mielec",
    "KS Lechia Gdansk": "Lechia Gdansk", "MKS Arka Gdynia": "Arka Gdynia",
    "Miedz Legnica": "Legnica", "Podbeskidzie Bielsko-Biala": "Podbeskidzie",
    "Pogon Grodzisk Mazowiecki": "Grodzisk M.", "Puszcza Niepolomice": "Puszcza",
    "Unia Skierniewice": "Skierniewice", "ZKS Stal Rzeszow": "S. Rzeszow",
    # Polen III Liga grupp 1
    "Jagiellonia II Bialystok": "Jagiellonia II", "KS Ck Troszyn": "Troszyn",
    "KS Pelikan Lowicz": "Pelikan", "KS Warta Sieradz": "Warta Sieradz",
    "KTS Weszlo Warszawa": "Weszlo", "LKS 1926 Lomza": "LKS Lomza",
    "Lechia Tomaszow Mazowiecki": "T. Mazowiecki", "MKS Mlawianka Mlawa": "Mlawa",
    "MKS Polonia Lidzbark Warminski": "Lidzbark Warminski", "Olimpia Zambrow": "Zambrow",
    "SK Mazovia Minsk Mazowiecki": "Mazovia Minsk Mazowiecki",
    "Swit Nowy Dwor Mazowiecki": "Swit Mazowiecki",
    # Polen III Liga grupp 2
    "KKS 1925 Kalisz": "KKS Kalisz", "KS Lipno Steszew": "Lipno Steszew",
    "Kss Kotwica Kornik": "Kotwica Kornik", "Lech II Poznan": "Lech Poznan II",
    "MKS Flota Swinoujscie": "Swinoujscie", "MKS Notec Czarnkow": "Notec Czarnkow",
    "MKS Viktoria Wrzesnia": "Wrzesnia", "Polonia Sroda Wielkopolska": "Sroda",
    "Sks Unia Swarzedz": "Unia Swarzedz", "WDA Swiecie": "Wda Swiecie",
    "Wiked Luzino": "Luzino", "Zks Kluczevia Stargard": "Kluczevia Stargard",
    # Polen III Liga grupp 3
    "BTP Stal Brzeg": "Brzeg", "Barycz Sulow": "Sulow",
    "KS Gornik Polkowice": "Polkowice", "KS Polonia Nysa": "Nysa",
    "KS Row 1964 Rybnik": "ROW Rybnik", "KS Sleza Wroclaw": "Sleza Wroclaw",
    "KS Stilon Gorzow Wlkp": "Stilon Gorzow", "Karkonosze Jelenia Gora": "Jelenia Gora",
    "LKS Goczalkowice-Zdroj": "Goczalkowice Zdroj", "MKS Kluczbork": "Kluczbork",
    "Miedz Legnica II": "Legnica II", "Mkp Carina Gubin": "Carina Gubin",
    # Polen III Liga grupp 4
    "AKS 1947 Busko Zdroj": "Busko-Zdroj", "JKS 1909 Jaroslaw": "Jaroslaw",
    "KS Hetman Zamosc": "Hetman Zamosc", "KS Naprzod Jedrzejow": "Naprzod Jedrzejow",
    "KS Wisloka Debica": "Wisloka Debica", "KSZO Ostrowiec Swietokrzyski": "Ostrowiec Swietokrzyski",
    "Korona II Kielce SA": "Korona Kielce II", "MKS Czarni Polaniec": "Czarni Polaniec",
    "MKS Podlasie Biala Podlaska": "Biala Podlaska", "Pogon Sokol Lubaczow": "Lubaczow",
    "Sokol Kolbuszowa Dolna": "Kolbuszowa Dolna", "Wieczysta II Krakow": "Wieczysta Krakow II",
    "Wisla II Krakow": "Wisla II",

    # Tyskland 3. Liga
    "1. FC Saarbrucken": "Saarbrucken", "FC Ingolstadt 04": "Ingolstadt",
    "FC Viktoria Cologne": "Viktoria Koln", "FC Wurzburger Kickers": "Wurzburger Kickers",
    "Fortuna Cologne": "Fortuna Koln", "Fortuna Dusseldorf": "Dusseldorf",
    "Jahn Regensburg": "Regensburg", "MSV Duisburg": "Duisburg",
    "Rot-Weiss Essen": "RW Essen", "SC Preussen 06 Munster": "Preussen Munster",
    "SC Verl": "Verl", "SG Sonnenhof Grossaspach": "Grossaspach",
    # Tyskland Regionalliga Nord
    "1. FC Phonix Lubeck": "Phonix Lubeck", "Bremer SV 1906": "Bremer",
    "Eimsbutteler TV": "Eimsbutteler", "Eintracht Norderstedt": "Norderstedt",
    "FC St. Pauli II": "St. Pauli II", "FSV Schoningen 2011": "Schoningen",
    "HSC Hannover": "Hannoverscher SC", "Hannover 96 II": "Hannover II",
    "Kickers Emden": "Emden", "SC Weiche Flensburg 08": "SC Weiche-08",
    "SSV Jeddeloh II": "Jeddeloh", "SV Atlas Delmenhorst": "Delmenhorst",
    # Tyskland Regionalliga West
    "1. FC Bocholt": "Bocholt", "1. FC Cologne II": "Koln II",
    "Bonner SC": "Bonner", "Borussia Dortmund II": "Dortmund II",
    "Borussia Monchengladbach II": "B. Monchengladbach II",
    "FC Gutersloh 2000": "FC Gutersloh", "FC Schalke 04 II": "Schalke II",
    "RW Oberhausen": "Oberhausen", "SC Paderborn 07 II": "Paderborn II",
    "SC Wiedenbruck": "Wiedenbruck", "SG Wattenscheid 09": "SG Wattenscheid",
    "SV Bergisch Gladbach 09": "Bergisch Gladbach",
    # Tyskland Regionalliga Sudwest
    "1. FC Kaiserslautern II": "Kaiserslautern II", "FC 08 Homburg-Saar": "FC 08 Homburg",
    "FC Astoria Walldorf": "Walldorf", "FSV Frankfurt 1899": "FSV Frankfurt",
    "FSV Mainz II": "Mainz II", "KSV Hessen Kassel": "Kassel",
    "Offenbacher FC Kickers 1901": "Offenbach", "SC Freiburg II": "Freiburg II",
    "SG Barockstadt Fulda-Lehnerz": "Fulda-Lehnerz", "SGV Freiberg": "Freiberg",
    "SSV Ulm 1846": "Ulm", "SV Sandhausen": "Sandhausen",
    # Tyskland Regionalliga Nordost
    "1. FC Lokomotive Leipzig": "Lokomotive Leipzig", "BFC Preussen Berlin": "BFC Preussen",
    "BSG Chemie Leipzig": "Chemie Leipzig", "Chemnitzer FC": "Chemnitzer",
    "Erzgebirge Aue": "Aue", "FC Carl Zeiss Jena": "Jena",
    "FC Magdeburg II": "Magdeburg II", "FC Rot-Weiss Erfurt": "Erfurt",
    "FSV Luckenwalde": "Luckenwalde", "FSV Zwickau": "Zwickau",
    "Greifswalder FC": "Greifswald", "Hallescher FC": "Hallescher",
    # Tyskland Regionalliga Bayern
    "1 FC Nuremberg II": "Nurnberg II", "1. FC Schweinfurt 05": "Schweinfurt",
    "Bayern Munich II": "Bayern II", "DJK Vilzing": "Vilzing",
    "FC Augsburg II": "Augsburg II", "FC Memmingen": "Memmingen",
    "FV Illertissen": "Illertissen", "Greuther Furth II": "Furth II",
    "SC Eltersdorf": "Eltersdorf", "SpVgg Ansbach": "Ansbach",
    "SpVgg Bayreuth": "Bayreuth", "SpVgg Unterhaching": "Unterhaching",

    # Wales Cymru Premier
    "Airbus UK Broughton": "Airbus", "Barry Town United FC": "Barry",
    "Caernarfon Town FC": "Caernarfon", "Cardiff Metropolitan University FC": "Cardiff Metropolitan",
    "Connah's Quay Nomads FC": "Connahs Q.", "Flint Town United": "Flint",
    "Haverfordwest County AFC": "Haverfordwest", "Holywell Town": "Holywell",
    "Llandudno FC": "Llandudno", "Pen-y-Bont FC": "Penybont",
    "The New Saints FC": "TNS", "Trefelin BGC": "Trefelin",
    # Wales Cymru North
    "Bala Town FC": "Bala", "Brickfield Rangers": "Brickfield",
    "Buckley Town": "Buckley", "CPD Dinas Bangor City 1876 FC": "Bangor 1876",
    "CPD Y Rhyl 1879": "Rhyl", "Caersws": "Caersws FC",
    "Denbigh Town": "Denbigh", "Gresford Athletic": "Gresford",
    "Guilsfield FC": "Guilsfield", "Holyhead Hotspur": "Holyhead",
    "Mold Alexandra FC": "Mold Alexandra", "Newtown AFC": "Newtown",
    # Wales Cymru South
    "Aberystwyth Town FC": "Aberystwyth", "Caerau Ely FC": "Caerau Ely",
    "Caerphilly Athletic FC": "Caerphilly", "Llanelli Town": "Llanelli",
    "Newport City FC": "Newport City", "Pontardawe Town FC": "Pontardawe",
    "Pontypridd Town": "Pontypridd", "Treowen Stars": "Treowen",

    # Japan J1
    "Fagiano Okayama": "Okayama", "Kyoto Sanga FC": "Kyoto",
    "Machida Zelvia": "Machida", "Tokyo Verdy": "Verdy",
    "Urawa Red Diamonds": "Urawa Reds", "Yokohama F Marinos": "Yokohama F. Marinos",

    # UAE Pro League + Division 1
    "Ajman Club": "Ajman", "Al Ain FC": "Al Ain", "Al Dhafra SSC": "Al Dhafra",
    "Al Jazira (UAE)": "Al Jazira", "Al Wahda FC (UAE)": "Al Wahda",
    "Al Wasl FC": "Al Wasl", "Al-Nasr Dubai CSC": "Al Nasr",
    "Baniyas Club": "Bani Yas", "Hatta SC": "Hatta",
    "Ittihad Kalba FC": "Ittihad Kalba", "Khor Fakkan Club": "Khorfakkan",
    "AL Arabi (UAE)": "Al Arabi", "AL Bataeh (UAE)": "Al Bataeh",
    "AL Ittifaq": "Al-Ittifaq", "AL Jazira AL Hamra": "Al Jazira Hamra",
    "Al Urooba (UAE)": "Al Urooba", "Al-Dhaid": "Al Thaid",
    "Al-Hamriyah": "Al Hamriyah", "Dibba Al-Hisn SC": "Dibba Al Hisn",
    "Dubai City FC": "Dubai City", "Forte Virtus FC": "Forte Virtus",
    "Fujairah FC": "Al Fujairah",

    # Skottland Premiership
    "Aberdeen FC": "Aberdeen", "Celtic Glasgow": "Celtic",
    "Dundee United": "Dundee Utd", "Falkirk FC": "Falkirk",
    "Glasgow Rangers": "Rangers", "Heart of Midlothian FC": "Hearts",
    "Hibernian FC": "Hibernian", "Kilmarnock FC": "Kilmarnock",
    "Motherwell FC": "Motherwell", "St Mirren FC": "St. Mirren",
    "St. Johnstone FC": "St Johnstone",
    # Skottland Championship
    "Arbroath FC": "Arbroath", "Ayr United FC": "Ayr",
    "Dunfermline Athletic FC": "Dunfermline", "Greenock Morton FC": "Morton",
    "Inverness Caledonian Thistle FC": "Inverness", "Livingston FC": "Livingston",
    "Partick Thistle FC": "Partick Thistle", "Queens Park FC": "Queen's Park",
    "Raith Rovers FC": "Raith", "Stenhousemuir FC": "Stenhousemuir",
    # Skottland League One
    "Airdrieonians FC": "Airdrieonians", "Alloa Athletic FC": "Alloa",
    "Cove Rangers FC": "Cove Rangers", "East Fife FC": "East Fife",
    "East Kilbride FC": "East Kilbride", "Hamilton Academical FC": "Hamilton",
    "Montrose FC": "Montrose", "Peterhead FC": "Peterhead",
    "Queen of the South FC": "Queen of South", "Ross County FC": "Ross County",
    # Skottland League Two
    "Annan Athletic FC": "Annan", "Clyde FC": "Clyde",
    "Dumbarton FC": "Dumbarton", "Edinburgh City FC": "Edinburgh City",
    "Elgin City FC": "Elgin City", "Forfar Athletic FC": "Forfar Athletic",
    "Kelty Hearts FC": "Kelty Hearts", "Spartans FC": "Spartans",
    "Stirling Albion FC": "Stirling", "Stranraer FC": "Stranraer",
    # Skottland Highland League
    "Banks O'Dee FC": "Banks O' Dee", "Brora Rangers FC": "Brora Rangers",
    "Buckie Thistle FC": "Buckie Thistle", "Clachnacuddin FC": "Clachnacuddin",
    "Deveronvale FC": "Deveronvale", "Formartine United FC": "Formartine Utd",
    "Forres Mechanics FC": "Forres Mechanics", "Fraserburgh FC": "Fraserburgh",
    "Huntly FC": "Huntly", "Invergordon FC": "Invergordon",
    "Inverurie Loco Works FC": "Inverurie", "Keith FC": "Keith",

    # Slovakien Nike liga
    "AS Trencin": "Trencin", "DAC 1904 Dunajska Streda": "Dun. Streda",
    "FC Spartak Trnava": "Trnava", "FK Kosice": "Kosice",
    "FK Zeleziarne Podbrezova": "Podbrezova", "KFC Komarno": "Komarno",
    "MFK Ruzomberok": "Ruzomberok", "MFK Skalica": "Skalica",
    "MFK Zemplin Michalovce": "Michalovce", "MFk Dukla Banska Bystrica": "Banska Bystrica",
    "MSK Zilina": "Zilina", "SK Slovan Bratislava": "Slovan Bratislava",
    # Slovakien 2. Liga
    "1. FC Tatran Presov": "Presov", "FC Petrzalka": "Petrzalka",
    "FC STK 1914 Samorin": "Samorin", "FC Slovan Galanta": "Galanta",
    "FC Vion Zlate Moravce - Vrable": "Z. Moravce-Vrable", "FK Inter Bratislava": "I. Bratislava",
    "FK Pohronie Ziar Nad Hronom Dolna Zdana": "Pohronie",
    "MFK Tatran Liptovsky Mikulas": "L. Mikulas", "MFK Zvolen": "Zvolen",
    "MFk Bytca": "MFK Bytca", "MSK Povazska Bystrica": "Povazska Bystrica",
    "MSK Zilina B": "Zilina B",
    # Slovakien 3. Liga Central
    "MFK Dukla Banska Bystrica B": "B. Bystrica B", "MSK Kysucke Nove Mesto": "K. Nove Mesto",
    # Slovakien 3. Liga East
    "MFK Stara Lubovna": "Lubovna", "Ofk-Sim Raslavice": "Raslavice",
    "SK Odeva Lipany": "Lipany",
    # Slovakien 3. Liga West
    "AS Trencin B": "Trencin B", "Druzstevnik Velke Ludince": "Velke Ludince",
    "FC Banik Prievidza": "Banik Prievidza", "FC Nitra": "Nitra",
    "FK Belusa": "Belusa", "FK Dac 1904 Dunajska Streda B": "Dun. Streda B",
    "FK Slovan Duslo Sala": "Sala", "KFC Komarno B": "Komarno B",

    # Slovenien Prva liga
    "Aluminij Kidricevo": "Aluminij", "Bravo Ljubljana": "Bravo",
    "FC Koper": "Koper", "Mura Murska Sobota": "Mura",
    "NK Brinje Grosuplje": "Grosuplje", "NK Celje": "Celje",
    "NK Maribor": "Maribor", "NK Radomlje": "Radomlje",
    "Nafta 1903 Lendava": "Nafta", "Olimpija Ljubljana": "O. Ljubljana",
    # Slovenien 2. SNL
    "Ilirija Ljubljana": "Ilirija", "Krka Novo Mesto": "NK Krka",
    "ND Beltinci": "Beltinci", "NK Bilje": "Bilje",
    "NK Bistrica Slovenska Bistrica": "Bistrc", "NK Brezice 1919": "Brezice",
    "NK Dekani": "Jadran Dekani", "NK Krsko Posavje": "Krsko Posavje",
    "NK Rudar Velenje": "Rudar", "NK Vrhnika": "Vrhnika",
    "Nd Dravinja": "Dravinja", "Nd Slovan": "Slovan Ljubljana",
    # Slovenien 3. SNL East/West (delade lagnamn i gransomradet)
    "Fuzinar Ravne": "Fuzinar", "Mnk Izola": "Izola",
    "ND Adria": "NK Adria", "NK Carda": "NK Carda Martjanci",
    "NK Dob": "Dob", "NK Hajdina": "Hajdina",
    "NK IB Ljubljana": "IB 1975 Ljubljana", "NK Korotan": "Korotan",
    "NK Limbus Pekre": "Limbus-Pekre", "NK Litija": "Litija",
    "NK Ljutomer": "Ljutomer",

    # Andra omgangen rattelser - Polen
    "Slask II Wroclaw": "Slask Wroclaw II",
    "Podbeskidzie Bielsko-Biała": "Podbeskidzie",
    "Wigry Suwalki": "Suwalki", "Wisla Plock II": "Plock II",
    "ZKS Olimpia Elblag": "Olimpia Elblag", "Zabkovia Zabki": "Zabki",
    "Odra Bytom Odrzanski": "Bytom Odrzanski", "Rakow II Czestochowa": "Rakow II",
    "SKRA Czestochowa": "Skra", "Slowianin Woliborz": "Woliborz",
    "Warta Gorzow Wielkopolski": "Warta Gorzow", "Zaglebie Lubin II": "Zaglebie II",
    # Andra omgangen - Tyskland
    "SV Meppen 1912": "Meppen", "SV Waldhof Mannheim 07": "Mannheim",
    "SV Wehen Wiesbaden": "Wehen", "TSG Hoffenheim II": "Hoffenheim II",
    "VfB Stuttgart II": "Stuttgart II",
    "SV Drochtersen/Assel": "Drochtersen/Assel", "SV Todesfelde": "Todesfelde",
    "SV Werder Bremen II": "Werder Bremen II",
    "SV Rodinghausen": "Rodinghausen", "SV Westfalia Rhynern": "Westfalia Rhynern",
    "Sportfreunde Siegen 1899": "Siegen", "VfB 03 Hilden": "Hilden",
    "VfL Bochum II": "Bochum II", "VfL Sportfreunde Lotte 1929": "Lotte",
    "Stuttgarter Kickers": "Stutt. Kickers", "TSV Steinbach Haiger": "Steinbach Haiger",
    "VfR Aalen": "Aalen",
    "Hertha BSC II": "Hertha Berlin II", "RSV Eintracht Stahnsdorf 1949": "RSV Eintracht",
    "SV Babelsberg": "Babelsberg", "SV Tasmania Berlin": "Tasmania Berlin",
    "VSG Altglienicke": "Altglienicke",
    "TSV 1860 Munich": "Munich 1860", "TSV Aubstadt": "Aubstadt",
    "TSV Buchbach": "Buchbach", "TSV Landsberg am Lech": "Landsberg",
    "VfB Eichstatt": "Eichstatt", "Wacker Burghausen": "Burghausen",
    # Andra omgangen - Wales
    "Porthmadog FC": "Porthmadog", "Ruthin Town": "Ruthin",
    # Andra omgangen - UAE
    "Dubai United FC": "United FC", "Shabab Al Ahli Dubai": "Shabab Al-Ahli Dubai",
    "Sharjah FC": "Al Sharjah",
    # Andra omgangen - Skottland Highland
    "Lossiemouth FC": "Lossiemouth", "Nairn County FC": "Nairn County",
    "Rothes FC": "Rothes", "Strathspey Thistle FC": "Strathspey Thistle",
    "Turriff United FC": "Turriff Utd", "Wick Academy FC": "Wick Academy",
    # Andra omgangen - Slovakien
    "OFK Banik Lehota Pod Vtacnikom": "Lehota p. V.", "OFK Dynamo Malzenice": "Malzenice",
    "FK Cadca": "Cadca", "FK Podkonice": "Podkonice", "FK Poprad": "Poprad",
    "FTC Filakovo": "Filakovo", "MFK Dolny Kubin": "D. Kubin",
    "MFK Kezmarok": "Kezmarok", "MFK Snina": "Snina",
    "MFK Spartak Medzev": "Medzev", "MFK Vranov Nad Topou": "Vranov",
    # Andra omgangen - Slovenien
    "Primorje Ajdovscina": "Primorje", "Triglav Kranj": "Triglav",
    "NK Odranci": "Odranci", "NK Podvinci": "Podvinci", "NK Race": "Race",
    "NK Sampion Celje": "Sampion Celje", "NK Sencur": "Sencur",
    "NK Skofja Loka": "Skofja Loka", "NK Idrija": "Zidgrad Idrija",

    # Japan J2 (gissningar enligt samma monster som redan bekraftats for J1 -
    # verifiera mot nasta kornings loggutskrift)
    "JEF United Chiba": "Chiba", "Mito Hollyhock": "Mito",
    "Ehime FC": "Ehime", "Roasso Kumamoto": "Kumamoto",
    "Blaublitz Akita": "Blaublitz", "Iwaki FC": "Iwaki",
    "Vanraure Hashima": "Vanraure",
}


def resolve_team(name, known_teams):
    if name in known_teams:
        return name
    if name in NAME_ALIASES and NAME_ALIASES[name] in known_teams:
        return NAME_ALIASES[name]
    return None


def api_get(path, params, max_retries=5):
    key = os.environ.get("ODDS_API_KEY") or load_env().get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Satt miljovariabeln ODDS_API_KEY forst (eller lagg den i .env i projektroten)")
    params = dict(params)
    params["apiKey"] = key
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                # Rate-limitad (for manga anrop for snabbt) - backa av och forsok igen.
                # Kolla om API:t sjalvt sager hur lange vi ska vanta (Retry-After-headern),
                # annars vanta stigande langre for varje forsok (5s, 10s, 20s, 40s, ...).
                wait_s = int(e.headers.get("Retry-After", 5 * (2 ** attempt)))
                print(f"  (429 Too Many Requests - vantar {wait_s}s och forsoker igen, {attempt + 1}/{max_retries})", file=sys.stderr)
                time.sleep(wait_s)
                continue
            raise


def get_upcoming_events(league_slug):
    return api_get("/events", {"sport": "football", "league": league_slug})


MAX_ROUNDS_AHEAD = 2  # hur manga "omgangar" (kalenderveckor med minst en match) framat vi skannar


def event_date(ev):
    try:
        return datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def limit_to_next_rounds(events, max_rounds=MAX_ROUNDS_AHEAD):
    """Begransar till de narmaste max_rounds 'omgangarna' istallet for att skanna
    hela sasongen framat - en omgang rammas in som en kalendervecka (man-son)
    med minst en match, sa en helg (fre-son) raknas som EN omgang, inte tre.
    Events utan tolkbart datum behalls (hellre skanna for mycket an missa nagot)."""
    dated = [(event_date(ev), ev) for ev in events]
    undated = [ev for d, ev in dated if d is None]
    dated = sorted([(d, ev) for d, ev in dated if d is not None], key=lambda x: x[0])

    weeks_seen = []
    result = []
    for d, ev in dated:
        wk = (d.isocalendar()[0], d.isocalendar()[1])
        if wk not in weeks_seen:
            if len(weeks_seen) >= max_rounds:
                break
            weeks_seen.append(wk)
        result.append(ev)
    return result + undated


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

    n_total = len(events)
    events = limit_to_next_rounds(events)
    print(f"  -> {n_total} kommande matcher hittade hos odds-api.io for {league_key}, "
          f"skannar de narmaste {MAX_ROUNDS_AHEAD} omgangarna ({len(events)} matcher)", file=sys.stderr)

    n_resolved = 0
    n_with_odds = 0
    unmatched = set()
    hits = []
    for ev in events:
        home = resolve_team(ev["home"], known_teams)
        away = resolve_team(ev["away"], known_teams)
        if not home:
            unmatched.add(ev["home"])
        if not away:
            unmatched.add(ev["away"])
        if not home or not away:
            continue  # laget hor inte till den har ligan (fel slug-tagg) eller saknar historik
        n_resolved += 1

        odds_data = get_event_odds(ev["id"])
        bet365 = odds_data.get("bookmakers", {}).get("Bet365")
        if not bet365:
            print(f"     (ingen Bet365-data alls an: {ev['home']} - {ev['away']})", file=sys.stderr)
            continue

        ml = next((m for m in bet365 if m["name"] == "ML"), None)
        totals = next((m for m in bet365 if m["name"] == "Totals"), None)
        if not ml or not totals:
            saknas = []
            if not ml:
                saknas.append("ML (1X2)")
            if not totals:
                saknas.append("Totals (Goal Line)")
            print(f"     (Bet365 har data, men saknar {' och '.join(saknas)} an: {ev['home']} - {ev['away']} — marknader som FINNS: {[m['name'] for m in bet365]})", file=sys.stderr)
            continue
        n_with_odds += 1

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
                "event_id": ev["id"],
                "match": f"{ev['home']} - {ev['away']}",
                "market": "Goal Line",
                "side": hit["sida"],
                "line": hit["line"],
                "model_prob": hit["modell_sannolikhet"],
                "bet365_odds": hit["bet365_odds"],
                "edge_pp": hit["edge_procentenheter"],
            })

        time.sleep(0.3)  # var snall mot API:t (kvot: 5000 req/h)

    print(f"  -> {n_resolved} av dem matchade lag i var historik, {n_with_odds} hade Bet365-odds, {len(hits)} value-traffar", file=sys.stderr)
    if unmatched:
        print(f"     Omatchade lagnamn fran odds-api.io: {', '.join(sorted(unmatched))}", file=sys.stderr)
    return hits


# Lokal fil som kommer ihag vilka value-bets som redan skickats till Telegram,
# sa vi inte skickar samma fynd flera ganger pa rad nar vi kor skannern om och
# om igen (t.ex. varje timme). Ligger i projektroten, delas INTE via git
# (lagg garna till den i .gitignore om den inte redan ar det).
SENT_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "sent_bets.json")
SENT_LOG_MAX_AGE_DAYS = 14  # efter sa har manga dagar antar vi att matchen spelats klart


def hit_key(h):
    """Unik nyckel per (match, marknad, sida, linje) - anvands for att avgora
    om ett fynd redan skickats tidigare."""
    return f"{h.get('event_id', '?')}|{h['market']}|{h['side']}|{h.get('line')}"


def load_sent_log():
    if not os.path.exists(SENT_LOG_PATH):
        return {}
    try:
        with open(SENT_LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_sent_log(log):
    with open(SENT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def prune_sent_log(log):
    """Tar bort gamla rader (aldre an SENT_LOG_MAX_AGE_DAYS) sa filen inte vaxer
    for alltid, och sa samma match nasta sasong kan trigga en ny alert igen."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SENT_LOG_MAX_AGE_DAYS)
    stale = []
    for key, entry in log.items():
        try:
            sent_at = datetime.fromisoformat(entry["sent_at"])
        except (KeyError, ValueError):
            stale.append(key)
            continue
        if sent_at < cutoff:
            stale.append(key)
    for key in stale:
        del log[key]


def main():
    args = sys.argv[1:]
    send = "--send" in args
    league_keys = [a for a in args if a != "--send"]

    if not league_keys:
        print(__doc__)
        sys.exit(1)

    if league_keys == ["all"]:
        league_keys = list(LEAGUES.keys())
        print(f"Skannar ALLA {len(league_keys)} ligor...", file=sys.stderr)

    all_hits = []
    for key in league_keys:
        if key not in LEAGUES:
            print(f"Okand liga-nyckel: {key} (se LEAGUES i tot_model.py)", file=sys.stderr)
            continue
        print(f"Skannar {key} ...", file=sys.stderr)
        all_hits += scan_league(key)
        time.sleep(0.3)  # var snall mot API:t mellan ligor ocksa, inte bara mellan matcher

    report = format_report(all_hits)
    print(report)

    if send:
        sent_log = load_sent_log()
        new_hits = [h for h in all_hits if hit_key(h) not in sent_log]
        already_sent = len(all_hits) - len(new_hits)
        if already_sent:
            print(f"({already_sent} av {len(all_hits)} fynd var redan skickade tidigare - hoppar over dem)", file=sys.stderr)

        if not new_hits:
            print("Inga NYA value-fynd att skicka.", file=sys.stderr)
        else:
            chunks = format_report_chunks(new_hits)
            for i, chunk in enumerate(chunks, 1):
                send_message(chunk)
                if len(chunks) > 1:
                    print(f"Skickat till Telegram ({i}/{len(chunks)}).", file=sys.stderr)
                else:
                    print("Skickat till Telegram.", file=sys.stderr)

            now = datetime.now(timezone.utc).isoformat()
            for h in new_hits:
                sent_log[hit_key(h)] = {
                    "sent_at": now, "league": h["league"], "match": h["match"],
                    "side": h["side"], "line": h.get("line"),
                }
            prune_sent_log(sent_log)
            save_sent_log(sent_log)


if __name__ == "__main__":
    main()
