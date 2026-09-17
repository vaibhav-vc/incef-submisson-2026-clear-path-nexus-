# Judge Demo: One Laptop, Any Device

The judge demo is a deliberately local, reproducible edition of EvidenceGate. It runs the web
app, API, PostgreSQL/PostGIS, and Redis on one laptop. Phones, tablets, and other laptops on the
same trusted Wi-Fi or Ethernet network can open the interface without installing anything.

This is an **offline-capable judging environment**, not a public deployment configuration. It
intentionally disables sign-in and live providers, so never run it on Vercel, Netlify, Firebase,
a public VM, a port-forwarded router, or untrusted public Wi-Fi. Only the web gateway is published
to the laptop. The nginx gateway alone joins a second bridge network for the published laptop/LAN
port; the API, database, and Redis have no published ports and remain on an externally isolated
Docker network.

## Prepare before judging day

1. Install and start Docker Desktop on Windows or macOS, or Docker Engine with the Compose plugin
   on Linux.
2. Connect to the internet once and run the launcher so Docker can download images and build the
   app.
3. Reboot the laptop, disconnect from the internet, and rehearse the explicit offline command.
   It uses `--no-build`, so it fails instead of attempting to retrieve a missing image.

## Start on Windows

Open PowerShell in the repository root and run:

```powershell
.\scripts\start_judge_demo.ps1
```

After that first successful online build, use the network-independent judging-day command:

```powershell
.\scripts\start_judge_demo.ps1 -Offline
```

## Start on macOS or Linux

```sh
chmod +x scripts/start_judge_demo.sh
./scripts/start_judge_demo.sh
```

After the initial build, use:

```sh
./scripts/start_judge_demo.sh --offline
```

The launcher waits for PostgreSQL, Redis, and the API, then exercises `/ready` and checks the
captured source file hashes through the same web gateway the judges will use. It prints URLs only
after that smoke test succeeds. Open one of the LAN URLs on a judge's device. If another device cannot
connect, allow the chosen port through the laptop firewall for **private networks only**. Do not
enable router port forwarding.

The default URL is `http://localhost:8080`. If that port is occupied, set `JUDGE_DEMO_PORT` before
running the launcher:

```powershell
$env:JUDGE_DEMO_PORT = '8090'
.\scripts\start_judge_demo.ps1
```

```sh
JUDGE_DEMO_PORT=8090 ./scripts/start_judge_demo.sh
```

`JUDGE_DEMO_BIND_ADDRESS` may be set to one specific IPv4 interface when the laptop has several
networks. Its default, `0.0.0.0`, listens on all of the laptop's IPv4 interfaces so LAN access
works without manual configuration.

## Persistence and generated secrets

PostgreSQL evidence is stored in the isolated `evidencegate-judge-real` Compose project's named data volume. Ordinary
stops, container rebuilds, and laptop reboots preserve it.

The launcher generates a new cryptographically random database password and session secret on
every invocation. Those values are passed through a temporary file and deleted after Compose
starts. On macOS and Linux that file is explicitly owner-readable only. No demo password is
committed to the repository.

The evidence-signing key is different: it must remain stable for as long as the saved evidence
exists, or earlier audit records could no longer be verified. The launcher therefore generates it
once per persistent judge dataset and keeps it in the git-ignored `.env.judge-real.state` file.
Treat that file and the judge data volume as one unit. Do not commit, share, rename, or edit
the state file manually.

## Stop without deleting evidence

The ordinary stop command needs values for Compose interpolation. The saved state provides the
stable values; temporary placeholders supply the two run-scoped values, which are irrelevant to
stopping containers.

### PowerShell

```powershell
$env:JUDGE_DEMO_POSTGRES_PASSWORD = 'stop-only-placeholder-value'
$env:JUDGE_DEMO_SESSION_SECRET = 'stop-only-placeholder-value'
docker compose --env-file .env.judge-real.state -f docker-compose.judge-demo.yml down
Remove-Item Env:JUDGE_DEMO_POSTGRES_PASSWORD, Env:JUDGE_DEMO_SESSION_SECRET
```

### macOS or Linux

```sh
JUDGE_DEMO_POSTGRES_PASSWORD=stop-only-placeholder-value \
JUDGE_DEMO_SESSION_SECRET=stop-only-placeholder-value \
docker compose --env-file .env.judge-real.state -f docker-compose.judge-demo.yml down
```

## Reset to a clean dataset

Reset is explicit because it destroys judge-demo evidence. It removes only this Compose project's
containers and named data volume, deletes its local signing state, generates fresh cryptographic
values, and creates a new empty local database. It does not remove unrelated Docker volumes or the older synthetic demo project's volume.

### PowerShell

```powershell
.\scripts\start_judge_demo.ps1 -Reset
```

### macOS or Linux

```sh
./scripts/start_judge_demo.sh --reset
```

## What this edition proves

- The complete application can start from a clean checkout with its database migrations.
- A pinned, real SNCF publisher capture is mounted read-only. The manifest bytes are checked against the Compose-pinned SHA-256, then every feed is checked against the manifest's SHA-256 and byte count before the launcher reports success. This detects changed local bytes; it is not a publisher digital signature.
- Synthetic corridor seeding is disabled and the real-data-only launch guard is active. The station list starts empty.
- Live-provider failures cannot be concealed by substituting generated data.
- Missing evidence produces `HOLD` or `UNAVAILABLE`; physical failures produce `HARD_BLOCKED`.
- The interface and API remain usable during an internet outage.
- Ordinary restarts retain both evidence data and the signing identity needed to verify it.

## Deliberate limitations

- `AUTH_DISABLED=true` is allowed only because the backend runs in development mode.
- Live weather, rail, AIS, GPS, event-engine, and ML-inference integrations are disabled.
- The recorded SNCF passenger feed was captured on 16 September 2026. It is French historical research data, not Indian Railways operational evidence, and is never called live at replay time.
- The source panel shows publisher, licence, capture time and feed checksums. Select **Inspect captured records** to decode the actual stops, trips, stop times, trip updates or alerts. Each table shows at most ten publisher rows and retains the original capture time and `REPLAYED_SNAPSHOT` classification. The first static-feed decode can take several seconds; later reads reuse a bounded preview after checking the captured bytes again. It does not import those bytes into operational route or assurance decisions.
- Without an authorized Indian timetable and engineering source, the offline edition cannot demonstrate a verified Indian corridor or a safe speed/dispatch recommendation.
- A high score cannot bypass a physical hard block or insufficient evidence.
- Anyone who can reach the LAN URL can use the demo; there is no judge-demo user account.

## Online deployment is a separate system

Never deploy `docker-compose.judge-demo.yml` to a public host. The online edition must use the
normal production deployment path with real Supabase authentication, HTTPS, non-demo evidence,
restricted hosts, independently managed secrets, backups, and monitoring.

Vercel, Netlify, and Firebase Hosting can serve a frontend. GitHub Actions can test and deploy it.
None of those services, by itself, provides the persistent FastAPI, PostgreSQL/PostGIS, and Redis
runtime this application requires, and none makes the unauthenticated judge edition safe to expose
to the public internet.
