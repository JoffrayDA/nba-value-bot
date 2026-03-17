# 🏀 NBA Value Bot

Bot de détection de value bets sur les totaux NBA.

## Installation

```bash
pip install -r requirements.txt
```

## Configuration (2 minutes)

### 1. Clé The Odds API (gratuit)
1. Va sur https://the-odds-api.com et crée un compte gratuit
2. Copie ta clé API

### 2. Bot Telegram (optionnel mais recommandé)
1. Dans Telegram, cherche @BotFather → /newbot → copie le token
2. Cherche @userinfobot → envoie /start → copie ton chat_id

### 3. Variables d'environnement
```bash
# Windows (Git Bash)
export ODDS_API_KEY="ta_cle_ici"
export TELEGRAM_TOKEN="ton_token_ici"
export TELEGRAM_CHAT_ID="ton_chat_id_ici"

# Ou crée un fichier .env (ne jamais commit ce fichier !)
```

## Utilisation

```bash
# Scan complet avec alertes Telegram
python value_bot.py

# Mode test (affiche sans envoyer)
python value_bot.py --dry-run

# Changer le seuil de value minimum
python value_bot.py --min-value 0.06  # 6% minimum

# Automatiser (toutes les 6h avec cron ou Task Scheduler)
# Ajouter dans crontab : 0 */6 * * * cd /chemin/bot && python value_bot.py
```

## Architecture

```
nba_fetcher.py   → Données NBA (stats avancées, forme des équipes)
                   Source : stats.nba.com via nba_api (GRATUIT)

odds_fetcher.py  → Cotes bookmakers en temps réel
                   Source : The Odds API (500 req/mois gratuit)

value_bot.py     → Cerveau : compare modèle vs bookmakers
                   → Calcul de value + mise Kelly
                   → Alertes Telegram
```

## Comment ça marche

### Modèle de prédiction (totaux)
Le bot utilise deux sources de données combinées :

**60% — Stats de saison complète**
- PACE (rythme de jeu)
- Offensive Rating / Defensive Rating
- Permet d'identifier les matchs structurellement à fort/faible scoring

**40% — Forme récente (10 derniers matchs)**
- Points marqués / encaissés
- Capture les tendances récentes (blessés, retour de forme...)

**Résultat** : Total prédit en points

### Calcul de la value
```
value = (probabilité_modèle × cote_bookmaker) - 1
```
- value > 0 = pari profitable sur le long terme
- value > 4% = seuil d'alerte (paramétrable)
- value > 8% = opportunité forte 🔥

### Mise conseillée (Kelly fractionné)
```
Kelly pur = (p × (odd-1) - (1-p)) / (odd-1)
Mise = Kelly × 25% × Bankroll   (fraction conservatrice)
```

## Limitations & Améliorations futures

Le modèle actuel est volontairement simple pour être lisible.
Axes d'amélioration :
- [ ] Intégrer les blessés (ESPN API ou rotowire)
- [ ] Paramétrer l'écart-type par matchup (haute/basse offense)
- [ ] Ajouter les spreads et player props
- [ ] Back-testing sur saisons passées
- [ ] Dashboard web pour suivre les performances

## ⚠️ Avertissement

Ce bot est un outil d'analyse. Les paris sportifs comportent des risques.
Ne misez jamais plus que ce que vous pouvez vous permettre de perdre.
