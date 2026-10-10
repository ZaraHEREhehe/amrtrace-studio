#!/usr/bin/env bash
# Z-12: Poll the reviewed main branch and deploy only complete GHCR image pairs.
# Install this as a root-owned file; run from a systemd timer (not a GitHub runner).
set -Eeuo pipefail
umask 077

ROOT=/opt/amrtrace-studio
COMPOSE="$ROOT/compose.ghcr.yml"
CURRENT="$ROOT/image.env"
LAST_GOOD="$ROOT/image.last-good.env"
BASELINE="$ROOT/main.baseline"
FAILED="$ROOT/main.failed"
REPO=https://github.com/ZaraHEREhehe/amrtrace-studio.git
IMAGE_PREFIX=ghcr.io/zaraherehehe/amrtrace-studio
URL=http://127.0.0.1:8080

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: Run as root (sudo)." >&2
  exit 1
fi
for file in "$COMPOSE" "$CURRENT" "$LAST_GOOD" "$BASELINE" "$ROOT/runtime.env"; do
  if [[ ! -f "$file" ]]; then
    echo "ERROR: Missing required file: $file" >&2
    exit 1
  fi
done

# Prevent overlapping deployments, including long image downloads.
exec 9>/run/lock/amrtrace-z12-deploy.lock
if ! flock -n 9; then
  echo "DEPLOY_SKIPPED: Another deployment is running."
  exit 0
fi

remote="$(timeout 30 git ls-remote "$REPO" refs/heads/main)"
main_sha="${remote%%[[:space:]]*}"
if [[ ! "$main_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: Cannot determine current main commit." >&2
  exit 1
fi
baseline="$(tr -d '\r\n' < "$BASELINE")"
current_tag="$(sed -n 's/^AMRTRACE_IMAGE_TAG=//p' "$CURRENT")"
if [[ -z "$current_tag" ]]; then
  echo "ERROR: Missing current image tag." >&2
  exit 1
fi

# Harmless status check before enabling the timer.
if [[ "${1:-}" == "--check" ]]; then
  echo "DEPLOY_CHECK_OK"
  echo "MAIN_BASELINE=$baseline"
  echo "MAIN_REMOTE=$main_sha"
  echo "ACTIVE_IMAGE_TAG=$current_tag"
  exit 0
fi
if [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--check]" >&2
  exit 2
fi
if [[ "$main_sha" == "$baseline" ]]; then
  echo "NO_CHANGE: main is unchanged."
  exit 0
fi
if [[ -f "$FAILED" && "$(cat "$FAILED")" == "$main_sha" ]]; then
  echo "DEPLOY_SKIPPED: This main commit previously failed health checks; review before retrying."
  exit 0
fi

new_tag="sha-$main_sha"
echo "DEPLOY_CANDIDATE=$new_tag"

# Wait for BOTH jobs in GitHub Actions to publish the exact same commit.
# Pulling images alone never changes the live containers.
for service in api web; do
  if ! timeout 180 docker pull "$IMAGE_PREFIX-$service:$new_tag"; then
    echo "IMAGES_PENDING: $service image not yet available; retry at next scheduled check."
    exit 0
  fi
done

compose_up() {
  docker compose --env-file "$CURRENT" -f "$COMPOSE" up -d --no-build --pull never --force-recreate
}
healthy() {
  local attempt
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

# Keep a known-good copy before attempting to replace a healthy deployment.
if curl -fsS -o /dev/null --max-time 10 "$URL/" &&
   curl -fsS -o /dev/null --max-time 10 "$URL/api/health" &&
   curl -fsS -o /dev/null --max-time 30 "$URL/api/cases?limit=1"; then
  install -m 600 "$CURRENT" "$LAST_GOOD"
fi

tmp="$(mktemp "$ROOT/.image.env.XXXXXXXX")"
trap 'rm -f "$tmp"' EXIT
printf 'AMRTRACE_IMAGE_TAG=%s\n' "$new_tag" > "$tmp"
chmod 600 "$tmp"
mv -f "$tmp" "$CURRENT"

if compose_up && healthy; then
  install -m 600 "$CURRENT" "$LAST_GOOD"
  printf '%s\n' "$main_sha" > "$BASELINE"
  rm -f "$FAILED"
  echo "DEPLOY_SUCCESS=$new_tag"
  exit 0
fi

echo "DEPLOY_FAILED: Restoring the last verified images." >&2
install -m 600 "$LAST_GOOD" "$CURRENT"
printf '%s\n' "$main_sha" > "$FAILED"
if ! compose_up; then
  echo "ROLLBACK_FAILED: Docker could not restart the prior images." >&2
  exit 1
fi
if ! healthy; then
  echo "ROLLBACK_UNHEALTHY: Check Docker logs immediately." >&2
  exit 1
fi
echo "ROLLBACK_SUCCESS: Previous images restored. Commit blocked until reviewed." >&2
exit 1
