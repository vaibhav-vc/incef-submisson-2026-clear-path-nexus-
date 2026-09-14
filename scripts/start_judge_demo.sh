#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compose_file="$repo_root/docker-compose.judge-demo.yml"
state_file="$repo_root/.env.judge-demo.state"
runtime_file=''
reset=false
offline=false

cleanup() {
  if [ -n "$runtime_file" ] && [ -f "$runtime_file" ]; then
    rm -f -- "$runtime_file"
  fi
}
trap cleanup EXIT HUP INT TERM

while [ "$#" -gt 0 ]; do
  case "$1" in
    --reset) reset=true ;;
    --offline) offline=true ;;
    -h|--help)
      printf '%s\n' 'Usage: ./scripts/start_judge_demo.sh [--reset] [--offline]'
      exit 0
      ;;
    *)
      printf '%s\n' 'Usage: ./scripts/start_judge_demo.sh [--reset] [--offline]' >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Docker is required. Install and start Docker, then run this launcher again.' >&2
  exit 1
fi

random_hex() {
  byte_count=$1
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$byte_count"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets; print(secrets.token_hex($byte_count))"
  else
    printf '%s\n' 'OpenSSL or Python 3 is required to generate judge-demo secrets.' >&2
    exit 1
  fi
}

write_state() {
  old_umask=$(umask)
  umask 077
  {
    printf 'JUDGE_DEMO_EVIDENCE_SIGNING_KEY=%s\n' "$(random_hex 32)"
    printf 'JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID=judge-demo-%s\n' "$(random_hex 8)"
  } > "$state_file"
  umask "$old_umask"
}

read_state_value() {
  key=$1
  sed -n "s/^${key}=//p" "$state_file"
}

validate_ipv4() {
  address=$1
  old_ifs=$IFS
  IFS=.
  set -- $address
  IFS=$old_ifs
  [ "$#" -eq 4 ] || return 1
  for octet do
    case "$octet" in ''|*[!0-9]*) return 1 ;; esac
    [ "$octet" -le 255 ] || return 1
  done
}

port=${JUDGE_DEMO_PORT:-8080}
case "$port" in ''|*[!0-9]*)
  printf '%s\n' 'JUDGE_DEMO_PORT must be an integer from 1 through 65535.' >&2
  exit 1
esac
if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
  printf '%s\n' 'JUDGE_DEMO_PORT must be an integer from 1 through 65535.' >&2
  exit 1
fi

bind_address=${JUDGE_DEMO_BIND_ADDRESS:-0.0.0.0}
if ! validate_ipv4 "$bind_address"; then
  printf '%s\n' 'JUDGE_DEMO_BIND_ADDRESS must be an IPv4 address.' >&2
  exit 1
fi

docker compose version >/dev/null

if [ ! -f "$state_file" ]; then
  write_state
fi
evidence_key=$(read_state_value JUDGE_DEMO_EVIDENCE_SIGNING_KEY)
evidence_key_id=$(read_state_value JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID)
case "$evidence_key" in
  *[!a-f0-9]*|'') printf '%s\n' "Judge-demo state is invalid: $state_file" >&2; exit 1 ;;
esac
case "$evidence_key_id" in
  judge-demo-????????????????) ;;
  *) printf '%s\n' "Judge-demo state is invalid: $state_file" >&2; exit 1 ;;
esac
if [ "${#evidence_key}" -ne 64 ]; then
  printf '%s\n' "Judge-demo state is invalid: $state_file" >&2
  exit 1
fi

runtime_file=$(mktemp "${TMPDIR:-/tmp}/evidencegate-judge-demo.XXXXXX")
chmod 600 "$runtime_file"
write_runtime() {
  {
    printf 'JUDGE_DEMO_POSTGRES_PASSWORD=%s\n' "$(random_hex 32)"
    printf 'JUDGE_DEMO_SESSION_SECRET=%s\n' "$(random_hex 32)"
    printf 'JUDGE_DEMO_EVIDENCE_SIGNING_KEY=%s\n' "$evidence_key"
    printf 'JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID=%s\n' "$evidence_key_id"
    printf 'JUDGE_DEMO_BIND_ADDRESS=%s\n' "$bind_address"
    printf 'JUDGE_DEMO_PORT=%s\n' "$port"
  } > "$runtime_file"
}
write_runtime

if [ "$reset" = true ]; then
  printf '%s\n' 'Reset requested: removing only the EvidenceGate judge-demo containers and data volume.'
  docker compose --env-file "$runtime_file" -f "$compose_file" down --volumes --remove-orphans
  rm -f -- "$state_file"
  write_state
  evidence_key=$(read_state_value JUDGE_DEMO_EVIDENCE_SIGNING_KEY)
  evidence_key_id=$(read_state_value JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID)
  write_runtime
fi

if [ "$offline" = true ]; then
  docker compose --env-file "$runtime_file" -f "$compose_file" up --detach --wait --no-build
else
  docker compose --env-file "$runtime_file" -f "$compose_file" up --build --detach --wait
fi
docker compose --env-file "$runtime_file" -f "$compose_file" exec -T backend \
  python -c "import json,urllib.request; ready=json.load(urllib.request.urlopen('http://frontend:5173/ready',timeout=5)); stations=json.load(urllib.request.urlopen('http://frontend:5173/api/v1/planner/stations',timeout=10)); assert ready.get('status')=='ready' and isinstance(stations,list) and stations"

printf '\nEvidenceGate is ready on this computer: http://localhost:%s\n' "$port"
lan_addresses=''
if command -v hostname >/dev/null 2>&1; then
  lan_addresses=$(hostname -I 2>/dev/null || true)
fi
if [ -n "$lan_addresses" ]; then
  printf '%s\n' 'Judges on the same trusted Wi-Fi or Ethernet network can open:'
  for address in $lan_addresses; do
    case "$address" in 127.*|169.254.*) continue ;; esac
    printf '  http://%s:%s\n' "$address" "$port"
  done
fi
printf '%s\n' 'Use this LAN mode only on a trusted local network; it intentionally has no sign-in.'
printf '%s\n' 'Data persists across ordinary stops and restarts.'
printf '%s\n' 'See docs/JUDGE_DEMO.md for the stop command.'
printf '%s\n' 'Reset only its saved data and signing identity with: ./scripts/start_judge_demo.sh --reset'
printf '%s\n' 'After the initial build, use --offline on judging day to forbid rebuilding.'
