"""
fetch_league.py – pobiera pełną historię tabeli wyników ligi ESPN Fantasy Football
(League ID: 58995) i zapisuje do plików JSON: standings, matchups, rosters,
draft, franchises oraz playoffs (drabinka playoffów ze surowego API).

Przed uruchomieniem ustaw zmienne środowiskowe (dla lat prywatnych 2012–2018):
    SWID="..." ESPN_S2="..." python fetch_league.py

UWAGA: SWID i ESPN_S2 to prywatne dane sesji ESPN – NIGDY nie zapisuj ich
w kodzie ani nie commituj do repozytorium.
"""
# os – do odczytu zmiennych środowiskowych (SWID, ESPN_S2)
# json – do zapisu wyników w formacie JSON
# pathlib.Path – do tworzenia folderów i ścieżek plików
import json
import os
from pathlib import Path

# ftfy naprawia zepsute kodowanie znaków w danych z ESPN API
# (np. "ZambrÃ³w" → "Zambrów" — double-encoded UTF-8 w starszych sezonach).
# Stosujemy _clean_text() przy każdym odczycie tekstu z API, więc wszystkie
# pliki JSON (standings, matchups, rosters, draft, franchises) są od razu czyste.
import ftfy

# Importujemy klasę League z biblioteki espn-api
from espn_api.football import League

# requests – tylko do surowego zapytania o playoffy (build_playoffs).
# espn-api nie udostępnia pola playoffTierType, więc drabinkę czytamy
# bezpośrednio z JSON API.
import requests


def _clean_text(text):
    """Naprawia zepsute kodowanie znaków (np. double-encoded UTF-8) w tekście z ESPN API."""
    if not isinstance(text, str):
        return text
    return ftfy.fix_text(text)

# ---------------------------------------------------------------------------
# KONFIGURACJA: zakresy lat – prywatne (wymagają autoryzacji) i publiczne
# ---------------------------------------------------------------------------
LEAGUE_ID = 58995                              # niezmienne ID naszej ligi
# Lata, w których liga była prywatna – dostęp tylko z SWID + ESPN_S2
PRIVATE_YEARS = list(range(2012, 2019))        # 2012, 2013, ..., 2018
# Lata, w których liga jest już publiczna – nie potrzeba logowania
PUBLIC_YEARS = list(range(2019, 2026))         # 2019, 2020, ..., 2025


def _get_owner_name(team):
    """Wyciąga imię i nazwisko właściciela z obiektu drużyny ESPN.

    Preferuje firstName + lastName z owners[0]. Jeśli którekolwiek jest puste
    lub nie istnieje, używa displayName jako fallbacku. Jeśli owners w ogóle
    nie istnieje, zwraca None.
    """
    try:
        owner = team.owners[0]
        first = (owner.get("firstName") or "").strip()
        last = (owner.get("lastName") or "").strip()
        if first or last:
            return f"{first} {last}".strip()
        return (owner.get("displayName") or "").strip() or None
    except (AttributeError, IndexError, TypeError):
        return None


def _get_owner_id(team):
    """Zwraca stabilny identyfikator właściciela (ESPN UUID) lub None."""
    try:
        return team.owners[0]["id"]
    except (AttributeError, IndexError, TypeError, KeyError):
        return None


def fetch_year_standings(league_id, year, swid=None, espn_s2=None):
    """Łączy się z ligą ESPN dla danego roku i zwraca listę statystyk drużyn.

    Każda drużyna to słownik (dict) z kluczami:
        team_name, team_id, owner_id, owner_name,
        wins, losses, ties, points_for, points_against

    Jeśli podano swid i espn_s2, używa ich do autoryzacji (potrzebne
    dla prywatnych sezonów 2012–2018). W przeciwnym razie łączy się
    anonimowo (dla publicznych sezonów 2019+).
    """
    # Tworzymy słownik z argumentami – tylko te, które faktycznie przekazano
    kwargs = {"league_id": league_id, "year": year}
    if swid and espn_s2:
        kwargs["swid"] = swid
        kwargs["espn_s2"] = espn_s2

    # Łączymy się z ESPN – League() wykonuje zapytanie HTTP
    league = League(**kwargs)

    # Budujemy listę wyników: dla każdej drużyny zapisujemy jej statystyki
    teams_data = []
    for team in league.teams:
        # final_standing = miejsce w klasyfikacji KOŃCOWEJ (po playoffach), 1 = mistrz.
        # Nie wszystkie sezony/API zwracają to pole — na wszelki wypadek try/except.
        try:
            final_standing = team.final_standing
        except AttributeError:
            final_standing = None

        teams_data.append({
            "team_name": _clean_text(team.team_name),
            "team_id": team.team_id,
            "owner_id": _get_owner_id(team),
            "owner_name": _get_owner_name(team),
            "wins": team.wins,
            "losses": team.losses,
            "ties": team.ties,
            "points_for": team.points_for,
            "points_against": team.points_against,
            "final_standing": final_standing,
        })

    return teams_data


