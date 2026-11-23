#!/usr/bin/env python3
"""Rebuild names.json, the first-name -> % female lookup used by index.html.

Sources:
  1. US Social Security Administration baby names (public domain).
     Download https://www.ssa.gov/oact/babynames/names.zip and unzip it;
     pass the folder containing yob1940.txt ... yob2006.txt.
  2. Fallback for names not in SSA data: the international name dictionary
     shipped with the `gender-guesser` package (pip install gender-guesser),
     nam_dict.txt by Jorg Michael, GNU Free Documentation License 1.2+.

Usage:
  python3 scripts/build_names.py path/to/ssa_names_dir [--start 1940] [--end 2006] [--min 200]
Output format: {"s": {name: pct_female}, "g": {name: pct_female}}
"""
import argparse, collections, json, os

ap = argparse.ArgumentParser()
ap.add_argument("ssa_dir")
ap.add_argument("--start", type=int, default=1940, help="first birth year (default 1940)")
ap.add_argument("--end", type=int, default=2006, help="last birth year (default 2006)")
ap.add_argument("--min", type=int, default=200, help="minimum births for a name to be kept")
ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "names.json"))
a = ap.parse_args()

fem, tot = collections.Counter(), collections.Counter()
for y in range(a.start, a.end + 1):
    with open(os.path.join(a.ssa_dir, f"yob{y}.txt")) as fh:
        for line in fh:
            n, s, c = line.strip().split(",")
            n, c = n.lower(), int(c)
            tot[n] += c
            if s == "F":
                fem[n] += c
ssa = {n: round(100 * fem[n] / tot[n]) for n in tot if tot[n] >= a.min}

fallback = {}
try:
    import gender_guesser.detector as gg
    d = gg.Detector(case_sensitive=False)
    pct = {"male": 0, "female": 100, "mostly_male": 15, "mostly_female": 85, "andy": 50}
    for n in d.names:
        if n.isalpha() and n.lower() not in ssa:
            r = d.get_gender(n)
            if r in pct:
                fallback[n.lower()] = pct[r]
except ImportError:
    print("gender-guesser not installed; skipping international fallback")

with open(a.out, "w") as fh:
    json.dump({"s": ssa, "g": fallback}, fh, separators=(",", ":"))
print(f"wrote {a.out}: {len(ssa)} SSA names, {len(fallback)} fallback names")
