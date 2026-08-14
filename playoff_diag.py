"""
playoff_diag.py – JEDNORAZOWY skrypt diagnostyczny struktury playoffów w lidze ESPN.

NIE modyfikuje fetch_league.py. Wynik zapisuje do /tmp/playoff_structure.txt
(poza repo – czysta diagnostyka).

Użycie (tak samo jak fetch_league.py):
    SWID="..." ESPN_S2="..." python playoff_diag.py

Co robi:
1. Dla lat 2012–2025 wypisuje league.settings.reg_season_count
   (i pomocniczo settings.playoff_team_count – ile drużyn w playoffach).
2. Dla 2025 i 2022 wypisuje WSZYSTKIE mecze z tygodni PO reg_season_count.
"""
import os
from espn_api.football import League

LEAGUE_ID = 58995
YEARS = list(range(2012, 2026))   # 2012..2025
DETAIL_YEARS = [2025, 2022]       # lata ze szczegółowym rozpisywaniem playoffów


def make_league(year):
    """League z autoryzacją, gdy SWID+ESPN_S2 są ustawione (jak fetch_league.py)."""
    kwargs = {"league_id": LEAGUE_ID, "year": year}
    swid = os.environ.get("SWID")
    espn_s2 = os.environ.get("ESPN_S2")
    if swid and espn_s2:
        kwargs["swid"] = swid
        kwargs["espn_s2"] = espn_s2
    return League(**kwargs)


lines = []


def out(s=""):
    print(s)
    lines.append(s)


# 1. reg_season_count dla wszystkich lat
out("=== reg_season_count / playoff_team_count wg lat ===")
for year in YEARS:
    try:
        league = make_league(year)
        rsc = league.settings.reg_season_count
        try:
            ptc = league.settings.playoff_team_count
        except AttributeError:
            ptc = "?"
        out(f"{year}: reg_season_count={rsc}  playoff_team_count={ptc}  drużyn={len(league.teams)}")
    except Exception as e:
        out(f"{year}: BŁĄD: {e}")

# 2. Szczegółowe mecze playoffowe dla wybranych lat
for year in DETAIL_YEARS:
    try:
        league = make_league(year)
        rsc = league.settings.reg_season_count
        ptc = league.settings.playoff_team_count
        out(f"\n===== {year}: reg_season_count={rsc}, playoff_team_count={ptc} =====")
        total = 0
        for week in range(rsc + 1, 21):  # tygodnie PO sezonie zasadniczym
            try:
                matchups = league.scoreboard(week=week)
            except Exception:
                matchups = []
            if not matchups:
                break
            for m in matchups:
                home = m.home_team.team_name if m.home_team else "—"
                away = m.away_team.team_name if m.away_team else "—"
                out(f"  Tydz {week}: {home} {m.home_score} - {m.away_score} {away}")
                total += 1
        if total == 0:
            # Brak tygodni po reg_season -> liga bez playoffów; pokaż końcówkę
            # sezonu zasadniczego, żeby było widać strukturę.
            out(f"  (BRAK meczów po tygodniu {rsc} – brak playoffów)")
            out(f"  Końcówka sezonu zasadniczego (tygodnie {max(1, rsc - 4)}–{rsc}):")
            for week in range(max(1, rsc - 4), rsc + 1):
                try:
                    matchups = league.scoreboard(week=week)
                except Exception:
                    matchups = []
                for m in matchups:
                    home = m.home_team.team_name if m.home_team else "—"
                    away = m.away_team.team_name if m.away_team else "—"
                    out(f"  Tydz {week}: {home} {m.home_score} - {m.away_score} {away}")
                total += len(matchups)
        out(f"  --- {year}: razem pokazanych meczów = {total}")
    except Exception as e:
        out(f"\n{year}: BŁĄD: {e}")

# Zapis do pliku poza repo
with open("/tmp/playoff_structure.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("\nZapisano: /tmp/playoff_structure.txt")
