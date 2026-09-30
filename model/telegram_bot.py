"""
Telegram-bot: skickar value-bet-fynd till din Telegram-chatt.

Miljövariabler som kravs (las in fran .env i projektroten):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

OBS: Telegrams API (api.telegram.org) ar blockerat via Bash/curl i Claudes
sandlada (samma natverksfilter som blockerar odds-api.io). For att skicka
meddelanden fran en interaktiv Claude-session, anvand Claude in Chrome for
att navigera till sendMessage-URL:en (samma teknik som anvands for att
hamta odds). For att skicka fran ett fristaende skript (lokalt/pa server
med riktig natverksatkomst) fungerar detta skript direkt via urllib.
"""

import os
import json
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path


def load_env(env_path=None):
    """Enkel .env-laddare (ingen extra dependency behovs)."""
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"
    env = {}
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def send_message(text, bot_token=None, chat_id=None, parse_mode="Markdown"):
    """Skickar ett textmeddelande via Telegram Bot API. Returnerar API-svaret (dict)."""
    env = load_env()
    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN saknas (satt i .env eller miljovariabel)")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID saknas (kor get_chat_id() forst)")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # Telegram skickar alltid en JSON-body med en forklaring aven vid fel
        # (t.ex. "message is too long" eller "can't parse entities") - visa
        # den istallet for bara "HTTP Error 400: Bad Request".
        try:
            body = json.loads(e.read().decode())
            raise RuntimeError(f"Telegram avvisade meddelandet: {body.get('description', body)}") from e
        except (ValueError, json.JSONDecodeError):
            raise


def get_updates(bot_token=None):
    """Hamtar senaste updates (anvands for att hitta chat_id efter att man skickat
    ett meddelande till boten). Returnerar hela API-svaret (dict)."""
    env = load_env()
    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN saknas")
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())


def format_value_bet(league, match, market, side, line, model_prob, bet365_odds, edge_pp):
    """Formaterar en enskild value-bet-rad for Telegram (Markdown)."""
    line_str = f" {line}" if line is not None else ""
    fair_odds = 100 / model_prob
    p = model_prob / 100
    ev_pct = (p * bet365_odds - 1) * 100  # forvantad avkastning i % av insatsen
    return (
        f"*{league}*\n"
        f"{match}\n"
        f"{market}{line_str} — *{side}*\n"
        f"Fair odds: {fair_odds:.3f}  |  Bet365: {bet365_odds}\n"
        f"Edge: {edge_pp:+.1f}pp  |  EV: {ev_pct:+.1f}%\n"
    )


def format_report(hits):
    """
    hits: lista av dict med nycklarna
        league, match, market, side, line (kan vara None), model_prob (0-100),
        bet365_odds (float), edge_pp (procentenheter)
    Returnerar ett komplett Telegram-meddelande (Markdown).
    """
    if not hits:
        return "Inga value-fynd just nu."
    parts = [f"*Value-bets hittade: {len(hits)}*\n"]
    for h in sorted(hits, key=lambda x: -x["edge_pp"]):
        parts.append(format_value_bet(
            h["league"], h["match"], h["market"], h["side"],
            h.get("line"), h["model_prob"], h["bet365_odds"], h["edge_pp"],
        ))
    return "\n".join(parts)


def format_report_chunks(hits, max_len=3500):
    """
    Som format_report(), men delar upp i flera meddelanden om det blir for
    langt for Telegram (som svarar 400 Bad Request over ca 4096 tecken per
    meddelande). max_len har en marginal under den gransen. Returnerar en
    lista av en eller flera meddelandetexter.
    """
    if not hits:
        return ["Inga value-fynd just nu."]

    header = f"*Value-bets hittade: {len(hits)}*\n"
    blocks = [format_value_bet(
        h["league"], h["match"], h["market"], h["side"],
        h.get("line"), h["model_prob"], h["bet365_odds"], h["edge_pp"],
    ) for h in sorted(hits, key=lambda x: -x["edge_pp"])]

    chunks = []
    current = header
    for block in blocks:
        if len(current) + len(block) + 1 > max_len and current != header:
            chunks.append(current.rstrip("\n"))
            current = ""
        current += block + "\n"
    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "get_chat_id":
        result = get_updates()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # exempel
        example_hits = [
            {"league": "Poland II Liga", "match": "Hutnik Krakow - GKS Tychy",
             "market": "Totals", "side": "Under", "line": 2.5,
             "model_prob": 66.2, "bet365_odds": 1.975, "edge_pp": 15.5},
        ]
        print(format_report(example_hits))
