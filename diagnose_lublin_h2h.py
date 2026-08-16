#!/usr/bin/env python3
"""JEDNORAZOWA DIAGNOSTYKA: bilans H2H Lublin Gnagare vs WSZYSCY przeciwnicy.

Łączy mecze z data/matchups.json (sezon zasadniczy) i data/playoffs.json.
Przeciwnika rozwiązuje przez owner_id z data/standings.json DLA DANEGO ROKU
(nazwa -> owner_id), z fallbackiem TEAM_NAME_ALIASES — ten sam mechanizm co
w fetch_league.py::build_franchises() (razem z MANUAL_OWNER_MERGES).

Ważne: od 2020 r. ESPN raportuje tygodnie playoffowe ZARÓWNO w matchups.json,
jak i w playoffs.json (te same gry, wyniki czasem różnią się o stat-korektę
<= ~1.0 pkt). Skrypt deduplikuje po (rok, para nazw, wyniki w tolerancji 1.5),
żeby nie liczyć meczów podwójnie.
"""
import json
from collections import defaultdict

DATA = "data"
LUBLIN_OWNER = "{4BF248FE-5037-4F2B-B248-FE50376F2B6B}"

# --- te same wyjątki co fetch_league.py::build_franchises() ---------------
MANUAL_OWNER_MERGES = {
    "{3AA0BC31-A484-4C48-A0BC-31A4843C4868}": "{4F1095CC-1DCD-427C-9095-CC1DCDE27C08}",
}
TEAM_NAME_ALIASES = {"Zambrow Bears": "Zambrów Bears"}
TOL = 2.5  # tolerancja wyniku przy deduplikacji (stat-korekty ESPN ~1-2 pkt)


def pl(n, one, few, many):
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def canon(name):
    return TEAM_NAME_ALIASES.get(name, name)


def merge_oid(oid):
    return MANUAL_OWNER_MERGES.get(oid, oid)


def load(path):
    with open(f"{DATA}/{path}", encoding="utf-8") as f:
        return json.load(f)


def collapse_ranges(pairs):
    """[(year, name)] chronologicznie -> '2013-2015 Kolberg Festung; 2016 Posen...'"""
    out, start, prev_y, prev_n = [], 0, 0, None
    for y, n in pairs:
        if prev_n == n and y == prev_y + 1:
            prev_y = y
            continue
        if prev_n is not None:
            out.append(f"{start if start == prev_y else f'{start}-{prev_y}'} {prev_n}")
        start, prev_y, prev_n = y, y, n
    if prev_n is not None:
        out.append(f"{start if start == prev_y else f'{start}-{prev_y}'} {prev_n}")
    return "; ".join(out)


standings = load("standings.json")
matchups = load("matchups.json")
playoffs = load("playoffs.json")
franchises = load("franchises.json")

name_by_owner = {f["owner_id"]: f["current_name"] for f in franchises}
years = sorted({int(y) for y in set(standings) | set(matchups) | set(playoffs)})

# 1) mapa nazwa -> owner_id per rok (nazwy zkanonizowane po aliasach)
year_map = {}
for y in years:
    m = {}
    for t in standings.get(str(y), []):
        if t.get("owner_id"):
            m[canon(t["team_name"])] = merge_oid(t["owner_id"])
    year_map[y] = m

# 2) gry z matchups.json i playoffs.json
match_games, playoff_games = [], []
max_week = {}  # rok -> najwyższy tydzień w matchups (0, gdy brak danych)
for y in years:
    sy = str(y)
    mw = 0
    for w, gs in matchups.get(sy, {}).items():
        w = int(w)
        mw = max(mw, w)
        for g in gs:
            match_games.append(dict(year=y, week=w, src="matchups",
                                    a=g["home_team"], sa=g["home_score"],
                                    b=g["away_team"], sb=g["away_score"]))
    max_week[y] = mw
    for r in playoffs.get(sy, {}).get("rounds", []):
        period = r["matchup_period"]
        for g in r["games"]:
            w = min(g.get("weeks") or [period])
            playoff_games.append(dict(year=y, week=int(w), period=period, src="playoffs",
                                      a=g["team_a"], sa=g["team_a_score"],
                                      b=g["team_b"], sb=g["team_b_score"]))

# 3) deduplikacja: gra playoffowa to duplikat tylko, gdy tydzień playoffowy
#    mieści się w zakresie matchups.json dla danego roku (lata 2020+: ESPN
#    raportuje bracket i tu, i tu), para nazw ta sama i wyniki w tolerancji
#    TOL (stat-korekty). Lata 2012-2019: playoffs są POZA zakresem matchups,
#    więc tam nic nie deduplikujemy.
deduped, kept = [], []
for pg in playoff_games:
    pair = {pg["a"], pg["b"]}
    ps = {pg["a"]: pg["sa"], pg["b"]: pg["sb"]}
    dup = None
    if pg["period"] <= max_week[pg["year"]]:
        for mg in match_games:
            if mg["year"] != pg["year"] or {mg["a"], mg["b"]} != pair:
                continue
            ms = {mg["a"]: mg["sa"], mg["b"]: mg["sb"]}
            if all(abs(ps[n] - ms[n]) <= TOL for n in pair):
                dup = mg
                break
    (deduped if dup else kept).append((pg, dup) if dup else pg)

