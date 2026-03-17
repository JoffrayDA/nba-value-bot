"""
odds_fetcher.py
---------------
Récupère les cotes NBA en temps réel via The Odds API.
Gratuit : 500 requêtes/mois → largement suffisant pour débuter.

Inscription : https://the-odds-api.com  (gratuit, pas de CB)
"""

import os
import requests
import json
from datetime import datetime, timezone


# ── Config ───────────────────────────────────────────────────────────────────
API_KEY      = os.getenv("ODDS_API_KEY", "REMPLACE_PAR_TA_CLE")
BASE_URL     = "https://api.the-odds-api.com/v4"

# Marchés qu'on surveille
MARKETS      = "totals,h2h,spreads"   # totals = over/under, h2h = moneyline
REGIONS      = "eu,uk"                # bookmakers européens (cotes décimales)
ODDS_FORMAT  = "decimal"
SPORT_KEY    = "basketball_nba"


# ── Récupération des matchs + cotes ──────────────────────────────────────────

def get_nba_odds() -> list[dict]:
    """
    Récupère tous les matchs NBA à venir avec leurs cotes.
    Retourne une liste de matchs enrichis.
    """
    url = f"{BASE_URL}/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey":      API_KEY,
        "regions":     REGIONS,
        "markets":     MARKETS,
        "oddsFormat":  ODDS_FORMAT,
        "dateFormat":  "iso",
    }

    print(f"[ODDS] Appel The Odds API ({SPORT_KEY})...")
    resp = requests.get(url, params=params, timeout=10)

    # Afficher les requêtes restantes (quota)
    remaining = resp.headers.get("x-requests-remaining", "?")
    used      = resp.headers.get("x-requests-used", "?")
    print(f"[ODDS] Quota : {used} utilisées / {remaining} restantes ce mois")

    if resp.status_code != 200:
        print(f"[ODDS] Erreur {resp.status_code}: {resp.text}")
        return []

    return resp.json()


def parse_totals(games: list[dict]) -> list[dict]:
    """
    Extrait les cotes over/under (totals) pour chaque match.
    Retourne une liste structurée avec :
      - les équipes, la date
      - le total proposé par chaque bookmaker
      - la moyenne et le meilleur prix disponible
    """
    results = []

    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        commence_time = game.get("commence_time", "")

        # Parser la date
        try:
            dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
            date_str = dt.astimezone().strftime("%d/%m %H:%M")
        except Exception:
            date_str = commence_time

        # Extraire les cotes totals de chaque bookmaker
        bookmaker_totals = []

        for bookmaker in game.get("bookmakers", []):
            bookie_name = bookmaker.get("title", "")
            for market in bookmaker.get("markets", []):
                if market.get("key") != "totals":
                    continue
                for outcome in market.get("outcomes", []):
                    bookmaker_totals.append({
                        "bookmaker": bookie_name,
                        "name":      outcome["name"],       # "Over" ou "Under"
                        "point":     outcome["point"],      # ex: 224.5
                        "price":     outcome["price"],      # cote décimale
                    })

        if not bookmaker_totals:
            continue

        # Grouper over vs under
        overs  = [x for x in bookmaker_totals if x["name"] == "Over"]
        unders = [x for x in bookmaker_totals if x["name"] == "Under"]

        if not overs or not unders:
            continue

        # Ligne de total médiane (ce que les bookies pensent)
        median_line = sorted([x["point"] for x in overs])[len(overs) // 2]

        # Meilleure cote over/under disponible
        best_over  = max(overs,  key=lambda x: x["price"])
        best_under = max(unders, key=lambda x: x["price"])

        results.append({
            "home_team":    home,
            "away_team":    away,
            "date":         date_str,
            "game_id":      game.get("id", ""),
            "total_line":   median_line,           # ligne de total des bookmakers
            "best_over":    best_over,             # meilleure cote Over
            "best_under":   best_under,            # meilleure cote Under
            "n_bookmakers": len(game.get("bookmakers", [])),
            "raw_totals":   bookmaker_totals,
        })

    return results


def get_nba_moneylines(games: list[dict]) -> list[dict]:
    """
    Extrait les cotes moneyline (1X2) pour chaque match.
    Utile pour modéliser les probabilités de victoire.
    """
    results = []

    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")

        h2h_odds = {"home": [], "away": []}

        for bookmaker in game.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    if outcome["name"] == home:
                        h2h_odds["home"].append(outcome["price"])
                    elif outcome["name"] == away:
                        h2h_odds["away"].append(outcome["price"])

        if not h2h_odds["home"] or not h2h_odds["away"]:
            continue

        avg_home = sum(h2h_odds["home"]) / len(h2h_odds["home"])
        avg_away = sum(h2h_odds["away"]) / len(h2h_odds["away"])

        # Probabilité implicite (sans marge)
        raw_home = 1 / avg_home
        raw_away = 1 / avg_away
        total    = raw_home + raw_away
        prob_home = raw_home / total   # Dévigoré
        prob_away = raw_away / total

        results.append({
            "home_team":       home,
            "away_team":       away,
            "avg_odd_home":    round(avg_home, 3),
            "avg_odd_away":    round(avg_away, 3),
            "implied_prob_home": round(prob_home, 3),
            "implied_prob_away": round(prob_away, 3),
        })

    return results


# ── Utilitaire : cote → probabilité ──────────────────────────────────────────

def odd_to_prob(odd: float) -> float:
    """Convertit une cote décimale en probabilité implicite."""
    return round(1 / odd, 4) if odd > 1 else 0.0


def prob_to_odd(prob: float) -> float:
    """Convertit une probabilité en cote équitable."""
    return round(1 / prob, 2) if prob > 0 else 0.0


# ── Test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  ODDS FETCHER — Test")
    print("=" * 55)

    if API_KEY == "REMPLACE_PAR_TA_CLE":
        print("\n⚠️  Remplace API_KEY par ta vraie clé The Odds API")
        print("   → https://the-odds-api.com (gratuit)")

        # Données fictives pour montrer le format
        print("\nExemple de sortie avec données simulées :")
        example = [{
            "home_team":    "Boston Celtics",
            "away_team":    "Miami Heat",
            "date":         "17/03 01:00",
            "total_line":   222.5,
            "best_over":    {"bookmaker": "Bet365", "point": 222.5, "price": 1.91},
            "best_under":   {"bookmaker": "Pinnacle", "point": 222.5, "price": 1.95},
            "n_bookmakers": 12,
        }]
        print(json.dumps(example, indent=2, ensure_ascii=False))
    else:
        games  = get_nba_odds()
        totals = parse_totals(games)
        print(f"\n{len(totals)} matchs avec cotes totals trouvés :\n")
        for m in totals[:5]:
            print(f"  {m['date']} | {m['away_team']} @ {m['home_team']}")
            print(f"    Ligne : {m['total_line']} pts")
            print(f"    Best Over  : {m['best_over']['price']} ({m['best_over']['bookmaker']})")
            print(f"    Best Under : {m['best_under']['price']} ({m['best_under']['bookmaker']})")
            print()
