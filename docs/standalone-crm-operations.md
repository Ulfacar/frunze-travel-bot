# Отдельная Frunze CRM: запуск и восстановление

Состояние на 13.10.2026: серверный тест отдельной CRM. Публичный домен ещё не
выбран пользователем; адрес `crm.invalid` используется только через закрытый
тестовый прокси. Это не опубликованная CRM. Текущий проверенный снимок и
результат восстановления указаны в `ai/STATE.md` и release handoff.

## Состав и границы

- `app.crm_main:create_app` — отдельный процесс без lifespan основного бота.
- Собственная PostgreSQL16, база `frunze_crm`, непривилегированная роль
  `frunze_crm`; административная роль контейнера — `crm_owner`.
- Закрытая Docker-сеть `172.30.78.0/24`; приложение `172.30.78.10:8000`,
  доверенный прокси `172.30.78.1`. Публичных портов приложения/БД нет.
  На установленном Docker публикация8078 во внутренней сети не работала;
  nginx обращается непосредственно к закреплённому частному IP.
- Старые `frunze-travel-*`, их тома, настройки и маршруты не входят в release.
- Первый пользователь — отдельный администратор `alan` с новым случайным
  паролем. Дополнительные пользователи требуют явного состава и ролей.
- Исходные208 единиц знаний остаются draft. Цены, правовые, календарные и
  privacy/storage-политики не утверждаются развёртыванием. J05 остаётся UNKNOWN.

## Артефакт

Сборка разрешает только перечисленные исходники приложения, миграции,
knowledge assets, производный текст и исходный PDF с проверенным SHA256.
Тесты, `.env`, записи разговоров и локальные данные в образ не попадают.

```powershell
python scripts/crm_release_bundle.py --snapshot runs/crm-standalone-rN --destination runs/crm-bundle-rN
```

Использовать зафиксированный env-free снимок, прошедший review. Команда
проверяет overlay-хэши и включает фактический compose и operational helper
в manifest. Release identity — первые20 символов SHA256 `manifest.json`.
Перед распаковкой на сервере проверить все имена tar; после — все420 хэшей.
Собирать и проверять один образ, затем сохранять его image ID и зависимости;
повторная сборка с плавающими версиями requirements не считается тем же образом.

## Первый запуск новой рабочей CRM

1. Получить точный hostname, проверить DNS и отсутствие чужого nginx server_name.
   Не заменять занятый `app.frunzetravel.kg`. Выделить `/root/frunze-crm` и новый
   Compose project `frunze-crm`. Не переносить тестовый том или клиентскую базу бота.
2. Распаковать проверенный release; создать секреты на сервере командой ниже.
   `crm.env`, `compose.env`, `first-login.json`, `database-role.sql` должны
   остаться0600 в каталоге0700. Генератор не заменяет существующие файлы.
3. Проверить свободный subnet. Если172.30.78.0/24 занят тестом, выполнить
   `docker compose --env-file compose.env -p frunze-crm-check -f compose.crm.yaml down`
   из его каталога `/root/frunze-crm-review/r9`, **без `-v`**. Это останавливает
   только тестовые контейнеры и удаляет их сеть, сохраняя том и backup. Простого
   `stop` недостаточно: существующая Docker-сеть удерживает подсеть. Проверить,
   что сеть удалена и подсеть свободна, до запуска нового project.
4. Запустить новую БД, создать роль через подготовленный SQL, выполнить init.
   Init отказывается работать с непустой БД. Не запускать его на старом боте.
5. Запустить приложение, проверить health/revision, роли, schema0043,
   bootstrap ready,208draft/0confirmed, пустой клиентский реестр.
6. Подключить отдельный hostname к nginx и получить его действительный TLS
   сертификат. Проверить `nginx -t` до reload, затем HTTPS/login/CSRF/cookie,
   native flow и неизменность старого бота. Самоподписанный тестовый TLS не
   заменяет эту проверку.

Примеры выполняются в каталоге **нового** release. Значения origin/release
заменяются только подтверждёнными данными; секреты не передаются в командной строке.