games = match_games + kept

# 4) rozwiązywanie ownerów + filtrowanie meczów Lublina
unresolved = []
records = defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "g": 0, "names": set(),
                               "by_year": defaultdict(lambda: {"g": 0, "w": 0, "l": 0, "t": 0})})
name_history = defaultdict(lambda: defaultdict(set))  # opp_oid -> {year: {names}}
for g in games:
    oids = {}
    for nm, key in (("a", "a"), ("b", "b")):
        oid = year_map[g["year"]].get(canon(g[nm]))
        oids[key] = oid
        if oid is None:
            unresolved.append((g["year"], g["week"], g["src"], g[nm]))
    if LUBLIN_OWNER not in oids.values():
        continue
    if oids["a"] == LUBLIN_OWNER:
        ls, os_, opp_oid, opp_name = g["sa"], g["sb"], oids["b"], g["b"]
    else:
        ls, os_, opp_oid, opp_name = g["sb"], g["sa"], oids["a"], g["a"]
    if opp_oid is None:
        continue
    r = records[opp_oid]
    r["g"] += 1
    r["w"] += ls > os_
    r["l"] += ls < os_
    r["t"] += ls == os_
    r["names"].add(canon(opp_name))
    yr = r["by_year"][g["year"]]
    yr["g"] += 1
    yr["w"] += ls > os_
    yr["l"] += ls < os_
    yr["t"] += ls == os_
    name_history[opp_oid][g["year"]].add(canon(opp_name))

print("=" * 78)
print("LUBLIN GNAGARE — bilans H2H vs wszyscy przeciwnicy w historii")
print(f"owner_id: {LUBLIN_OWNER}  |  lata w danych: {years[0]}-{years[-1]}")
print("=" * 78)

print("\n--- BILANS WG PRZECIWNIKA (grupowanie po owner_id) ---")
for oid in sorted(records, key=lambda o: name_by_owner.get(o, o).lower()):
    r = records[oid]
    hist = sorted((y, n) for y, ns in name_history[oid].items() for n in ns)
    print(f"{name_by_owner.get(oid, '???'):<24} {r['w']:>3}-{r['l']:>2}-{r['t']:<2}"
          f" ({r['g']:>3} {pl(r['g'], 'gra', 'gry', 'gier')})   id={oid}")
    print(f"    nazwy w grach z Lublinem: {collapse_ranges(hist)}")

print("\n--- TEST KLUCZOWY: POZNAN FESTUNG (zmiany nazw) ---")
poz_oid = "{6ABD5EE7-E1A9-421B-BD5E-E7E1A9421BC9}"
r = records[poz_oid]
print(f"owner_id: {poz_oid}  ->  bilans vs Lublin: {r['w']}-{r['l']}-{r['t']} "
      f"({r['g']} {pl(r['g'], 'gra', 'gry', 'gier')})")
for y in sorted(name_history[poz_oid]):
    names = sorted(name_history[poz_oid][y])
    yr = r["by_year"][y]
    print(f"    {y}: {'/'.join(names):<24} {yr['g']:>2} {pl(yr['g'], 'gra', 'gry', 'gier')}"
          f" ({yr['w']}-{yr['l']}-{yr['t']})")
print(f"    UŻYTE NAZWY: {sorted(r['names'])}")
print(f"    Czy wszystkie (Kolberg/Posen/Mosina/Poznan) wpadły do JEDNEGO owner_id? "
      f"{'TAK' if len(r['names']) >= 3 else 'NIE — SPRAWDŹ'}")

print("\n--- SZCZEGÓŁY LAT Z PUSTYM matchups.json (tylko playoffs.json) ---")


def involves_lublin(g):
    return LUBLIN_OWNER in (year_map[g["year"]].get(canon(g["a"])),
                            year_map[g["year"]].get(canon(g["b"])))


for y in (2012, 2018):
    yr_games = [g for g in games if g["year"] == y]
    n_lub = sum(1 for g in yr_games if involves_lublin(g))
    print(f"  {y}: {len(yr_games)} gier w danych (matchups=0), w tym {n_lub} z udziałem Lublina")
    for g in sorted(yr_games, key=lambda g: g["week"]):
        print(f"    w{g['week']}: {g['a']} {g['sa']} vs {g['b']} {g['sb']} [{g['src']}]")

print("\n--- UZGODNIENIE LICZB (per rok, TYLKO mecze Lublina) ---")

min_po_year = {}
for y in years:
    min_po_year[y] = min((r["matchup_period"]
                          for r in playoffs.get(str(y), {}).get("rounds", [])),
                         default=None)

print(f"{'rok':<6}{'standings':>11}{'zas. w data':>11}{'bracket':>9}"
      f"{'playoff+':>9}{'duplikaty':>10}{'razem':>7}")
