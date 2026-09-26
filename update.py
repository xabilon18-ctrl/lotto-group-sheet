"""Add new draws to data.json.

Runs once a day from GitHub Actions. It only ever appends draws newer than the
last one stored for each game, and only when the numbers pass validation and,
where a second source exists, the sources agree. Anything doubtful is skipped
and retried on the next run, so a bad scrape never overwrites good data.
"""
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

DATA = Path(__file__).with_name("data.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; lotto-group-sheet updater)"}
MONTHS = "January February March April May June July August September October November December".split()


def get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:  # a dead source just means fewer confirmations
        print(f"  ! {url}: {e}")
        return ""


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def rows(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    return [[clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)]
            for tr in re.findall(r"<tr.*?</tr>", page, flags=re.S)]


def pdate(s):
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)? (%s) (20\d\d)" % "|".join(MONTHS), s)
    return dt.date(int(m[3]), MONTHS.index(m[2]) + 1, int(m[1])) if m else None


def ints(s):
    return [int(x) for x in re.findall(r"\d+", s)]


def split_bonus(s):
    p = re.split(r"Bonus Ball:|PB ?:", s)
    return ints(p[0]), (ints(p[1])[0] if len(p) > 1 and ints(p[1]) else None)


# ---------- sources ----------
def natlot(game, year):
    """za.national-lottery.com archive: main numbers (+ bonus / PowerBall)."""
    out = {}
    for c in rows(get(f"https://za.national-lottery.com/{game}/results/{year}-archive")):
        r = " ".join(c)
        d = pdate(r)
        if d:
            out[d] = ints(r.split(str(year), 1)[1].split("R")[0])
    return out


def prt(path, year):
    """powerballresultstoday.co.za yearly tables: main + Plus games."""
    out = {}
    for c in rows(get(f"https://www.powerballresultstoday.co.za/{path}-{year}/")):
        d = pdate(c[0]) if c else None
        if d and len(c) > 1 and re.search(r"[1-9]", c[1]):
            out[d] = c[1:]
    return out


def pbnet(year):
    t = clean(re.sub(r"<script.*?</script>", "", get(f"https://www.powerball.net/southafrica/results/history/{year}"), flags=re.S))
    pat = r"(\d{1,2} \w+ %d) PowerBall ((?:\d+ ){5})(\d+) PowerBall PowerBall XTRA ((?:\d+ ){5})(\d+)" % year
    return {pdate(m[0]): (ints(m[1]), int(m[2]), ints(m[3]), int(m[4])) for m in re.findall(pat, t)}


def uk49(name, year):
    out = {}
    for c in rows(get(f"https://uk.lottonumbers.com/uk49s-{name}/results/{year}")):
        r = " ".join(c)
        d = pdate(r)
        if d:
            n = ints(r.split(str(year), 1)[1])
            if len(n) == 7:
                out[d] = n
    return out


# ---------- merge ----------
def valid(nums, k, top):
    return len(nums) == k and len(set(nums)) == k and all(1 <= x <= top for x in nums)


def collect(year):
    """Return {game_key: {date: (sorted_main, bonus)}} of confirmed draws for one year."""
    got = {k: {} for k in ("lotto", "lp1", "lp2", "pb", "pbp", "dl", "dlp", "lunch", "tea")}

    # Lotto: national-lottery.com main; Plus 1/2 from the second site when its main numbers agree
    nl, pl = natlot("lotto", year), prt("lotto/lotto-results", year)
    for d, n in nl.items():
        main, bonus = n[:6], (n[6] if len(n) > 6 else None)
        if not valid(main, 6, 58):
            continue
        got["lotto"][d] = (sorted(main), bonus)
        for dd in (d, d - dt.timedelta(1), d + dt.timedelta(1)):  # the sites sometimes date a draw a day apart
            if dd in pl and len(pl[dd]) >= 5:
                m2, _ = split_bonus(pl[dd][0])
                if sorted(m2) == sorted(main):
                    for key, col in (("lp1", 2), ("lp2", 4)):
                        pm, pb = split_bonus(pl[dd][col]) if len(pl[dd]) > col else ([], None)
                        if valid(pm, 6, 58):
                            got[key][d] = (sorted(pm), pb)
                break

    # PowerBall: need 2 of 3 sources to agree on the main draw
    nl, pn, pr = natlot("powerball", year), pbnet(year), prt("powerball/powerball-results", year)
    for d in set(nl) | set(pn) | set(pr):
        votes = []
        if d in nl and len(nl[d]) >= 6:
            votes.append((tuple(sorted(nl[d][:5])), nl[d][5]))
        if d in pn:
            votes.append((tuple(sorted(pn[d][0])), pn[d][1]))
        if d in pr:
            m, b = split_bonus(pr[d][0])
            votes.append((tuple(sorted(m)), b))
        best = max(set(votes), key=votes.count) if votes else None
        if best and votes.count(best) >= 2 and valid(list(best[0]), 5, 50):
            got["pb"][d] = (list(best[0]), best[1])
            plus = []
            if d in pn:
                plus.append((tuple(sorted(pn[d][2])), pn[d][3]))
            if d in pr and len(pr[d]) > 2:
                m, b = split_bonus(pr[d][2])
                plus.append((tuple(sorted(m)), b))
            if plus and (len(plus) == 1 or plus[0] == plus[1]) and valid(list(plus[0][0]), 5, 50):
                got["pbp"][d] = (list(plus[0][0]), plus[0][1])

    # Daily Lotto: national-lottery.com, skipped if the second site disagrees;
    # Daily Lotto Plus only from the second site, and only when its main numbers agree
    nl, pr = natlot("daily-lotto", year), prt("daily-lotto/daily-lotto-results", year)
    for d, n in nl.items():
        main = sorted(n[:5])
        if not valid(main, 5, 36):
            continue
        agrees = d in pr and sorted(ints(pr[d][0])[:5]) == main
        if d in pr and not agrees:
            print(f"  ? Daily Lotto {d}: sources disagree, skipped")
            continue
        got["dl"][d] = (main, None)
        if agrees and len(pr[d]) > 2 and valid(ints(pr[d][2]), 5, 36):
            got["dlp"][d] = (sorted(ints(pr[d][2])), None)

    # UK49s: one source, strict validation (6 distinct + booster)
    for key, name in (("lunch", "lunchtime"), ("tea", "teatime")):
        for d, n in uk49(name, year).items():
            if valid(n[:6], 6, 49) and 1 <= n[6] <= 49 and n[6] not in n[:6]:
                got[key][d] = (sorted(n[:6]), n[6])
    return got


def main():
    data = json.loads(DATA.read_text())
    today = dt.date.today()
    years = {today.year} | ({today.year - 1} if today.month == 1 else set())
    fresh = {}
    for y in sorted(years):
        for k, v in collect(y).items():
            fresh.setdefault(k, {}).update(v)

    added = 0
    for g in data["games"]:
        last = dt.date.fromisoformat(g["draws"][-1][0])
        new = sorted(d for d in fresh.get(g["key"], {}) if last < d <= today)
        for d in new:
            main, bonus = fresh[g["key"]][d]
            g["draws"].append([d.isoformat(), main, bonus])
            print(f"  + {g['name']} {d} {main} {bonus if bonus is not None else ''}")
        added += len(new)

    if added:
        data["updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        DATA.write_text(json.dumps(data, separators=(",", ":")))
    print(f"{added} new draw(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
