"""
raw_playoff_diag.py – JEDNORAZOWA diagnostyka surowego JSON z ESPN API.

Świadomie NIE używa espn-api – czyste zapytanie HTTP (requests),
żeby zobaczyć surową strukturę meczów playoffowych 2025:
playoffTierType, matchupPeriodId, winner, id, totalPoints drużyn
oraz wykryć ewentualne mecze wielotygodniowe (to samo matchup id
w >1 matchupPeriodId).

Użycie: SWID="..." ESPN_S2="..." .venv/bin/python raw_playoff_diag.py
Wynik: /tmp/raw_playoff_structure.txt
"""
import json
import os
import pprint
from collections import defaultdict

import requests

URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2025/"
    "segments/0/leagues/58995?view=mMatchup&view=mMatchupScore"
)
# UWAGA: fantasy.espn.com (host z zadania) zwraca 202 + bot-challenge dla
# surowych zapytań requests. Ten sam API v3 jest dostępny pod
# lm-api-reads.fantasy.espn.com — dokładnie tego hosta używa biblioteka
# espn-api (constant.py: FANTASY_BASE_ENDPOINT). Zwracany JSON jest ten sam.
MIN_WEEK = 16          # tygodnie playoffowe 2025 (reg_season_count=15)
DEPTH = 6              # głębokość pprint przykładowego meczu (zmień, jeśli za płytko)

lines = []


def out(s=""):
    print(s)
    lines.append(s)


swid = os.environ["SWID"]
espn_s2 = os.environ["ESPN_S2"]

resp = requests.get(URL, cookies={"swid": swid, "espn_s2": espn_s2}, timeout=60)
resp.raise_for_status()
data = resp.json()

schedule = data.get("schedule", [])
out(f"Liczba wpisów w schedule: {len(schedule)}")

by_week = defaultdict(list)
for m in schedule:
    by_week[m.get("matchupPeriodId")].append(m)
out(f"Tygodnie obecne w schedule: {sorted(w for w in by_week if w is not None)}")

playoff = [m for m in schedule if (m.get("matchupPeriodId") or 0) >= MIN_WEEK]
out(f"Mecze z tygodni {MIN_WEEK}+: {len(playoff)}")

# 1. PEŁNA struktura jednego przykładowego meczu playoffowego
if playoff:
    out(f"\n===== PEŁNA STRUKTURA PRZYKŁADOWEGO MECZU PLAYOFFOWEGO (pprint, depth={DEPTH}) =====")
    sample = playoff[0]
    out(pprint.pformat(sample, width=120, sort_dicts=False, depth=DEPTH))
    out(f"\nKlucze najwyższego poziomu: {list(sample.keys())}")

# 2. Skrócona lista wszystkich meczów playoffowych
out("\n===== WSZYSTKIE MECZE PLAYOFFOWE (tyg. 16+) – skrót =====")
for m in playoff:
    home = m.get("home") or {}
    away = m.get("away") or {}
    out(f"  id={m.get('id')}  matchupPeriodId={m.get('matchupPeriodId')}  "
        f"playoffTierType={m.get('playoffTierType')!r}  winner={m.get('winner')!r}")
    out(f"    home: teamId={home.get('teamId')}  totalPoints={home.get('totalPoints')}")
    out(f"    away: teamId={away.get('teamId')}  totalPoints={away.get('totalPoints')}")

# 2b. pointsByScoringPeriod dla każdego meczu playoffowego
#     (ESPN reprezentuje mecz dwutygodniowy jako JEDEN wpis z jednym
#     matchupPeriodId, ale z >1 kluczem w pointsByScoringPeriod)
out("\n===== pointsByScoringPeriod meczów playoffowych =====")
for m in playoff:
    home = m.get("home") or {}
    away = m.get("away") or {}
    out(f"  id={m.get('id')}: home.teamId={home.get('teamId')} "
        f"pointsByScoringPeriod={home.get('pointsByScoringPeriod')}  "
        f"eliminationMatchupPeriod={home.get('eliminationMatchupPeriod')}")
    out(f"        away.teamId={away.get('teamId')} "
        f"pointsByScoringPeriod={away.get('pointsByScoringPeriod')}  "
        f"eliminationMatchupPeriod={away.get('eliminationMatchupPeriod')}")

# 3. Wykrywanie meczów wielotygodniowych (cały sezon)
out("\n===== MECZE WIELOTYGODNIOWE =====")
out("a) to samo matchup id w >1 matchupPeriodId:")
by_id = defaultdict(set)
for m in schedule:
    by_id[m.get("id")].add(m.get("matchupPeriodId"))
multi = {i: sorted(p) for i, p in by_id.items() if len(p) > 1}
if not multi:
    out("    BRAK – każde matchup id występuje w dokładnie jednym matchupPeriodId")
else:
    for i, periods in multi.items():
        out(f"    matchup id={i}: matchupPeriodId {periods}")

out("b) >1 klucz w pointsByScoringPeriod (mecz rozliczany w wielu tygodniach):")
found_b = False
for m in schedule:
    for side in ("home", "away"):
        s = m.get(side) or {}
        pbsp = s.get("pointsByScoringPeriod") or {}
        if len(pbsp) > 1:
            out(f"    matchup id={m.get('id')} matchupPeriodId={m.get('matchupPeriodId')} "
                f"{side}.teamId={s.get('teamId')} {side} tygodnie={sorted(pbsp)}")
            found_b = True
if not found_b:
    out("    BRAK")

with open("/tmp/raw_playoff_structure.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("\nZapisano: /tmp/raw_playoff_structure.txt")
