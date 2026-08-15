#!/bin/bash
# Откат боевого сервера на предыдущую (или указанную) версию. Запускается НА СЕРВЕРЕ:
#
#     /root/frunze-travel/scripts/rollback_prod.sh              # на один коммит назад
#     /root/frunze-travel/scripts/rollback_prod.sh 7409d44      # на конкретный коммит
#
# Нужен для случая, когда беда видна не сразу: `deploy_prod.sh` откатывается сам, но только
# если приложение не поднялось. Логическую поломку — бот отвечает, но неправильно — ловит
# человек через час, и вот тогда нужен откат одной командой, без вспоминания, что где лежало.
#
# prod.env не трогаем: он вне git и живёт своей жизнью. Если ломает именно он, бэкапы лежат
# в /root/backups/prod.env.before-deploy-*.
set -euo pipefail

APP_DIR=/root/frunze-travel
TARGET="${1:-HEAD~1}"

cd "$APP_DIR"

compose() {
    docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env "$@"
}

CURRENT=$(git rev-parse HEAD)
COMMIT=$(git rev-parse "$TARGET")

echo "== сейчас: $CURRENT ($(git log --oneline -1 --format=%s))"
echo "== откат на: $COMMIT ($(git log --oneline -1 --format=%s "$COMMIT"))"

git checkout -q "$COMMIT"
compose up -d --build app

for _ in $(seq 20); do
    if curl -sf -m 5 http://localhost:8000/health | grep -q '"status":"ok"'; then
        echo "== откат выполнен, приложение здорово: $COMMIT"
        echo "== вернуться обратно: scripts/rollback_prod.sh $CURRENT"
        exit 0
    fi
    sleep 3
done

echo "!! приложение не поднялось и после отката. Смотреть: docker logs frunze-travel-app-1 --tail 50"
exit 1
