# Tiny alpine-based cron container that pings the backend's internal
# weekly-compaction trigger endpoint on a schedule. Holds no database
# credentials and no application code — just curl + crond + a shared
# secret. Detaches the schedule lifecycle from the backend's container
# lifecycle.
#
# Build:    docker compose build compactor
# Run:      docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d compactor
# Inspect:  docker compose logs -f compactor

FROM alpine:3.19

RUN apk add --no-cache curl tzdata

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
