#!/bin/sh
# Ежедневный бэкап Frunze: БД + prod.env, ротация, алерт в Telegram при сбое.
#
# Что изменилось 30.07: раньше бэкапился ТОЛЬКО дамп БД. prod.env не попадал никуда, а в
# нём MANAGERS с паролями и все токены — потеря файла означала потерю всех логинов и
# доступов. Плюс сбой был молчаливым: stderr уходил в лог, который никто не читает.
#
# Крон (не менять расписание): 20 3 * * * /root/backups/backup_frunze.sh >> /root/backups/backup.log 2>&1
set -u
DIR=/root/backups
ENVFILE=/root/frunze-travel/prod.env
STAMP=$(date +%Y%m%d_%H%M)
DUMP="$DIR/frunze_daily_${STAMP}.dump"
MIN_BYTES=100000          # дамп меньше 100 КБ = что-то сломалось, это не норма
DOCKER=/snap/bin/docker

log() { echo "$(date -u +'%Y-%m-%d %H:%M:%S') $*"; }

alert() {
    # Тревога владельцам тем же ботом, что шлёт брифы. Токен читаем из prod.env, не логируем.
    TOKEN=$(grep -E '^MANAGERS_TELEGRAM_BOT_TOKEN=' "$ENVFILE" 2>/dev/null | cut -d= -f2-)
    [ -z "$TOKEN" ] && TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENVFILE" 2>/dev/null | cut -d= -f2-)
    [ -z "$TOKEN" ] && return 0
    for CHAT in $ALERT_CHATS; do
        curl -s -m 20 -o /dev/null \
             --data-urlencode "text=🔴 Бэкап Frunze не сделан: $1" \
             --data "chat_id=$CHAT" \
             "https://api.telegram.org/bot$TOKEN/sendMessage" || true
    done
}
ALERT_CHATS="434859857"    # Гриша (admin). Добавлять через пробел.

# --- БД ---
if ! $DOCKER exec frunze-travel-db-1 pg_dump -U postgres -d frunze -F c -f /tmp/frunze_daily.dump; then
    log "ОШИБКА: pg_dump упал"; alert "pg_dump упал"; exit 1
fi
if ! $DOCKER cp frunze-travel-db-1:/tmp/frunze_daily.dump "$DUMP"; then
    log "ОШИБКА: docker cp дампа не удался"; alert "не удалось забрать дамп из контейнера"; exit 1
fi
SIZE=$(wc -c < "$DUMP")
if [ "$SIZE" -lt "$MIN_BYTES" ]; then
    log "ОШИБКА: дамп подозрительно мал ($SIZE байт)"; alert "дамп всего $SIZE байт"; exit 1
fi
log "ok: БД $DUMP ($SIZE байт)"

# --- prod.env (пароли менеджеров и токены; без него прод не поднять) ---
if [ -f "$ENVFILE" ]; then
    cp -a "$ENVFILE" "$DIR/prod.env.${STAMP}" && chmod 600 "$DIR/prod.env.${STAMP}"
    log "ok: prod.env скопирован"
else
    log "ВНИМАНИЕ: $ENVFILE не найден"; alert "prod.env не найден на месте"
fi

# --- ротация: БД 7 дней, env 30 (файл крошечный, а восстанавливать по нему логины) ---
find "$DIR" -name 'frunze_daily_*.dump' -mtime +7 -delete
find "$DIR" -name 'prod.env.*' -mtime +30 -delete
log "готово"