def fetch_year_matchups(league_id, year, swid=None, espn_s2=None):
    """Pobiera wyniki wszystkich meczów tygodniowych dla danego roku.

    Sprawdza tygodnie 1–18 po kolei. Jeśli dla danego tygodnia nie ma
    żadnych meczów (sezon się jeszcze nie zaczął lub już się skończył),
    przerywa pętlę i przechodzi do kolejnego roku.

    Zwraca słownik: klucz = numer tygodnia (str), wartość = lista meczów.
    Każdy mecz to słownik z kluczami:
        home_team, home_score, away_team, away_score
    """
    # Tworzymy obiekt ligi (tak samo jak przy standings, ale będziemy
    # na nim wywoływać .scoreboard() zamiast iterować po .teams)
    kwargs = {"league_id": league_id, "year": year}
    if swid and espn_s2:
        kwargs["swid"] = swid
        kwargs["espn_s2"] = espn_s2

    league = League(**kwargs)

    # Słownik na wyniki wszystkich tygodni w tym roku
    weeks_data = {}

    # NFL regular season ma maksymalnie 18 tygodni – sprawdzamy każdy
    for week in range(1, 19):
        try:
            # scoreboard(week=N) zwraca listę obiektów Matchup dla danego tygodnia
            matchups = league.scoreboard(week=week)

            # Jeśli lista jest pusta – sezon się skończył, wychodzimy z pętli tygodni
            if not matchups:
                break

            # Przetwarzamy każdy mecz – zapisujemy nazwy drużyn i ich wyniki
            week_matchups = []
            for match in matchups:
                week_matchups.append({
                    "home_team": _clean_text(match.home_team.team_name),
                    "home_score": match.home_score,
                    "away_team": _clean_text(match.away_team.team_name),
                    "away_score": match.away_score,
                })

            # Zapisujemy wyniki tygodnia pod kluczem tekstowym (np. "1", "2", ...)
            weeks_data[str(week)] = week_matchups

        except Exception:
            # Błąd przy danym tygodniu – przerywamy tylko pętlę tygodni
            # (nie cały skrypt), bo sezon mógł mieć mniej tygodni
            break

    return weeks_data


def fetch_year_rosters(league_id, year, swid=None, espn_s2=None):
    """Pobiera składy drużyn (rostery) dla danego roku.

    Dla każdej drużyny w lidze pobiera listę zawodników z team.roster
    (atrybut wypełniany automatycznie przy tworzeniu obiektu League).
    Każdy zawodnik to słownik z kluczami: name, position, proTeam.

    Zwraca listę słowników: [{"team_name": "...", "players": [...]}, ...].
    Jeśli roster danej drużyny jest pusty, lista players będzie pusta.
    """
    # Budujemy argumenty dla konstruktora League – auth tylko jeśli podano
    kwargs = {"league_id": league_id, "year": year}
    if swid and espn_s2:
        kwargs["swid"] = swid
        kwargs["espn_s2"] = espn_s2

    league = League(**kwargs)

    # Dla każdej drużyny zbieramy jej roster
    teams_rosters = []
    for team in league.teams:
        # team.roster to lista obiektów Player z biblioteki espn-api
        players = []
        for player in team.roster:
            players.append({
                "name": _clean_text(player.name),
                "position": player.position,
                "proTeam": player.proTeam,
            })
        teams_rosters.append({
            "team_name": _clean_text(team.team_name),
            "players": players,
        })

    return teams_rosters


