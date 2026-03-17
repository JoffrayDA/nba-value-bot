"""
value_bot.py
------------
Cerveau du bot : compare les prédictions NBA avec les cotes bookmakers,
détecte les value bets, et envoie des alertes Telegram.

Usage :
  python value_bot.py             → scan complet
  python value_bot.py --dry-run   → affiche les value bets sans envoyer
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime
from dataclasses import dataclass, asdict

from nba_fetcher import get_league_advanced_stats, predict_match_total
from odds_fetcher import get_nba_odds_parsed, odd_to_prob


# ── Config ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",  "REMPLACE_PAR_TON_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","REMPLACE_PAR_TON_CHAT_ID")

# Seuils de détection
MIN_VALUE        = 0.04   # valeur minimum pour alerter (4%)
MIN_BOOKMAKERS   = 1      # ignorer les matchs couverts par peu de bookies
KELLY_FRACTION   = 0.25   # Kelly fractionné (25% du Kelly pur = plus prudent)
BANKROLL         = 1000   # Bankroll fictive en € pour calculer la mise Kelly

# Mapping noms d'équipes The Odds API → nba_api (quand ils diffèrent)
TEAM_NAME_MAP = {
    "LA Clippers":         "Los Angeles Clippers",
    "LA Lakers":           "Los Angeles Lakers",
    "GS Warriors":         "Golden State Warriors",
    "NY Knicks":           "New York Knicks",
    "NJ Nets":             "Brooklyn Nets",
    "NO Pelicans":         "New Orleans Pelicans",
    "SA Spurs":            "San Antonio Spurs",
    "OKC Thunder":         "Oklahoma City Thunder",
}

def normalize_team(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)


# ── Dataclass ValueBet ────────────────────────────────────────────────────────

@dataclass
class ValueBet:
    home_team:       str
    away_team:       str
    date:            str
    market:          str          # "Over 224.5" ou "Under 224.5"
    bookmaker:       str
    bookie_odd:      float        # cote proposée par le bookmaker
    bookie_prob:     float        # probabilité implicite du bookie
    model_prob:      float        # notre estimation de probabilité
    value:           float        # value = (model_prob * odd) - 1
    kelly_stake:     float        # mise conseillée (Kelly fractionné)
    predicted_total: float        # total prédit par notre modèle
    total_line:      float        # ligne de total du bookmaker


# ── Calcul de probabilité modèle ─────────────────────────────────────────────

def model_probability_over(predicted_total: float, line: float,
                            std_dev: float = 12.0) -> float:
    """
    Estime la probabilité que le match dépasse la ligne (Over).

    On modélise les totaux NBA comme une distribution normale :
    - Moyenne = notre total prédit
    - Écart-type = ~12 pts (variance historique typique des totaux NBA)

    Note : avec plus de données, on peut calibrer std_dev par équipe/match.
    """
    from scipy.stats import norm
    prob_over = 1 - norm.cdf(line, loc=predicted_total, scale=std_dev)
    return round(float(prob_over), 4)


def fractional_kelly(prob: float, odd: float, fraction: float = KELLY_FRACTION) -> float:
    """
    Calcule la mise optimale selon le critère de Kelly fractionné.
    Kelly pur = (p*b - q) / b  où b = odd - 1
    """
    b = odd - 1
    q = 1 - prob
    kelly = (prob * b - q) / b
    return max(0.0, round(kelly * fraction, 4))


# ── Détection de value ────────────────────────────────────────────────────────

def detect_value_bets(totals: list[dict], league_df) -> list[ValueBet]:
    """
    Pour chaque match avec cotes, prédit le total NBA et cherche des value bets.
    """
    value_bets = []
    n = len(totals)

    for i, match in enumerate(totals, 1):
        home = normalize_team(match["home_team"])
        away = normalize_team(match["away_team"])

        print(f"\n[{i}/{n}] Analyse : {away} @ {home}")

        # Ignorer les matchs avec peu de bookmakers (faible liquidité)
        if match["n_bookmakers"] < MIN_BOOKMAKERS:
            print(f"  ⏭  Ignoré ({match['n_bookmakers']} bookmakers seulement)")
            continue

        # Prédire le total via notre modèle NBA
        try:
            prediction = predict_match_total(home, away, league_df)
            pred_total = prediction.get("predicted_total")
        except Exception as e:
            print(f"  ❌ Erreur prédiction : {e}")
            continue

        if pred_total is None:
            print(f"  ❌ Pas de prédiction disponible")
            continue

        line = match["total_line"]
        print(f"  Total prédit : {pred_total} pts | Ligne bookie : {line} pts")

        # Probabilité Over selon notre modèle
        prob_over  = model_probability_over(pred_total, line)
        prob_under = round(1 - prob_over, 4)

        print(f"  P(Over)={prob_over:.1%}  P(Under)={prob_under:.1%}")

        # Analyser Over
        best_over = match["best_over"]
        bookie_prob_over = odd_to_prob(best_over["price"])
        value_over = round((prob_over * best_over["price"]) - 1, 4)

        if value_over >= MIN_VALUE:
            kelly = fractional_kelly(prob_over, best_over["price"])
            stake = round(BANKROLL * kelly, 2)
            print(f"  ✅ VALUE BET OVER  : value={value_over:.1%} | cote={best_over['price']} @ {best_over['bookmaker']} | mise conseillée : {stake}€")
            value_bets.append(ValueBet(
                home_team=home, away_team=away, date=match["date"],
                market=f"Over {line}", bookmaker=best_over["bookmaker"],
                bookie_odd=best_over["price"], bookie_prob=bookie_prob_over,
                model_prob=prob_over, value=value_over, kelly_stake=stake,
                predicted_total=pred_total, total_line=line,
            ))

        # Analyser Under
        best_under = match["best_under"]
        bookie_prob_under = odd_to_prob(best_under["price"])
        value_under = round((prob_under * best_under["price"]) - 1, 4)

        if value_under >= MIN_VALUE:
            kelly = fractional_kelly(prob_under, best_under["price"])
            stake = round(BANKROLL * kelly, 2)
            print(f"  ✅ VALUE BET UNDER : value={value_under:.1%} | cote={best_under['price']} @ {best_under['bookmaker']} | mise conseillée : {stake}€")
            value_bets.append(ValueBet(
                home_team=home, away_team=away, date=match["date"],
                market=f"Under {line}", bookmaker=best_under["bookmaker"],
                bookie_odd=best_under["price"], bookie_prob=bookie_prob_under,
                model_prob=prob_under, value=value_under, kelly_stake=stake,
                predicted_total=pred_total, total_line=line,
            ))

        # Petit délai pour ne pas spammer l'API NBA
        time.sleep(0.3)

    return value_bets


# ── Alertes Telegram ──────────────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """Envoie un message Telegram."""
    if TELEGRAM_TOKEN == "REMPLACE_PAR_TON_TOKEN":
        print("[TELEGRAM] Token non configuré, message non envoyé.")
        print(f"[TELEGRAM] Message :\n{message}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }
    resp = requests.post(url, json=payload, timeout=10)
    return resp.status_code == 200


def format_value_bet_message(vb: ValueBet) -> str:
    """Formate une value bet en message Telegram lisible."""
    value_pct   = f"{vb.value * 100:.1f}%"
    edge_emoji  = "🔥" if vb.value >= 0.08 else "✅"

    return (
        f"{edge_emoji} <b>VALUE BET NBA — {vb.market.upper()}</b>\n"
        f"\n"
        f"🏀 <b>{vb.away_team} @ {vb.home_team}</b>\n"
        f"📅 {vb.date}\n"
        f"\n"
        f"📊 <b>Analyse :</b>\n"
        f"  Total prédit   : <b>{vb.predicted_total} pts</b>\n"
        f"  Ligne bookmaker: {vb.total_line} pts\n"
        f"  Notre P(gagner): {vb.model_prob:.1%}\n"
        f"  Prob. implicite: {vb.bookie_prob:.1%}\n"
        f"\n"
        f"💰 <b>Value : {value_pct}</b>\n"
        f"  Cote : {vb.bookie_odd} @ {vb.bookmaker}\n"
        f"  Mise Kelly ({int(KELLY_FRACTION*100)}%) : <b>{vb.kelly_stake}€</b>\n"
        f"  (sur bankroll de {BANKROLL}€)"
    )


def send_summary(value_bets: list[ValueBet], dry_run: bool = False) -> None:
    """Envoie un résumé + chaque value bet en Telegram."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    if not value_bets:
        msg = (
            f"🏀 <b>NBA Value Bot — {now}</b>\n\n"
            f"Aucune value bet détectée aujourd'hui.\n"
            f"Patience, la value viendra 🎯"
        )
        if not dry_run:
            send_telegram(msg)
        else:
            print(f"\n[DRY RUN]\n{msg}")
        return

    summary = (
        f"🏀 <b>NBA Value Bot — {now}</b>\n\n"
        f"<b>{len(value_bets)} value bet(s) détectée(s)</b>\n"
        f"Seuil minimum : {int(MIN_VALUE*100)}%\n"
        f"Bankroll : {BANKROLL}€"
    )

    if not dry_run:
        send_telegram(summary)
        for vb in value_bets:
            time.sleep(0.5)
            send_telegram(format_value_bet_message(vb))
    else:
        print(f"\n{'='*55}")
        print("[DRY RUN] Messages qui seraient envoyés :")
        print(f"{'='*55}")
        print(summary)
        for vb in value_bets:
            print(f"\n{format_value_bet_message(vb)}")


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main():
    global MIN_VALUE

    parser = argparse.ArgumentParser(description="NBA Value Bet Bot")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche les value bets sans envoyer de Telegram")
    parser.add_argument("--min-value", type=float, default=MIN_VALUE,
                        help=f"Seuil de value minimum (défaut: {MIN_VALUE})")
    args = parser.parse_args()

    MIN_VALUE = args.min_value

    print("=" * 55)
    print("  🏀 NBA VALUE BOT")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Seuil value : {int(MIN_VALUE*100)}%")
    print(f"  Mode : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 55)

    # 1. Charger les stats NBA
    print("\n[1/3] Chargement stats NBA...")
    league_df = get_league_advanced_stats()

    # 2. Récupérer les cotes
    print("\n[2/3] Récupération des cotes...")
    totals = get_nba_odds_parsed()

    print(f"  {len(totals)} matchs avec cotes totals")

    if not totals:
        print("\n⚠️  Aucun match trouvé. Vérifie ta clé Odds API.")
        sys.exit(0)

    # 3. Détecter les value bets
    print(f"\n[3/3] Analyse des {len(totals)} matchs...")
    value_bets = detect_value_bets(totals, league_df)

    # 4. Envoyer les alertes
    print(f"\n{'='*55}")
    print(f"  Résultat : {len(value_bets)} value bet(s) trouvée(s)")
    print(f"{'='*55}")

    send_summary(value_bets, dry_run=args.dry_run)

    # Sauvegarder dans un fichier log
    if value_bets:
        log = {
            "timestamp":   datetime.now().isoformat(),
            "value_bets":  [asdict(vb) for vb in value_bets],
        }
        with open("value_bets_log.json", "a") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")
        print(f"\n📁 Value bets sauvegardées dans value_bets_log.json")


if __name__ == "__main__":
    main()
