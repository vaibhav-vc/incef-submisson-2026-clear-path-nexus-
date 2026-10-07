# India Rail AI

Planning automation for Indian Railways traffic control, built on open data:

1. **Data pipeline.** It ingests the open Indian Railways timetable (about 9,000 stations, 5,200 trains and 394,000 timed stops) into SQLite, with every source file's SHA-256 pinned.
2. **ML run-time model.** Gradient-boosted trees predict how many minutes a train needs between two stops, with a calibrated P10–P90 interval.
3. **Disruption planner.** When a train runs late, it spreads the delay through the network, finds trains that would come too close, and proposes priority-based holds to restore separation.
4. **Assistant.** Answers questions like "which trains run Delhi to Mumbai?" or "12002 is 30 minutes late at NDLS — what should we hold?" by calling all of the above. It's free by default: built-in offline, or a local open-source AI model.

**Cost: nothing.** The data is public domain (CC0) or open (ODbL). All code and libraries are open source. Everything runs on your own computer with no account, API key or subscription. The only paid option is the Claude assistant; it's off unless you choose it by name and use your own key.

## What "automation" means here

This automates the **planning work of a section controller**: noticing a knock-on conflict, choosing who waits, and working out the effect. Every plan comes back as `PROPOSED_FOR_CONTROLLER_REVIEW`. Nothing here connects to signalling, interlocking, Kavach or a locomotive. Those are safety-critical (SIL-4) systems that need RDSO/CRIS certification and authorised data feeds. The path from this prototype to field use is in [Next steps](#next-steps-towards-real-deployment).

## Quick start

```sh
cd india_rail_ai
pip install -r requirements.txt
python -m india_rail setup            # download + verify data (~100 MB), build DB, train model (~4 min)
python -m india_rail summary
python -m india_rail plan 12002 NDLS 30          # Shatabdi 30 min late at New Delhi
python -m india_rail slack 12951                 # where the Mumbai Rajdhani timetable has padding
python -m india_rail serve                       # HTTP API on http://127.0.0.1:8100/docs
python -m india_rail ask "trains from New Delhi to Howrah"     # free assistant
python -m india_rail ask "12002 is 30 min late at NDLS"
python -m india_rail ask                         # interactive session
```

Tests run offline on a hand-made three-station network: `python -m pytest -q`.

## Data

| Source | Contents | Licence | Status |
|---|---|---|---|
| [DataMeet `stations.json`](https://github.com/datameet/railways) | 8,990 stations with code, zone, state and coordinates | CC0 | Ingested, SHA-256 pinned |
| [DataMeet `trains.json`](https://github.com/datameet/railways) | 5,208 trains with type, zone, classes, distance and route geometry | CC0 | Ingested, SHA-256 pinned |
| [DataMeet `schedules.json`](https://github.com/datameet/railways) | 417,080 stop rows (arrival, departure, day) | CC0 | Ingested, SHA-256 pinned |
| OpenStreetMap `railway=rail` | Physical track geometry, gauge, electrification, track count, max speed | ODbL | Loader in `scripts/fetch_osm_tracks.py`. It needs Overpass access, which this build sandbox did not have |
| NTES / COA / FOIS / ICMS | Live running, control charts, freight, crew | Indian Railways (no open API) | Needs an authorised data-sharing agreement. Not scraped |

**Data quality**, from the ingest report:

- 443 duplicate stop listings were removed. Some trains appear twice under different row IDs, which would otherwise splice into a looping train.
- 22,508 untimed rows were dropped.
- 780 small backward clock steps (for example 08:30 followed by 08:29) were clamped rather than read as a 24-hour section.
- 1,220 rows disagree with the published `day` field. Spot checks show the published day is the faulty field: train 59298 increments its day at most stops within four hours.

The timetable is a **community snapshot from about 2016** with **no running-days field**, so every train is treated as daily. Station codes are from that era too (Mumbai Central is `BCT`, not `MMCT`).

## ML model: section run time

- **Target:** the scheduled minutes between consecutive timed points (383,192 sections, 5,184 trains).
- **Validation:** 5-fold `GroupKFold` with a train and its return working kept together, so every scored train is unseen during training.
- **No target leakage:** section averages are rebuilt inside each fold from the training trains only.
- **Method:**
  - Gradient-boosted trees learn the *difference* from the section's typical run time. Trees group each input into at most 255 bins, so they can't reproduce an exact typical value; learning only the correction avoids that.
  - P10 and P90 quantile models give the interval, checked with split-conformal calibration (CQR).

| Model (cross-validated) | Mean abs. error | Error on sections ≥10 min | Within 2 min |
|---|---|---|---|
| Speed by train type (baseline) | 2.57 min | 31.3% | 64.0% |
| Median of other trains on the same section (baseline) | 1.95 min | 24.9% | **80.4%** |
| Gradient boosting, new path | 1.87 min | 23.6% | 76.5% |
| **Gradient boosting, existing train** | **1.86 min** | **23.3%** | 76.6% |

- The P10–P90 interval covers **80.1%** of held-out sections against an 80% target, with a mean width of 5.4 minutes.
- **Honest read:**
  - Gradient boosting is 5% better than the strongest baseline on mean error and 28% better than speed-by-type.
  - The section median still gets more predictions within 2 minutes. It returns exact whole-minute values that many trains share, while the model trades those exact hits for fewer large misses.
  - The model learns **planned** run times. Delay prediction needs NTES-style actual running data, and no open source exists for that.
- Full metrics are in [`models/runtime_model_metrics.json`](models/runtime_model_metrics.json).

## Disruption planner

The planner works the way a controller does:

1. **Spread the delay.** It carries the delay along the late train's remaining route. On each section it recovers half of (scheduled time − the model's P10). At each halt it can shorten the stop down to 2 minutes.
2. **Check every section entry.** It compares the late train with every other train entering the same section. The separation it requires is `min(headway, the separation the published timetable already plans for that pair)`. The timetable is taken as feasible, so only gaps the disruption makes *worse* count as conflicts.
3. **Choose who waits.** The lower-priority train is held at the station before the section. The default ranking is Rajdhani/Shatabdi/Duronto, then SF/Garib Rath, then Mail/Express, then Passenger/MEMU; it's configurable. A held train is re-planned in turn, up to 30 trains.

Results from the real timetable (6-minute headway):

| Disruption | Conflicts | Trains held | Delay at destinations (sum) | Runtime |
|---|---|---|---|---|
| 12951 Mumbai Rajdhani, +20 min at BRC | 2 | 2 | 0.4 min | 0.5 s |
| 12002 Bhopal Shatabdi, +30 min at NDLS | 34 | 12 | 1.2 min | 1.9 s |
| 12259 Duronto, +60 min at SDAH | 87 | 27 | 43 min | 4.2 s |
| 12301 Howrah Rajdhani, +45 min at CNB | 342 | 29 | 205 min | 4.6 s |

Large delays on the Delhi–Howrah and Delhi–Mumbai trunk routes can cascade past the 30-train limit. Those cases are listed under `unresolved` rather than dropped. Because the planner chooses who waits one conflict at a time, it isn't an optimiser. A mixed-integer or constraint-programming re-scheduler is the natural next step once track-count and loop-line data are available.

## Assistant

All three assistants share the same nine read-only tools in `india_rail/tools.py`:
- train and station search;
- schedule, trains between stations, station board;
- busiest sections, fastest path;
- timetable slack;
- the disruption planner.

None of them can change anything; plans are proposals.

| Provider | Cost | Needs | Understands |
|---|---|---|---|
| `offline` | Free | Nothing | The common question types: delays/holds, trains between stations, fastest route, schedule, station board, busiest sections, slack, train/station search |
| `ollama` | Free | [Ollama](https://ollama.com) installed, then `ollama pull qwen2.5:7b` (about 5 GB; runs on a laptop CPU, faster with a GPU) | Free-form questions, with the model calling the tools itself |
| `claude` | **Paid** (Anthropic API, your own key) | `ANTHROPIC_API_KEY` | Free-form questions, strongest reasoning |

- `--provider auto` (the default) uses Ollama if it's running and the offline assistant otherwise. It never picks the paid option.
- Choose a different local model with `OLLAMA_MODEL=llama3.1:8b`.
- The HTTP API refuses `provider: "claude"` unless the server sets `INDIA_RAIL_ALLOW_PAID_ASSISTANT=1`, so nobody can run up charges on a shared server.
- The tests run the offline assistant on a miniature network and the Ollama and Claude tool loops against mocked servers.

## HTTP API

Run `python -m india_rail serve`; the endpoint docs are at `/docs`.

- `GET /health`
- `GET /trains/search?q=`, `/trains/{number}`, `/trains/{number}/slack`
- `GET /stations/search?q=`, `/stations/{code}/board`
- `GET /between?origin=&destination=`, `/sections/busiest`, `/path`
- `POST /plan/disruption`, `POST /assistant/ask`

## Next steps towards real deployment

1. **Authorised live data.** NTES running status and COA control charts through CRIS, plus running days and the current timetable (Trains at a Glance / ICMS).
2. **Track data.** Load OSM or, better, the Indian Railways engineering register: line count, loops and block sections. This enables single-line conflicts and overtaking at loops.
3. **Delay model.** Train on actual running data to predict delays, not just planned run times.
4. **Optimiser.** Replace the greedy holds with an optimiser that minimises weighted delay, then trial it in shadow mode beside a real control office, comparing its proposals with the controllers' decisions.
5. **Certification.** Any step that issues commands to trains or signals goes through RDSO safety certification and Kavach/EI integration by the authority. That is outside this software.

Data attribution: DataMeet (CC0). OpenStreetMap contributors (ODbL) when the OSM loader is used.