def fetch_year_draft(league_id, year, swid=None, espn_s2=None):
    """Pobiera wyniki draftu: kto kogo wybrał w której rundzie.

    league.draft to lista obiektów BasePick — wypełniana automatycznie
    przy konstrukcji League (jeśli draft się odbył). Jeśli liga nie ma
    jeszcze draftu (np. sezon przed draftem), lista będzie pusta.

    Zwraca listę słowników: [{"round_num": N, "round_pick": N,
    "player_name": "...", "team_name": "..."}, ...].
    """
    # Budujemy argumenty dla League – auth tylko jeśli podano
    kwargs = {"league_id": league_id, "year": year}
    if swid and espn_s2:
        kwargs["swid"] = swid
        kwargs["espn_s2"] = espn_s2

    league = League(**kwargs)

    # league.draft: lista BasePick (round_num, round_pick, playerName, team)
    picks = []
    for pick in league.draft:
        picks.append({
            "round_num": pick.round_num,
            "round_pick": pick.round_pick,
            "player_name": _clean_text(pick.playerName),
            "team_name": _clean_text(pick.team.team_name),
        })

    return picks


def build_franchises(all_standings):
    """Buduje historię franczyz z danych standings (już w pamięci).

    Grupuje drużyny po stabilnym owner_id (ESPN UUID), więc zmiany team_id
    ani team_name nie rozbijają franczyzy. Dla każdej franczyzy zbiera:
      - listę sezonów (posortowaną rosnąco)
      - wszystkie nazwy drużyny w kolejności chronologicznej,
        bez Powtórzeń pod rząd (np. "Minsk Maz Old Goats" -> "MMz Old Goats")
      - aktualną (ostatnią) nazwę
      - sumaryczne statystyki (wins, losses, ties, PF, PA)

    Drużyny bez owner_id są pomijane (nie da się ich przypisać do franczyzy).
    """
    # ---------------------------------------------------------------------
    # RĘCZNE WYJĄTKI – oparte na wiedzy o lidze, a nie wykryte automatycznie.
    #
    # (1) MANUAL_OWNER_MERGES: jedna osoba grała na dwóch różnych kontach
    #     ESPN (różne owner_id), więc jej sezony mają iść do JEDNEJ franczyzy.
    #     Edinburgh Yer Maws i Madison Bumgarners to ta sama osoba.
    MANUAL_OWNER_MERGES = {
        "{3AA0BC31-A484-4C48-A0BC-31A4843C4868}":  # Edinburgh Yer Maws
        "{4F1095CC-1DCD-427C-9095-CC1DCDE27C08}",   # Madison Bumgarners
    }
    # (2) TEAM_NAME_ALIASES: literówka/wariant nazwy w źródle ESPN (ten sam
    #     owner_id), nie faktyczna zmiana nazwy. Po zamianie istniejąca logika
    #     "bez duplikatów pod rząd" sama usunie powtórzenie.
    TEAM_NAME_ALIASES = {
        "Zambrow Bears": "Zambrów Bears",
    }
    # ---------------------------------------------------------------------

    # Grupujemy sezony po owner_id (najpierw scalenie kont wg MANUAL_OWNER_MERGES)
    # final_standing może być None – None != 1, więc nie przeszkadza w liczeniu.
    by_owner = {}  # owner_id -> lista (year, team_name, w, l, t, pf, pa, final_standing)
    for year_str, teams in sorted(all_standings.items(), key=lambda x: int(x[0])):
        year = int(year_str)
        for team in teams:
            oid = team.get("owner_id")
            if not oid:
                continue
            oid = MANUAL_OWNER_MERGES.get(oid, oid)
            if oid not in by_owner:
                by_owner[oid] = []
            by_owner[oid].append((
                year,
                team["team_name"],
                team["wins"],
                team["losses"],
                team["ties"],
                team["points_for"],
                team["points_against"],
                team.get("final_standing"),
            ))

    # Budujemy obiekty franczyz
    franchises = []
    for oid, seasons in by_owner.items():
        seasons_sorted = sorted(seasons, key=lambda s: s[0])

        # Lata
        years_list = [s[0] for s in seasons_sorted]

        # Nazwy chronologicznie, bez duplikatów pod rząd
        # (najpierw alias literówek z TEAM_NAME_ALIASES)
        names_list = []
        for s in seasons_sorted:
            name = TEAM_NAME_ALIASES.get(s[1], s[1])
            if not names_list or names_list[-1] != name:
                names_list.append(name)

        current_name = names_list[-1] if names_list else ""
        previous_names = names_list[:-1] if len(names_list) > 1 else []

        # Sumy statystyk
        total_wins = sum(s[2] for s in seasons_sorted)
        total_losses = sum(s[3] for s in seasons_sorted)
        total_ties = sum(s[4] for s in seasons_sorted)
        total_pf = round(sum(s[5] for s in seasons_sorted), 2)
        total_pa = round(sum(s[6] for s in seasons_sorted), 2)

        # Mistrzostwa: liczba sezonów, w których final_standing == 1
        # final_standing może być None (dla starych lat/braku danych); None != 1 → OK.
        championships = sum(1 for s in seasons_sorted if s[7] == 1)

        # Owner name — bierzemy z pierwszego sezonu, który go ma
        owner_name = ""
        for year_str in sorted(all_standings.keys(), key=int):
            for team in all_standings[year_str]:
                if team.get("owner_id") == oid and team.get("owner_name"):
                    owner_name = team["owner_name"]
                    break
            if owner_name:
                break

        franchises.append({
            "owner_id": oid,
            "owner_name": owner_name,
            "current_name": current_name,
            "previous_names": previous_names,
            "all_names": names_list,  # pełna lista chronologiczna bez duplikatów pod rząd
            "seasons": years_list,
            "total_wins": total_wins,
            "total_losses": total_losses,
            "total_ties": total_ties,
            "total_pf": total_pf,
            "total_pa": total_pa,
            "championships": championships,
        })

    # 3-poziomowe sortowanie:
    #   1. Liczba sezonów malejąco (najdłużej grający pierwsi)
    #   2. Rok dołączenia rosnąco (wcześniej dołączeni wyżej)
    #   3. Win ratio malejąco (lepszy bilans wyżej)
    def sort_key(f):
        seasons_count = len(f['seasons'])
        join_year = min(f['seasons'])
        total_games = f['total_wins'] + f['total_losses'] + f['total_ties']
        win_ratio = (f['total_wins'] + 0.5 * f['total_ties']) / total_games if total_games > 0 else 0
        return (-seasons_count, join_year, -win_ratio)

    franchises.sort(key=sort_key)
    return franchises