```sh
python3 scripts/crm_prepare_environment.py --directory . --origin https://CONFIRMED_HOST --release REVIEWED_MANIFEST_ID
docker compose --env-file compose.env -p frunze-crm -f compose.crm.yaml config --quiet
docker compose --env-file compose.env -p frunze-crm -f compose.crm.yaml up -d --wait db
docker compose --env-file compose.env -p frunze-crm -f compose.crm.yaml exec -T db psql -v ON_ERROR_STOP=1 -U crm_owner -d postgres < database-role.sql
docker compose --env-file compose.env -p frunze-crm -f compose.crm.yaml run --rm --no-deps app python scripts/crm_initialize.py --fresh-database --source release-source.pdf
docker compose --env-file compose.env -p frunze-crm -f compose.crm.yaml up -d --wait app
```

Если после миграций импорт прерван, приложение откажется стартовать без ready
marker. `--resume-bootstrap --source release-source.pdf` вместо `--fresh-database`
разрешён только для записанного pending bootstrap со schema0043 и без клиентов
и услуг. Частично выполненная миграция требует отдельного восстановления.

## Ограничения процесса

Приложение работает под UID/GID10001, с read-only root и временным `/tmp`,
нулевыми Linux capabilities и стандартными AppArmor/seccomp. В Docker Snap
NNP до первоначального перехода AppArmor давал `operation not permitted`.
Поэтому абсолютный ENTRYPOINT `setpriv --no-new-privs --` включает тот же
необратимый флаг перед Python, после перехода в `docker-default`. Healthcheck
также использует setpriv. Это соответствует наследованию флага через exec,
описанному в [документации ядра Linux](https://docs.kernel.org/userspace-api/no_new_privs.html).

Проверять именно `/proc/1/status` и `/proc/1/attr/current`: UID/GID10001,
CapInh/Prm/Eff/Bnd/Amb=0, NoNewPrivs=1, Seccomp=2, docker-default enforcing.
`docker exec` обходит ENTRYPOINT: любые maintenance Python команды запускать
с `/usr/bin/setpriv --no-new-privs --` или через `compose run`.
Не отключать AppArmor/seccomp и не менять Docker daemon ради этого сервиса.

## Backup и откат

Снимать `pg_dump -Fc` только из собственной БД. Файл хранить0600 за пределами
образа. Проверять восстановлением в **новый** volume/контейнер с отдельной
закрытой сетью и новым паролем, а не поверх рабочей БД. Проверка включает
строки/ID, внешние ключи, sequences, чтение прежнего дела, точный повтор
сохранённой команды и новую допустимую операцию. Evidence не содержит cookie,
подписанных форм, паролей или клиентских данных.

13.10.2026 отдельный аудитор выполнил этот сценарий на синтетической R8:
78 таблиц и61 sequence совпали,160 внешних ключей валидны; исходные подписанные
повторы обращения/дела не изменили fingerprint, конкурентный ввод создал одну
запись, новая задача после restore сохранена. R9 меняет только CSS/подпись
календаря. Evidence: `runs/crm-standalone-audit-r8/runs/audit-recovery-r8.json`;
итог: `ai/reviews/2026-10-13-standalone-crm-final-audit.md`.
Сохранённый серверный backup находится в `/root/frunze-crm-review/audit-recovery-r8`,
clone-контейнеры остановлены. Рабочая база оператора ещё не создана.

При неудачной публикации отключить только новый nginx маршрут или остановить
только новый app. Сохранить новый том и backup. При замене вернуть точный
предыдущий image ID и совместимые настройки. Не применять `down -v`, prune,
сброс базы или downgrade с данными. Публичная выкладка и исходный бот имеют
раздельные проверки, rollback и владельцев ресурсов.

После фактического запуска обновить PDF, `ai/CLAUDE_HANDOFF.md`, `ai/STATE.md`
и handoff; лишь затем отправить Алану личное Telegram уведомление с итоговым
адресом. Токен и получателя проверить на сервере, не помещать значения в Git.
