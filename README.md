# Lotto Group Sheet

A school project that maps South African Lotto, PowerBall, Daily Lotto and UK49s draws onto a 40-group number sheet (group *n* = *n*, *n*+4, *n*+15, *n*+23, *n*+36) and tests every pattern against the numbers themselves.

- `index.html`: the app (tabs: Predictions, Sheet, Groups, Patterns, Moon & stars, Formula lab)
- `data.json`: every 2026 draw, updated automatically
- `update.py`: fetches new draws, cross-checks them between results sites, and only appends confirmed ones
- `.github/workflows/update.yml`: runs the update every evening and early morning, then republishes the site

Results come from unofficial results sites. Check any ticket against the official National Lottery site before claiming.