# ---------------------------------------------------------------------------
# PLAYOFFY – surowe API ESPN (requests, bez espn-api)
# ---------------------------------------------------------------------------
# Host lm-api-reads.fantasy.espn.com – fantasy.espn.com blokuje surowe zapytania
# (HTTP 202 + bot-challenge). To ten sam API v3, z którego korzysta espn-api
# (constant.py: FANTASY_BASE_ENDPOINT).
ESPN_API_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

# playoffTierType spoza tego zbioru oznacza mecz playoffowy (dowolny tier:
# WINNERS_BRACKET, WINNERS_CONSOLATION_LADDER, LOSERS_CONSOLATION_LADDER).
NON_PLAYOFF_TIERS = {None, "", "NONE"}

# Pola meczu, które MUSZĄ istnieć, żebyśmy uznali strukturę za znaną.
# Jakiegokolwiek brakuje -> nie zgadujemy, pomijamy cały rok.
# away/home są sprawdzane osobno w build_playoffs: mecz z JEDNĄ drużyną
# to znany wzorzec ESPN – wolny los (bye) – pomijamy sam mecz, nie rok.
REQUIRED_MATCH_FIELDS = ("id", "matchupPeriodId", "playoffTierType", "winner")
REQUIRED_TEAM_FIELDS = ("teamId", "pointsByScoringPeriod")


