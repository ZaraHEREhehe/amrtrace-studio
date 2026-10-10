#!/usr/bin/env bash
# Z-12: Roll back the running API + web to the last verified GHCR image tag.
# Manual use: sudo /usr/local/sbin/amrtrace-z12-rollback --check
#             sudo /usr/local/sbin/amrtrace-z12-rollback --apply
set -Eeuo pipefail
umask 077

ROOT=/opt/amrtrace-studio
COMPOSE="$ROOT/compose.ghcr.yml"
CURRENT="$ROOT/image.env"
LAST_GOOD="$ROOT/image.last-good.env"
PREFIX=ghcr.io/zaraherehehe/amrtrace-studio
URL=http://127.0.0.1:8080

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: Run using sudo." >&2
  exit 1
fi
if [[ $# -ne 1 || ( "$1" != "--check" && "$1" != "--apply" ) ]]; then
  echo "Usage: sudo $0 --check|--apply" >&2
  exit 2
fi

for file in "$COMPOSE" "$CURRENT" "$LAST_GOOD" "$ROOT/runtime.env"; do
  [[ -f "$file" ]] || { echo "ERROR: Missing $file" >&2; exit 1; }
done

exec 9>/run/lock/amrtrace-z12-deploy.lock
flock -n 9 || { echo "ERROR: Deployment already in progress; retry later." >&2; exit 1; }

old_tag="$(sed -n 's/^AMRTRACE_IMAGE_TAG=//p' "$LAST_GOOD")"
active_tag="$(sed -n 's/^AMRTRACE_IMAGE_TAG=//p' "$CURRENT")"
[[ "$old_tag" =~ ^sha-[0-9a-f]{40}$ ]] || { echo "ERROR: Invalid last-good tag." >&2; exit 1; }
[[ "$active_tag" =~ ^sha-[0-9a-f]{40}$ ]] || { echo "ERROR: Invalid active tag." >&2; exit 1; }

for service in api web; do
  docker image inspect "$PREFIX-$service:$old_tag" >/dev/null ||
    { echo "ERROR: Missing local last-good image for $service. No changes made." >&2; exit 1; }
done

echo "ACTIVE_TAG=$active_tag"
echo "LAST_GOOD_TAG=$old_tag"
if [[ "$1" == "--check" ]]; then
  echo "ROLLBACK_READY"
  exit 0
fi

# Hold a recoverable copy of the original pointer while applying last-good.
original="$(mktemp "$ROOT/.image-before-rollback.XXXXXXXX")"
trap 'rm -f "$original"' EXIT
cp "$CURRENT" "$original"
install -m 600 "$LAST_GOOD" "$CURRENT"

compose_up() {
  docker compose --env-file "$CURRENT" -f "$COMPOSE" up -d --no-build --pull never --force-recreate
}
check_health() {
  for attempt in {1..18}; do
    if curl -fsS -o /dev/null --max-time 10 "$URL/" &&
       curl -fsS -o /dev/null --max-time 10 "$URL/api/health" &&
       curl -fsS -o /dev/null --max-time 30 "$URL/api/cases?limit=1"; then
      return 0
    fi
    sleep 5
  done
  return 1
}
if compose_up && check_health; then
  echo "ROLLBACK_REDEPLOY_VERIFIED=$old_tag"
  exit 0
fi

echo "ROLLBACK_REDEPLOY_FAILED: Attempting to restore original image tag." >&2
install -m 600 "$original" "$CURRENT"
compose_up || true
check_health || true
exit 1
