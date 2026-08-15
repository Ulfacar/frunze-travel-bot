#!/bin/bash
# Деплой Frunze Travel на боевом сервере. Запускается НА СЕРВЕРЕ:
#
#     /root/frunze-travel/scripts/deploy_prod.sh
#
# Что делает: подтягивает код из репозитория, бэкапит prod.env, пересобирает контейнер,
# ждёт здоровья — и САМ ОТКАТЫВАЕТСЯ, если приложение не поднялось.
#
# Зачем скриптом, а не руками. До 15.08.2026 деплой шёл копированием файлов по scp, и на
# вопрос «что сейчас крутится на проде» ответа не существовало: сверять приходилось хешами.
# Плюс две ловушки, на которых мы уже обжигались:
#
#   1. `docker compose` БЕЗ `--env-file prod.env` поднимает контейнер с пустым MANAGERS —
#      логины менеджеров в панель отваливаются молча, приложение при этом «здорово».
#   2. `docker-compose.vps.yml` обязателен: без него контейнер лезет на порты 80/443, где
#      уже сидит системный nginx с сертификатами других проектов.
#
# Оба флага теперь зашиты здесь, забыть их нельзя.
set -euo pipefail

APP_DIR=/root/frunze-travel
BACKUP_DIR=/root/backups
BRANCH="${1:-fix/tours-search-quality}"
HEALTH_URL=http://localhost:8000/health
HEALTH_TRIES=20        # 20 попыток по 3 секунды = минута на подъём
HEALTH_SLEEP=3

cd "$APP_DIR"

compose() {
    docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env "$@"
}

healthy() {
    for _ in $(seq "$HEALTH_TRIES"); do
        if curl -sf -m 5 "$HEALTH_URL" | grep -q '"status":"ok"'; then
            return 0
        fi
        sleep "$HEALTH_SLEEP"
    done
    return 1
}

PREV=$(git rev-parse HEAD)
echo "== было: $PREV ($(git log --oneline -1 --format=%s))"

# prod.env вне git намеренно — в нём боевые токены. Бэкапим отдельно, каждый деплой.
cp prod.env "$BACKUP_DIR/prod.env.before-deploy-$(date +%Y%m%d_%H%M)"

git fetch -q origin "$BRANCH"
git checkout -q -B "$BRANCH" "origin/$BRANCH"
NEW=$(git rev-parse HEAD)
echo "== стало: $NEW ($(git log --oneline -1 --format=%s))"

if [ "$PREV" = "$NEW" ]; then
    echo "== код не изменился, пересобираю всё равно (мог измениться prod.env)"
fi

compose up -d --build app

if healthy; then
    echo "== здоров. Деплой завершён: $NEW"
    exit 0
fi

echo "!! приложение не поднялось за $((HEALTH_TRIES * HEALTH_SLEEP)) секунд — ОТКАТ на $PREV"
git checkout -q "$PREV"
compose up -d --build app
if healthy; then
    echo "== откат удался, работает прежняя версия $PREV"
else
    echo "!! откат НЕ помог — приложение лежит. Смотреть: docker logs frunze-travel-app-1 --tail 50"
fi
exit 1