def _fetch_raw_schedule(year, swid=None, espn_s2=None):
    """Pobiera surową listę meczów ('schedule') z ESPN API dla danego roku.

    Lata <2018: endpoint leagueHistory – zwraca LISTĘ lig; bierzemy wpis
    z pasującym seasonId (gdy brak – ostatni). Lata 2018+: endpoint
    seasons/.../leagues – zwraca obiekt z kluczem 'schedule'.
    """
    cookies = {"SWID": swid, "espn_s2": espn_s2} if swid and espn_s2 else None
    if year < 2018:
        url = (f"{ESPN_API_BASE}/leagueHistory/{LEAGUE_ID}"
               f"?seasonId={year}&view=mMatchup&view=mMatchupScore")
        data = requests.get(url, cookies=cookies, timeout=60).json()
        if isinstance(data, list):
            data = next((e for e in data if e.get("seasonId") == year), data[-1])
    else:
        url = (f"{ESPN_API_BASE}/seasons/{year}/segments/0/leagues/{LEAGUE_ID}"
               f"?view=mMatchup&view=mMatchupScore")
        data = requests.get(url, cookies=cookies, timeout=60).json()
    return data.get("schedule", [])


def build_playoffs(all_standings, swid=None, espn_s2=None):
    """Buduje drabinkę playoffów dla lat 2012–2025 ze surowego API ESPN.

    Dla każdego roku:
      - pobiera surowy 'schedule' (view=mMatchup&view=mMatchupScore),
      - wybiera mecze, gdzie playoffTierType nie jest puste/'NONE',
      - WALIDUJE strukturę: mecz musi mieć id/matchupPeriodId/
        playoffTierType/winner, a drużyny – teamId i pointsByScoringPeriod.
        Brak czegokolwiek = "nietypowa struktura, pomijam" (cały rok).
        Wyjątek: mecz z jedną drużyną (away/home == None) to wolny los
        (bye) – znany wzorzec ESPN, pomijamy tylko ten mecz.
      - mapuje teamId -> nazwę drużyny z JUŻ pobranych standings
        (bez dodatkowych zapytań do API),
      - sumuje pointsByScoringPeriod (obsługuje mecze 1- i wielotygodniowe),
      - grupuje mecze wg matchupPeriodId = runda.

    Zwraca (playoffs, ok_years, unusual_years):
      playoffs = {"2025": {"rounds": [{"matchup_period": 16, "games": [...]}]}, ...}
    """
    playoffs = {}
    ok_years = []
    unusual_years = []

    for year in PRIVATE_YEARS + PUBLIC_YEARS:
        year_str = str(year)
        # Drużyny z danego roku: team_id -> team_name (ze standings)
        team_names = {
            t["team_id"]: t["team_name"]
            for t in all_standings.get(year_str, [])
        }

        try:
            schedule = _fetch_raw_schedule(year, swid=swid, espn_s2=espn_s2)

            # Mecze playoffowe = tier spoza NON_PLAYOFF_TIERS
            playoff_matches = [
                m for m in schedule
                if m.get("playoffTierType") not in NON_PLAYOFF_TIERS
            ]

            # Walidacja struktury każdego meczu playoffowego – bez zgadywania.
            # Mecz z jedną drużyną (home lub away == None) to znany wzorzec
            # ESPN: wolny los (bye) w drabince – pomijamy TYLKO ten mecz.
            structure_ok = True
            bye_count = 0
            real_matches = []
            for m in playoff_matches:
                if any(m.get(f) is None for f in REQUIRED_MATCH_FIELDS):
                    structure_ok = False
                    break
                home, away = m.get("home"), m.get("away")
                if home is None and away is None:
                    structure_ok = False
                    break
                if home is None or away is None:
                    bye_count += 1
                    continue
                for team in (home, away):
                    if any(team.get(f) is None for f in REQUIRED_TEAM_FIELDS):
                        structure_ok = False
                        break
                    if team.get("teamId") not in team_names:
                        # Nie znamy nazwy drużyny – nie zapisujemy półdanych
                        structure_ok = False
                        break
                if not structure_ok:
                    break
                real_matches.append(m)

            if not structure_ok:
                raise ValueError("brak wymaganych pól w meczu playoffowym")

            # Mapowanie meczów na drabinkę
            rounds = {}
            for m in sorted(real_matches, key=lambda x: x.get("id") or 0):
                home = m["home"]
                away = m["away"]
                # Suma wszystkich kluczy pointsByScoringPeriod – działa dla
                # meczów 1-tygodniowych (1 klucz) i wielotygodniowych (2+ klucze)
                home_score = round(sum(home["pointsByScoringPeriod"].values()), 2)
                away_score = round(sum(away["pointsByScoringPeriod"].values()), 2)
                weeks = sorted(int(w) for w in home["pointsByScoringPeriod"])

                # winner: nazwa drużyny zamiast HOME/AWAY
                if m["winner"] == "HOME":
                    winner = team_names[home["teamId"]]
                elif m["winner"] == "AWAY":
                    winner = team_names[away["teamId"]]
                else:
                    winner = None  # np. UNDECIDED – nie zgadujemy

                game = {
                    "team_a": team_names[home["teamId"]],
                    "team_a_score": home_score,
                    "team_b": team_names[away["teamId"]],
                    "team_b_score": away_score,
                    "winner": winner,
                    "tier": m["playoffTierType"],
                    "weeks": weeks,
                }
                rounds.setdefault(m["matchupPeriodId"], []).append(game)

            playoffs[year_str] = {
                "rounds": [
                    {"matchup_period": period, "games": games}
                    for period, games in sorted(rounds.items())
                ]
            }
            ok_years.append(year)
            n_rounds = len(rounds)
            n_games = len(real_matches)
            bye_note = f", {bye_count} BYE pominięte" if bye_count else ""
            print(f"  [{year}] OK ({n_rounds} rund, {n_games} meczów{bye_note})")
        except Exception as e:
            unusual_years.append(year)
            print(f"  [{year}] nietypowa struktura, pomijam ({e})")

    return playoffs, ok_years, unusual_years


