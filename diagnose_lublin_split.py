#!/usr/bin/env python3
"""JEDNORAZOWA DIAGNOSTYKA: bilans H2H Lublin Gnagare ROZDZIELONY na
SEZON ZASADNICZY vs PLAYOFFY, z niezależną weryfikacją obu sum.

Dwa niezależne zestawienia per przeciwnik:
  regular_season: TYLKO data/matchups.json — tygodnie zasadnicze
                  (tygodnie bracketowe z matchups pokazujemy OSOBNO,
                  bez żadnej deduplikacji — to osobny problem).
  playoffs:       TYLKO data/playoffs.json — wszystkie rundy, bez
                  patrzenia na matchups.json.

Następnie weryfikacja:
  - czy Σ regular_season == 173 (wiemy: 173 z 197 gier zasadniczych,
    brakuje 24 z 2012+2018),
  - czy Σ playoffs == 25 gier / 14-10-1 (poprzednia analiza: 19 z
    playoffs.json + 6 bracket w matchups = 25) — czyli czy playoffs.json
    SAM W SOBIE jest kompletny,
  - czy suma obu == 198 (znany łączny bilans 89-107-2).

Mechanizm rozwiązywania nazw: ten sam co w fetch_league.py
(TEAM_NAME_ALIASES + MANUAL_OWNER_MERGES, mapa nazwa->owner_id per rok).
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


def canon(name):
    return TEAM_NAME_ALIASES.get(name, name)


def merge_oid(oid):
    return MANUAL_OWNER_MERGES.get(oid, oid)


def load(path):
    with open(f"{DATA}/{path}", encoding="utf-8") as f:
        return json.load(f)


def pl(n, one, few, many):
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def rec():
    return {"w": 0, "l": 0, "t": 0, "g": 0}


standings = load("standings.json")
matchups = load("matchups.json")
playoffs = load("playoffs.json")
franchises = load("franchises.json")

name_by_owner = {f["owner_id"]: f["current_name"] for f in franchises}
years = sorted({int(y) for y in set(standings) | set(matchups) | set(playoffs)})

# mapa nazwa -> owner_id per rok (kanonizacja aliasów)
year_map = {}
for y in years:
    m = {}
    for t in standings.get(str(y), []):
        if t.get("owner_id"):
            m[canon(t["team_name"])] = merge_oid(t["owner_id"])
    year_map[y] = m

# start playoffów per rok (z playoffs.json — tylko jako KALENDARZ tygodni,
# nie jako źródło gier). 2022: brak rund -> wszystkie tygodnie zasadnicze.
min_po = {}
for y in years:
    min_po[y] = min((r["matchup_period"]
                     for r in playoffs.get(str(y), {}).get("rounds", [])),
                    default=None)


def oid_of(g, side):
    return year_map[g["year"]].get(canon(g[side]))


def outcome(g, lublin_side):
    """Wynik z perspektywy Lublina: 'w'/'l'/'t'."""
    if lublin_side == "a":
        ls, os_ = g["sa"], g["sb"]
    else:
        ls, os_ = g["sb"], g["sa"]
    return "w" if ls > os_ else "l" if ls < os_ else "t"


reg_records = defaultdict(rec)          # opp_oid -> bilans ZASADNICZY
po_records = defaultdict(rec)           # opp_oid -> bilans PLAYOFFOWY
bracket_games = []                      # mecze Lublina z bracketowych tygodni matchups
po_lublin = []                          # mecze Lublina z playoffs.json (rok, tydzień, para)
unresolved = []

# --- SEZON ZASADNICZY: TYLKO matchups.json --------------------------------
for y in years:
    for w, gs in matchups.get(str(y), {}).items():
        for g in gs:
            ga = dict(year=y, week=int(w), a=g["home_team"], sa=g["home_score"],
                      b=g["away_team"], sb=g["away_score"])
            a_oid, b_oid = oid_of(ga, "a"), oid_of(ga, "b")
            for nm, oid in ((ga["a"], a_oid), (ga["b"], b_oid)):
                if oid is None:
                    unresolved.append((y, w, "matchups", nm))
            if LUBLIN_OWNER not in (a_oid, b_oid):
                continue
            lub_side = "a" if a_oid == LUBLIN_OWNER else "b"
            opp_oid = b_oid if lub_side == "a" else a_oid
            if opp_oid is None:
                continue
            if min_po[y] is None or ga["week"] < min_po[y]:
                r = reg_records[opp_oid]
                r["g"] += 1
                r[outcome(ga, lub_side)] += 1
            else:
                bracket_games.append(ga)  # OSOBNO — nie wchodzi do bilansu zasadniczego

# --- PLAYOFFY: TYLKO playoffs.json ----------------------------------------
for y in years:
    for rnd in playoffs.get(str(y), {}).get("rounds", []):
        for g in rnd["games"]:
            gp = dict(year=y, week=min(g.get("weeks") or [rnd["matchup_period"]]),
                      a=g["team_a"], sa=g["team_a_score"],
                      b=g["team_b"], sb=g["team_b_score"])
            a_oid, b_oid = oid_of(gp, "a"), oid_of(gp, "b")
            for nm, oid in ((gp["a"], a_oid), (gp["b"], b_oid)):
                if oid is None:
                    unresolved.append((y, gp["week"], "playoffs", nm))
            if LUBLIN_OWNER not in (a_oid, b_oid):
                continue
            lub_side = "a" if a_oid == LUBLIN_OWNER else "b"
            opp_oid = b_oid if lub_side == "a" else a_oid
            if opp_oid is None:
                continue
            po_lublin.append(gp)
            r = po_records[opp_oid]
            r["g"] += 1
            r[outcome(gp, lub_side)] += 1

# --- ZESTAWIENIE PER PRZECIWNIK (dwie osobne kolumny) ---------------------
all_opps = sorted(set(reg_records) | set(po_records),
                  key=lambda o: name_by_owner.get(o, o).lower())
print("=" * 74)
print("LUBLIN GNAGARE — bilans H2H ROZDZIELONY: sezon zasadniczy vs playoffy")
print("=" * 74)
print(f"{'przeciwnik':<24}{'SEZON ZAS.':>22}{'PLAYOFFY':>20}")
print(f"{'':24}{'W-L-T':>13}{'gry':>9}{'W-L-T':>13}{'gry':>7}")
s_w = s_l = s_t = s_g = p_w = p_l = p_t = p_g = 0
for oid in all_opps:
    rr, pr = reg_records[oid], po_records[oid]
    s_w += rr["w"]; s_l += rr["l"]; s_t += rr["t"]; s_g += rr["g"]
    p_w += pr["w"]; p_l += pr["l"]; p_t += pr["t"]; p_g += pr["g"]
    name = name_by_owner.get(oid, "???")
    reg_s = f"{rr['w']}-{rr['l']}-{rr['t']}" if rr["g"] else "-"
    po_s = f"{pr['w']}-{pr['l']}-{pr['t']}" if pr["g"] else "-"
    reg_g = str(rr["g"]) if rr["g"] else "-"
    po_g = str(pr["g"]) if pr["g"] else "-"
    print(f"{name:<24}{reg_s:>13}{reg_g:>9}{po_s:>13}{po_g:>7}")
print("-" * 74)
print(f"{'SUMY':<24}{s_w}-{s_l}-{s_t} {s_g} gier | {p_w}-{p_l}-{p_t} {p_g} gier")

# --- WERYFIKACJA NIEZALEŻNA ----------------------------------------------
print("\n--- WERYFIKACJA: SEZON ZASADNICZY (matchups.json, tygodnie zasadnicze) ---")
print(f"  Σ regular_season = {s_w}-{s_l}-{s_t}, {s_g} {pl(s_g, 'gra', 'gry', 'gier')}")
print(f"  OCZEKIWANE: 75-97-1, 173 gry  ->  "
      f"{'OK' if (s_w, s_l, s_t, s_g) == (75, 97, 1, 173) else 'ROZJAZD!'}")

print("\n--- WERYFIKACJA: PLAYOFFY (TYLKO playoffs.json, matchups pominięte) ---")
print(f"  Σ playoffs = {p_w}-{p_l}-{p_t}, {p_g} {pl(p_g, 'gra', 'gry', 'gier')}")
print(f"  OCZEKIWANE (poprzednia analiza: 19 + 6 bracket = 25, 14-10-1):  "
      f"{'OK' if (p_w, p_l, p_t, p_g) == (14, 10, 1, 25) else 'INACZEJ!'}")
print(f"  -> playoffs.json sam w sobie: "
      f"{'KOMPLETNY' if p_g == 25 else f'NIEKOMPLETNY (ma tylko {p_g} gier)'}")
print(f"  Per rok (gry Lublina w playoffs.json):")
by_year = defaultdict(int)
for g in po_lublin:
    by_year[g["year"]] += 1
print("    " + "  ".join(f"{y}:{by_year.get(y, 0)}" for y in years))

print("\n--- GRY BRACKETOWE W matchups.json (OSOBNO, poza bilansem) ---")
print(f"  Razem: {len(bracket_games)} gier. Każda ma bliźniaka w playoffs.json?")
b_match, b_no_match = [], []
for g in bracket_games:
    pair = {g["a"], g["b"]}
    twin = next((pg for pg in po_lublin
                 if pg["year"] == g["year"] and {pg["a"], pg["b"]} == pair), None)
    (b_match if twin else b_no_match).append((g, twin))
for g, twin in sorted(b_match, key=lambda t: (t[0]["year"], t[0]["week"])):
    print(f"  {g['year']} w{g['week']}: {g['a']} {g['sa']} vs {g['b']} {g['sb']}"
          f"  <->  playoffs.json: {twin['a']} {twin['sa']} vs {twin['b']} {twin['sb']}")
for g, _ in b_no_match:
    print(f"  {g['year']} w{g['week']}: {g['a']} vs {g['b']}  -> BRAK bliźniaka w playoffs.json!")
print(f"  Wniosek: te {len(b_match)} gier to DUPLIKATY meczów z playoffs.json "
      f"(stat-korekty różnicują wyniki o ~1-2 pkt); "
      f"{'nic nie trzeba dokładać z matchups' if not b_no_match else 'UWAGA: są gry bez bliźniaka'}")

print("\n--- WERYFIKACJA: SUMA OBU ŹRÓDEŁ ---")
print(f"  {s_w}-{s_l}-{s_t} ({s_g}) + {p_w}-{p_l}-{p_t} ({p_g}) = "
      f"{s_w + p_w}-{s_l + p_l}-{s_t + p_t} ({s_g + p_g})")
print(f"  OCZEKIWANE: 89-107-2, 198 gier  ->  "
      f"{'OK' if (s_w + p_w, s_l + p_l, s_t + p_t, s_g + p_g) == (89, 107, 2, 198) else 'ROZJAZD!'}")
print(f"  (standings 89-106-2 z 197 gier - 14-9-1 z 2012/2018 + playoffy 14-10-1"
      f" = 89-107-2 z 198)")

if unresolved:
    print(f"\n--- NIEROZWIĄZANE NAZWY: {len(unresolved)} ---")
    for y, w, src, nm in unresolved:
        print(f"  {y} w{w} [{src}]: '{nm}'")
else:
    print("\n--- WSZYSTKIE NAZWY POPRAWNIE ROZWIĄZANE ---")
