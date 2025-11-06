import os
import requests
import math
import random
from datetime import date
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Carica variabili d'ambiente
load_dotenv()
API_KEY = os.getenv("API_FOOTBALL_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}


# Funzioni matematiche
def poisson_probability(lmbda, k):
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k)


def expected_goals(avg_home, avg_away):
    return (avg_home + avg_away) / 2


def media_pesata(lista):
    pesi = [5, 4, 3, 2, 1]
    return sum([a * p for a, p in zip(lista[-5:], pesi[:len(lista)])]) / sum(pesi[:len(lista)])


# Calcola forma recente
def get_team_form(team_id, league_id, season):
    url = f"{BASE_URL}/fixtures?team={team_id}&league={league_id}&season={season}&last=5"
    res = requests.get(url, headers=HEADERS)
    matches = res.json().get("response", [])
    if not matches:
        return 1.0, 1.0  # fallback neutro

    goals_for = []
    goals_against = []
    for m in matches:
        home = m["teams"]["home"]["id"]
        g_home = m["goals"]["home"]
        g_away = m["goals"]["away"]
        if g_home is None or g_away is None:
            continue  # salta partite incomplete

        if home == team_id:
            goals_for.append(g_home)
            goals_against.append(g_away)
        else:
            goals_for.append(g_away)
            goals_against.append(g_home)

    if not goals_for or not goals_against:
        return 1.0, 1.0  # fallback in caso di dati mancanti

    return media_pesata(goals_for), media_pesata(goals_against)



# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    fixtures_url = f"{BASE_URL}/fixtures?date={today}"
    fixtures_res = requests.get(fixtures_url, headers=HEADERS)
    fixtures = fixtures_res.json().get("response", [])

    # Filtra solo partite non ancora iniziate
    fixtures = [f for f in fixtures if f.get("fixture", {}).get("status", {}).get("short") == "NS"]

    if not fixtures:
        await update.message.reply_text("⚠️ Nessuna partita in programma (non ancora iniziata).")
        return

    message = "📊 *Analisi avanzata partite di oggi*\n\n"

    for f in fixtures[:10]:
        fixture_id = f.get("fixture", {}).get("id")
        home_team = f.get("teams", {}).get("home", {}).get("name")
        away_team = f.get("teams", {}).get("away", {}).get("name")
        league_id = f["league"]["id"]
        season = f["league"]["season"]
        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]

        # Quote
        odds_url = f"{BASE_URL}/odds?fixture={fixture_id}"
        odds_res = requests.get(odds_url, headers=HEADERS)
        odds_data = odds_res.json().get("response", [])

        odds_1x2 = {"1": None, "X": None, "2": None}
        odds_ggng = {"GG": None, "NG": None}
        odds_ou = {"Over 2.5": None, "Under 2.5": None}

        if odds_data:
            for b in odds_data:
                for bookmaker in b.get("bookmakers", []):
                    for bet in bookmaker.get("bets", []):
                        if bet.get("name") == "Match Winner":
                            for val in bet.get("values", []):
                                odds_1x2[val["value"]] = float(val["odd"])
                        if bet.get("name") == "Both Teams Score":
                            for val in bet.get("values", []):
                                odds_ggng[val["value"]] = float(val["odd"])
                        if bet.get("name") == "Over/Under":
                            for val in bet.get("values", []):
                                if val["value"] in ["Over 2.5", "Under 2.5"]:
                                    odds_ou[val["value"]] = float(val["odd"])

        def implied_probability(odd):
            return 1 / odd if odd else 0

        probs_1x2 = {k: implied_probability(v) for k, v in odds_1x2.items()}
        s1 = sum(probs_1x2.values()) or 1
        probs_1x2 = {k: v / s1 for k, v in probs_1x2.items()}

        probs_ggng = {k: implied_probability(v) for k, v in odds_ggng.items()}
        s2 = sum(probs_ggng.values()) or 1
        probs_ggng = {k: v / s2 for k, v in probs_ggng.items()}

        probs_ou = {k: implied_probability(v) for k, v in odds_ou.items()}
        s3 = sum(probs_ou.values()) or 1
        probs_ou = {k: v / s3 for k, v in probs_ou.items()}

        # Statistiche e forma
        home_for, home_against = get_team_form(home_id, league_id, season)
        away_for, away_against = get_team_form(away_id, league_id, season)

        # Fattore casa/trasferta
        home_for *= 1.15
        away_for *= 0.9

        exp_home = expected_goals(home_for, away_against)
        exp_away = expected_goals(away_for, home_against)

        # Poisson
        p_home = poisson_probability(exp_home, 2)
        p_draw = poisson_probability(exp_home, 1) * poisson_probability(exp_away, 1)
        p_away = poisson_probability(exp_away, 2)
        s4 = p_home + p_draw + p_away
        probs_poisson = {"1": p_home/s4, "X": p_draw/s4, "2": p_away/s4}

        # Combinazione finale
        final_probs = {
            k: 0.5 * probs_1x2.get(k, 0) + 0.3 * probs_poisson.get(k, 0) + 0.2 * random.random()
            for k in ["1", "X", "2"]
        }

        result_1x2 = max(final_probs, key=final_probs.get)
        result_ggng = max(probs_ggng, key=probs_ggng.get)
        result_ou = max(probs_ou, key=probs_ou.get)

        # Valutazione forma
        forma = (home_for + away_for) / 2
        if forma > 2:
            forma_txt = "📈 Ottima"
        elif forma > 1.2:
            forma_txt = "🙂 Buona"
        else:
            forma_txt = "😐 Normale"

        message += (
            f"⚽ {home_team} vs {away_team}\n"
            f"{forma_txt}\n"
            f"👉 1X2: {result_1x2} | GG/NG: {result_ggng} | O/U 2.5: {result_ou}\n\n"
        )

    await update.message.reply_text(message, parse_mode="Markdown")


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("🤖 Bot avanzato Quote + Forma + Poisson avviato...")
    app.run_polling()