# ---------------------------------------------------------------------------
# GŁÓWNA LOGIKA SKRYPTU
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Wczytujemy dane logowania ze zmiennych środowiskowych (jeśli są)
    swid = os.environ.get("SWID")
    espn_s2 = os.environ.get("ESPN_S2")

    # Słownik, który będzie przechowywał wyniki: klucz = rok (str), wartość = lista drużyn
    all_standings = {}
    # Licznik sukcesów – żeby na końcu poinformować użytkownika
    success_count = 0
    total_years = len(PRIVATE_YEARS) + len(PUBLIC_YEARS)

    # 2. Pobieramy dane dla lat prywatnych (2012–2018) – z autoryzacją
    if not swid or not espn_s2:
        print("[!] SWID i/lub ESPN_S2 nie ustawione – pomijam lata prywatne.")
        print("    Uruchom: SWID=\"...\" ESPN_S2=\"...\" python fetch_league.py\n")
    else:
        print("--- LATA PRYWATNE (2012–2018) – z autoryzacją ---")
        for year in PRIVATE_YEARS:
            try:
                teams = fetch_year_standings(LEAGUE_ID, year, swid=swid, espn_s2=espn_s2)
                all_standings[str(year)] = teams
                print(f"  [{year}] OK ({len(teams)} drużyn)")
                success_count += 1
            except Exception as e:
                # Wypisujemy pełny błąd – chcemy wiedzieć, co poszło nie tak
                print(f"  [{year}] BŁĄD: {e}")

    # 3. Pobieramy dane dla lat publicznych (2019–2025) – bez autoryzacji
    print("\n--- LATA PUBLICZNE (2019–2025) – bez autoryzacji ---")
    for year in PUBLIC_YEARS:
        try:
            teams = fetch_year_standings(LEAGUE_ID, year)
            all_standings[str(year)] = teams
            print(f"  [{year}] OK ({len(teams)} drużyn)")
            success_count += 1
        except Exception as e:
            print(f"  [{year}] BŁĄD: {e}")

    # 4. Pobieramy wyniki meczów tygodniowych – najpierw lata prywatne
    #    Słownik na wyniki meczów: rok -> tydzień -> lista meczów
    print("\n--- MECZE TYGODNIOWE (prywatne 2012–2018) ---")
    all_matchups = {}
    matchup_years_done = 0     # Licznik lat z powodzeniem

    if swid and espn_s2:
        for year in PRIVATE_YEARS:
            try:
                weeks = fetch_year_matchups(LEAGUE_ID, year, swid=swid, espn_s2=espn_s2)
                all_matchups[str(year)] = weeks
                # Liczymy drużyny z obiektu standings (już pobranego wcześniej)
                team_count = len(all_standings.get(str(year), []))
                week_count = len(weeks)
                print(f"  [{year}] OK ({week_count} tygodni, {team_count} drużyn)")
                matchup_years_done += 1
            except Exception as e:
                print(f"  [{year}] BŁĄD: {e}")
    else:
        print("[!] Pomijam – brak SWID/ESPN_S2.")

    # 5. Mecze tygodniowe dla lat publicznych (2019–2025)
    print("\n--- MECZE TYGODNIOWE (publiczne 2019–2025) ---")
    for year in PUBLIC_YEARS:
        try:
            weeks = fetch_year_matchups(LEAGUE_ID, year)
            all_matchups[str(year)] = weeks
            team_count = len(all_standings.get(str(year), []))
            week_count = len(weeks)
            print(f"  [{year}] OK ({week_count} tygodni, {team_count} drużyn)")
            matchup_years_done += 1
        except Exception as e:
            print(f"  [{year}] BŁĄD: {e}")

    # 6. Pobieramy składy drużyn (rostery) – najpierw lata prywatne z auth
    print("\n--- ROSTERY (prywatne 2012–2018) ---")
    all_rosters = {}
    roster_years_done = 0
    roster_total_years = len(PRIVATE_YEARS) + len(PUBLIC_YEARS) + 1  # +1 dla 2026

    # Dla lat prywatnych: każdy rok w osobnym try/except – błąd nie przerywa reszty
    if swid and espn_s2:
        for year in PRIVATE_YEARS:
            try:
                teams_rosters = fetch_year_rosters(LEAGUE_ID, year, swid=swid, espn_s2=espn_s2)
                # Liczymy drużyny i łączną liczbę zawodników we wszystkich rosterach
                team_count = len(teams_rosters)
                player_count = sum(len(t["players"]) for t in teams_rosters)
                all_rosters[str(year)] = teams_rosters
                if player_count == 0:
                    print(f"  [{year}] BRAK: brak zawodników w rosterach ({team_count} drużyn)")
                else:
                    print(f"  [{year}] OK ({team_count} drużyn, {player_count} zawodników razem)")
                    roster_years_done += 1
            except Exception as e:
                print(f"  [{year}] BRAK: {e}")
    else:
        print("[!] Pomijam – brak SWID/ESPN_S2.")

    # Rostery dla lat publicznych (2019–2025) – bez autoryzacji
    print("\n--- ROSTERY (publiczne 2019–2025) ---")
    for year in PUBLIC_YEARS:
        try:
            teams_rosters = fetch_year_rosters(LEAGUE_ID, year)
            team_count = len(teams_rosters)
            player_count = sum(len(t["players"]) for t in teams_rosters)
            all_rosters[str(year)] = teams_rosters
            if player_count == 0:
                print(f"  [{year}] BRAK: brak zawodników w rosterach ({team_count} drużyn)")
            else:
                print(f"  [{year}] OK ({team_count} drużyn, {player_count} zawodników razem)")
                roster_years_done += 1
        except Exception as e:
            print(f"  [{year}] BRAK: {e}")

    # Rok 2026 osobno – sezon może się jeszcze nie zacząć, roster bywa pusty
    print("\n--- ROSTERY (2026) ---")
    try:
        teams_rosters = fetch_year_rosters(LEAGUE_ID, 2026)
        team_count = len(teams_rosters)
        player_count = sum(len(t["players"]) for t in teams_rosters)
        all_rosters["2026"] = teams_rosters
        if player_count == 0:
            print(f"  [2026] BRAK: brak zawodników w rosterach ({team_count} drużyn)")
        else:
            print(f"  [2026] OK ({team_count} drużyn, {player_count} zawodników razem)")
            roster_years_done += 1
    except Exception as e:
        print(f"  [2026] BRAK: {e}")

    # 7. Pobieramy dane z draftu – prywatne 2012–2018 z auth
    #    Draft 2026 pomijamy – jeszcze się nie odbył
    print("\n--- DRAFT (prywatne 2012–2018) ---")
    all_drafts = {}
    draft_years_done = 0
    draft_total_years = len(PRIVATE_YEARS) + len(PUBLIC_YEARS)  # bez 2026

    if swid and espn_s2:
        for year in PRIVATE_YEARS:
            try:
                picks = fetch_year_draft(LEAGUE_ID, year, swid=swid, espn_s2=espn_s2)
                all_drafts[str(year)] = picks
                if not picks:
                    print(f"  [{year}] BRAK: brak danych draftu")
                else:
                    print(f"  [{year}] OK ({len(picks)} wyborów)")
                    draft_years_done += 1
            except Exception as e:
                print(f"  [{year}] BRAK: {e}")
    else:
        print("[!] Pomijam – brak SWID/ESPN_S2.")

    # Draft dla lat publicznych (2019–2025) – bez autoryzacji
    print("\n--- DRAFT (publiczne 2019–2025) ---")
    for year in PUBLIC_YEARS:
        try:
            picks = fetch_year_draft(LEAGUE_ID, year)
            all_drafts[str(year)] = picks
            if not picks:
                print(f"  [{year}] BRAK: brak danych draftu")
            else:
                print(f"  [{year}] OK ({len(picks)} wyborów)")
                draft_years_done += 1
        except Exception as e:
            print(f"  [{year}] BRAK: {e}")

    # 8. Budujemy drabinkę playoffów – surowe API ESPN (requests), bo
    #    espn-api nie udostępnia playoffTierType. Wykorzystuje JUŻ pobrane
    #    standings do mapowania teamId -> nazwy drużyn.
    print("\n--- PLAYOFFY (2012–2025) ---")
    all_playoffs, playoff_ok_years, playoff_unusual_years = build_playoffs(
        all_standings, swid=swid, espn_s2=espn_s2
    )
    print(f"Playoffy: {len(playoff_ok_years)}/{total_years} sezonów OK, "
          f"nietypowe: {playoff_unusual_years or 'brak'}")

    # 9. Zapisujemy wyniki do plików JSON w folderze data/
    #    Path("data") tworzy obiekt ścieżki – mkdir tworzy folder, jeśli nie istnieje
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)

    # Zapis tabeli wyników (standings)
    standings_path = output_dir / "standings.json"
    with open(standings_path, "w", encoding="utf-8") as f:
        json.dump(all_standings, f, indent=2, ensure_ascii=False)

    # Zapis meczów tygodniowych (matchups)
    matchups_path = output_dir / "matchups.json"
    with open(matchups_path, "w", encoding="utf-8") as f:
        json.dump(all_matchups, f, indent=2, ensure_ascii=False)

    # Zapis składów drużyn (rosters)
    rosters_path = output_dir / "rosters.json"
    with open(rosters_path, "w", encoding="utf-8") as f:
        json.dump(all_rosters, f, indent=2, ensure_ascii=False)

    # Zapis wyników draftu
    draft_path = output_dir / "draft.json"
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(all_drafts, f, indent=2, ensure_ascii=False)

    # Zapis historii franczyz (agregacja po stabilnym owner_id)
    franchises = build_franchises(all_standings)
    franchises_path = output_dir / "franchises.json"
    with open(franchises_path, "w", encoding="utf-8") as f:
        json.dump(franchises, f, indent=2, ensure_ascii=False)

    # Zapis drabinki playoffów (build_playoffs)
    playoffs_path = output_dir / "playoffs.json"
    with open(playoffs_path, "w", encoding="utf-8") as f:
        json.dump(all_playoffs, f, indent=2, ensure_ascii=False)

    # 10. Podsumowanie w konsoli
    print(f"\nZapisano standings:   {standings_path}")
    print(f"Zapisano matchups:    {matchups_path}")
    print(f"Zapisano rosters:     {rosters_path}")
    print(f"Zapisano draft:       {draft_path}")
    print(f"Zapisano franchises:  {franchises_path} ({len(franchises)} franczyz)")
    print(f"Zapisano playoffs:    {playoffs_path} ({len(playoff_ok_years)} sezonów z drabinką)")
    print(f"Tabele: {success_count}/{total_years} sezonów  |  Mecze: {matchup_years_done}/{total_years} sezonów  |  Rostery: {roster_years_done}/{roster_total_years} sezonów  |  Draft: {draft_years_done}/{draft_total_years} sezonów  |  Playoffy: {len(playoff_ok_years)}/{total_years} sezonów")