tot = {"g": 0, "std": 0, "kept": 0, "dup": 0, "bracket": 0, "missing": 0, "reg": 0}
for y in years:
    sy = str(y)
    lub = next((t for t in standings.get(sy, []) if t.get("owner_id") == LUBLIN_OWNER), None)
    n_std = lub["wins"] + lub["losses"] + lub["ties"] if lub else 0

    min_po = min_po_year[y]
    n_reg = sum(1 for g in match_games if g["year"] == y and involves_lublin(g)
                and (min_po is None or g["week"] < min_po))
    n_bracket = sum(1 for g in match_games if g["year"] == y and involves_lublin(g)
                    and min_po is not None and g["week"] >= min_po)
    n_kept = sum(1 for g in kept if g["year"] == y and involves_lublin(g))
    n_dup = sum(1 for pg, _ in deduped if pg["year"] == y and involves_lublin(pg))
    n_tot = n_reg + n_bracket + n_kept

    tot["g"] += n_tot
    tot["std"] += n_std
    tot["kept"] += n_kept
    tot["dup"] += n_dup
    tot["bracket"] += n_bracket
    tot["reg"] += n_reg
    missing = max(0, n_std - n_reg)
    tot["missing"] += missing

    wlt = f"{lub['wins']}-{lub['losses']}-{lub['ties']}" if lub else "B/D"
    notes = []
    if missing:
        notes.append(f"brakuje {missing} {pl(missing, 'gry', 'gier', 'gier')} "
                     f"zasadniczej (pusto w matchups.json)")
    if n_reg and n_reg != n_std:
        notes.append(f"NIEPASUJE: standings={n_std} vs zas. w danych={n_reg}")
    if n_bracket:
        notes.append(f"bracket w matchups (+{n_bracket})")
    print(f"{y:<6}{wlt:>8}({n_std:>2}){n_reg:>9}{n_bracket:>9}{n_kept:>9}"
          f"{n_dup:>10}{n_tot:>7}  {'; '.join(notes)}")
print("-" * 62)
print(f"{'SUMA':<6}{'':>8}({tot['std']:>2}){tot['reg']:>9}{tot['bracket']:>9}{tot['kept']:>9}"
      f"{tot['dup']:>10}{tot['g']:>7}")

# Bilans Lublina w playoffach (osobno, dla porównania ze standings)
pl_w = pl_l = pl_t = 0
for g in games:
    oa = year_map[g["year"]].get(canon(g["a"]))
    ob = year_map[g["year"]].get(canon(g["b"]))
    if LUBLIN_OWNER not in (oa, ob):
        continue
    if min_po_year[g["year"]] is None or g["week"] < min_po_year[g["year"]]:
        continue
    if oa == LUBLIN_OWNER:
        ls, os_ = g["sa"], g["sb"]
    else:
        ls, os_ = g["sb"], g["sa"]
    pl_w += ls > os_
    pl_l += ls < os_
    pl_t += ls == os_

print(f"\n  Lublin w standings (sezon zasadniczy, KOMPLET): {tot['std']}")
print(f"  Sezon zasadniczy policzony z danych:            "
      f"{tot['std'] - tot['missing']} (brakuje {tot['missing']}: 2012 i 2018)")
print(f"  Playoffy Lublina (unikalne):                    "
      f"{tot['kept'] + tot['bracket']} = {tot['kept']} z playoffs.json + "
      f"{tot['bracket']} bracket w matchups.json  |  bilans: {pl_w}-{pl_l}-{pl_t}")
print(f"  RAZEM w danych: {tot['g']}  (= {tot['std'] - tot['missing']} + "
      f"{tot['kept'] + tot['bracket']})")
print(f"  PEŁNY bilans (gdyby 2012/2018 miały matchups):  "
      f"{tot['std'] + tot['kept'] + tot['bracket']}")
print(f"  Suma H2H po przeciwnikach: {sum(r['g'] for r in records.values())} "
      f"{'== razem (OK)' if sum(r['g'] for r in records.values()) == tot['g'] else 'ROZJAZD!'}")

if deduped:
    print(f"\n--- DEDUPLIKACJA ({len(deduped)} {pl(len(deduped), 'duplikat', 'duplikaty', 'duplikatów')} "
          f"playoffy<->matchups; [L] = z udziałem Lublina) ---")
    for pg, mg in sorted(deduped, key=lambda d: (d[0]["year"], d[0]["week"])):
        lub = " [L]" if "Lublin Gnagare" in (pg["a"], pg["b"]) else ""
        print(f"  {pg['year']} w{pg['week']}: {pg['a']} {pg['sa']} vs {pg['b']} {pg['sb']}"
              f"  ==  matchups {mg['sa']}-{mg['sb']}{lub}")
else:
    print("\n(żadnych duplikatów playoffy<->matchups nie wykryto)")

if unresolved:
    print(f"\n--- NIEROZWIĄZANE NAZWY (brak w standings danego roku): {len(unresolved)} ---")
    for y, w, src, nm in unresolved:
        print(f"  {y} w{w} [{src}]: '{nm}'")
else:
    print("\n--- WSZYSTKIE NAZWY POPRAWNIE ROZWIĄZANE (brak nierozwiązanych) ---")
