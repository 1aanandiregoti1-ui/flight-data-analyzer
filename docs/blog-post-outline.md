# Blog post — outline and word budget

Target: 800–1,200 words, written for a smart friend who does not code. Publish anywhere that renders markdown (GitHub Pages, dev.to, Medium), then link it from the README and the README from it.

Fill in each section below. The word counts are a budget, not a rule.

## Hook (~100 words)

A specific thing you wondered about aircraft. Not "I did a data project" — the actual question. Example shape: *Every plane leaving JFK for Europe seems to turn north first. Are they going the long way?*

## The data (~200 words)

- What ADS-B is: every airliner broadcasts its position, altitude and speed roughly once a second, unencrypted.
- What OpenSky is: volunteers run cheap receivers; the network stitches what they hear into one feed.
- What one "state vector" contains, and the three things that surprised you (units are metric, almost every field can be null, a flight is not a row).

## The hard part (~250 words)

Pick **one** real problem and tell it honestly:

- Grouping position reports into flights — why `icao24` and not callsign, why a 30-minute gap, what went wrong the first time.
- Or nulls — 22% of altitude fields empty; why dropping rows would have been wrong.
- Or the API budget — credits, bounding boxes, the 429 that stopped a run.

## The finding (~350 words)

Two or three figures from `figures/`, each with one paragraph: what it shows, what number to look at, what surprised you. Lead with the flight-paths map. Say the detour-ratio result as a plain sentence with the sample size: *"Across n = ___ flights on ___, the median flight flew ___% further than the straight line."*

A negative result — "they mostly don't detour" — is a perfectly good finding if you say why.

## What I'd do differently (~150 words)

The three limitations from the README, in your own words, plus the one thing you would build next (pick from the blueprint's stretch goals).

## Links (~50 words)

- Repository
- OpenSky Network, cited as the README does
- Blueprint / anything else you leaned on
