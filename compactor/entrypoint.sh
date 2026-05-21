#!/bin/sh
# Compactor cron entrypoint. Validates required env, writes a crontab from
# CRON_SCHEDULE, and runs crond in the foreground so docker can manage
# lifecycle and capture logs.
#
# Required env:
#   INTERNAL_API_TOKEN    Shared secret matching settings.INTERNAL_API_TOKEN
#                         on the backend.
# Optional env:
#   CRON_SCHEDULE         Cron expression. Default: "0 20 * * 5" (Fri 20:00).
#   BACKEND_URL           Target URL. Default: http://backend:8000.
#   TRIGGER_PATH          Endpoint path. Default: /panel/api/internal/compaction/run-weekly/.
#   MAX_WORKERS           Parallel workers for the compaction job. Default: 2.
#   TZ                    Container timezone. Default: Europe/Skopje.
#   REQUEST_TIMEOUT       curl --max-time value (seconds). Default: 30.

set -eu

: "${CRON_SCHEDULE:=0 20 * * 5}"
: "${BACKEND_URL:=http://backend:8000}"
: "${TRIGGER_PATH:=/panel/api/internal/compaction/run-weekly/}"
: "${MAX_WORKERS:=2}"
: "${TZ:=Europe/Skopje}"
: "${REQUEST_TIMEOUT:=30}"

if [ -z "${INTERNAL_API_TOKEN:-}" ]; then
    echo "[compactor] FATAL: INTERNAL_API_TOKEN is empty or unset" >&2
    exit 1
fi

# Persist tz selection so crond uses the right local time.
if [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    cp "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

# The cron job itself just POSTs to the trigger endpoint and logs the
# response. The backend immediately returns 202 and runs compaction
# out-of-band; this curl call lasts seconds, not minutes.
cat <<EOF > /usr/local/bin/run-compaction.sh
#!/bin/sh
set -eu
TS=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "[compactor \$TS] triggering weekly compaction at ${BACKEND_URL}${TRIGGER_PATH}"
HTTP_STATUS=\$(curl -sS -o /tmp/compactor-resp.json -w "%{http_code}" \\
    --max-time ${REQUEST_TIMEOUT} \\
    -X POST \\
    -H "Content-Type: application/json" \\
    -H "X-Internal-Token: \${INTERNAL_API_TOKEN}" \\
    -d "{\"max_workers\": ${MAX_WORKERS}}" \\
    "${BACKEND_URL}${TRIGGER_PATH}") || HTTP_STATUS=000
echo "[compactor \$TS] http_status=\$HTTP_STATUS body=\$(cat /tmp/compactor-resp.json 2>/dev/null || echo '<none>')"
if [ "\$HTTP_STATUS" != "202" ] && [ "\$HTTP_STATUS" != "409" ]; then
    # 409 (already compacted) is benign for a periodic retrigger; everything
    # else is a real failure surfaced to docker logs for the operator.
    echo "[compactor \$TS] FAILED: unexpected http_status=\$HTTP_STATUS" >&2
    exit 1
fi
EOF
chmod +x /usr/local/bin/run-compaction.sh

# Crontab format: minute hour dom mon dow command
# Pass INTERNAL_API_TOKEN through cron's stripped environment via a small
# wrapper that re-reads /etc/environment.
echo "INTERNAL_API_TOKEN=${INTERNAL_API_TOKEN}" > /etc/environment
echo "${CRON_SCHEDULE} . /etc/environment; /usr/local/bin/run-compaction.sh >> /var/log/compactor.log 2>&1" > /etc/crontabs/root

touch /var/log/compactor.log

echo "[compactor] schedule='${CRON_SCHEDULE}' tz='${TZ}' target='${BACKEND_URL}${TRIGGER_PATH}' max_workers=${MAX_WORKERS}"
echo "[compactor] starting crond in foreground"

# -f foreground, -L log to stdout, -d log-level (8=info)
crond -f -L /dev/stdout -d 8 &
CROND_PID=$!

# Tail the cron job's log so docker logs surface curl responses live.
tail -F /var/log/compactor.log &

wait $CROND_PID
