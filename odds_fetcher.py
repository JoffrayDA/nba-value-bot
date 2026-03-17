"""
odds_fetcher.py
---------------
Récupère les cotes NBA en temps réel via la librairie ps3838api.
Authentification : username + password Asian Connect via variables d'env.

pip install ps3838api
"""

import os
from dotenv import load_dotenv
load_dotenv()

from ps3838api.api.client import PinnacleClient
from datetime import datetime

client = PinnacleClient()

SPORT_ID   = 4    # Basketball
LEAGUE_NBA = 487  # NBA


def odd_to_prob(odd: float) -> float:
    return round(1 / odd, 4) if odd > 1 else 0.0

def prob_to_odd(prob: float) -> float:
    return round(1 / prob, 2) if prob > 0 else 0.0


def get_nba_fixtures() -> list[dict]:
    print("[PS3838] Récupération des fixtures NBA...")
    try:
        resp = client.get_fixtures(sport_id=SPORT_ID, league_ids=[LEAGUE_NBA])
    except Exception as e:
        print(f"[PS3838] Erreur fixtures : {e}")
        return []

    fixtures = []
    for league in resp.get("league", []):
        for event in league.get("events", []):
            if event.get("liveStatus", 0) == 1:
                continue
            if event.get("status", "O") != "O":
                continue
            starts = event.get("starts", "")
            try:
                dt       = datetime.fromisoformat(starts.replace("Z", "+00:00"))
                date_str = dt.strftime("%d/%m %H:%M")
            except Exception:
                date_str = starts
            fixtures.append({
                "event_id":  event["id"],
                "home_team": event.get("home", ""),
                "away_team": event.get("away", ""),
                "starts":    starts,
                "date":      date_str,
            })

    print(f"[PS3838] {len(fixtures)} matchs NBA trouvés")
    return fixtures


def get_nba_odds_raw() -> dict:
    print("[PS3838] Récupération des cotes NBA...")
    try:
        return client.get_odds(sport_id=SPORT_ID, league_ids=[LEAGUE_NBA])
    except Exception as e:
        print(f"[PS3838] Erreur cotes : {e}")
        return {}


def parse_totals(fixtures: list[dict], odds_data: dict) -> list[dict]:
    fixture_map = {f["event_id"]: f for f in fixtures}
    results     = []

    for league in odds_data.get("leagues", []):
        for event in league.get("events", []):
            event_id = event["id"]
            fixture  = fixture_map.get(event_id)
            if not fixture:
                continue
            for period in event.get("periods", []):
                if period.get("number") != 0:
                    continue
                if period.get("status") != 1:
                    continue
                totals = period.get("totals", [])
                if not totals:
                    continue
                main_total = next(
                    (t for t in totals if not t.get("altLineId")),
                    totals[0]
                )
                line      = main_total.get("points", 0)
                over_odd  = main_total.get("over", 0)
                under_odd = main_total.get("under", 0)
                if not line or not over_odd or not under_odd:
                    continue
                results.append({
                    "event_id":     event_id,
                    "home_team":    fixture["home_team"],
                    "away_team":    fixture["away_team"],
                    "date":         fixture["date"],
                    "total_line":   line,
                    "best_over":    {"bookmaker": "PS3838", "point": line, "price": over_odd},
                    "best_under":   {"bookmaker": "PS3838", "point": line, "price": under_odd},
                    "n_bookmakers": 1,
                    "raw_totals":   totals,
                })

    print(f"[PS3838] {len(results)} matchs avec cotes totals")
    return results


def get_nba_odds_parsed() -> list[dict]:
    fixtures  = get_nba_fixtures()
    if not fixtures:
        return []
    odds_data = get_nba_odds_raw()
    if not odds_data:
        return []
    return parse_totals(fixtures, odds_data)


if __name__ == "__main__":
    print("=" * 55)
    print("  PS3838 ODDS FETCHER — Test")
    print("=" * 55)
    try:
        balance = client.get_client_balance()
        print(f"\n Connecté ! Solde : {balance.get('availableBalance', '?')} {balance.get('currency', '')}")
    except Exception as e:
        print(f"\n Erreur de connexion : {e}")
        print("  Vérifie PS3838_USERNAME et PS3838_PASSWORD dans ton .env")
        exit(1)

    totals = get_nba_odds_parsed()
    if not totals:
        print("\nAucun match NBA disponible pour le moment.")
    else:
        print(f"\n{len(totals)} matchs disponibles :\n")
        for m in totals[:5]:
            print(f"  {m['date']} | {m['away_team']} @ {m['home_team']}")
            print(f"    Ligne  : {m['total_line']} pts")
            print(f"    Over   : {m['best_over']['price']}")
            print(f"    Under  : {m['best_under']['price']}")
            print()
