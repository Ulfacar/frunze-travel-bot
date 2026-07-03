# СПЕКА для Codex — второй полный админ-аккаунт (self-describing)

Автор: Claude (планирует + ревьюит). Исполнитель: Codex (пишет код). Режим Веном.

## Задача
Дать возможность заводить **второй (и любой N-й) полный админ-аккаунт** админ-панели через env
`MANAGERS`, чтобы аккаунт сам объявлял себя админом, а не полагался на хрупкий трюк
«подстрока `админ` в имени» или на единственный `admin_user`.

Полный админ = видит все воронки (визы + туры + билеты), аналитику и LLM-бюджет
(`_manager_bot_scope(...) is None`).

**Не трогаем** разделение воронок для менеджеров (`BOT_SCOPE_BY_MANAGER`) — оно остаётся как есть.

## Почему так
Сейчас (`app/config.py`, `app/admin/router.py`):
- Аккаунты — в env `MANAGERS` (JSON, пароли открытым текстом, by design).
- Если `MANAGERS` задан, fallback `admin_user`/`admin_password` **выключается** (`manager_list()`),
  значит на проде админ существует только если он есть внутри `MANAGERS`.
- «Полный админ» определяется в `_manager_bot_scope` по `login in {"admin","administrator",admin_user}`
  **или** `"админ" in name`. Второй критерий — хрупкий (случайное «админ» в имени = случайный суперюзер),
  первый — не масштабируется на несколько админов.

Решение: явный флаг `admin: bool` в `ManagerConfig`. Аккаунт сам несёт свою роль.

## Изменения (3 точки)

### 1. `app/config.py` — поле в `ManagerConfig`
Класс `ManagerConfig` (сейчас строки ~44-51). Добавить поле:
```python
class ManagerConfig(BaseModel):
    """..."""
    login: str
    name: str = ""
    password: str = ""
    admin: bool = False  # True → полный доступ ко всем воронкам (как admin_user)
```
`extra`-поля pydantic по умолчанию игнорирует, поэтому старые JSON без `admin` продолжают работать
(`admin=False`). Обратная совместимость сохранена.

### 2. `app/admin/router.py` — прокинуть флаг в cookie-сессию
Функция `_check_credentials` (сейчас строки 175-180). Вернуть `admin` в dict сессии:
```python
def _check_credentials(login: str, password: str) -> dict | None:
    for mgr in settings.manager_list():
        if (secrets.compare_digest(login, mgr.login)
                and secrets.compare_digest(password, mgr.password)):
            return {"login": mgr.login, "name": mgr.name or mgr.login, "admin": bool(mgr.admin)}
    return None
```

### 3. `app/admin/router.py` — учесть флаг в скоупе
Функция `_manager_bot_scope` (сейчас строки 183-192). Добавить проверку флага **первой**,
до логин/имя-эвристик (их НЕ удаляем — обратная совместимость с текущим прод-`admin`):
```python
def _manager_bot_scope(manager: dict | None) -> set[str] | None:
    """Return bot ids visible to this manager. None means unrestricted admin view."""
    if not manager:
        return set()
    if manager.get("admin"):          # NEW: явный флаг из ManagerConfig
        return None
    login = str(manager.get("login") or "").strip().lower()
    name = str(manager.get("name") or "").strip().lower()
    admin_login = str(settings.admin_user or "").strip().lower()
    if login in {"admin", "administrator", admin_login} or "админ" in name:
        return None
    return BOT_SCOPE_BY_MANAGER.get(login) or BOT_SCOPE_BY_MANAGER.get(name) or set()
```
Старые сессии (залогинены до деплоя) не содержат ключ `admin` → `.get("admin")` = None → падают
в старую ветку. Безопасно.

## Тесты (обязательно)
Добавить в существующий тест-модуль скоупа админки (там, где уже тестируется fail-closed
`_manager_bot_scope` / `_can_view_conversation`):
1. `ManagerConfig(login="grisha", admin=True)` → после логина сессия `{"admin": True}` →
   `_manager_bot_scope` возвращает `None` (видит всё).
2. `admin=False` без записи в `BOT_SCOPE_BY_MANAGER` → `_manager_bot_scope` = `set()` (fail-closed, не видит ничего).
3. Обратная совместимость: сессия-dict БЕЗ ключа `admin` + имя «Медина» → скоуп визовых ботов (как раньше).
4. Обратная совместимость: логин `admin` (без флага) → `None` (как раньше).
5. JSON `MANAGERS` со старой схемой (без `admin`) грузится без ошибок, `admin=False`.

## Env для прода (после деплоя кода)
Добавить админа в `MANAGERS` (JSON в `.env` на VPS `/root/frunze-travel/.env`).
Пример полного значения — существующие менеджеры + новый полный админ:
```
MANAGERS='[
  {"login":"ademi","name":"Адеми","password":"..."},
  {"login":"sezim","name":"Сезим","password":"..."},
  {"login":"medina","name":"Медина","password":"..."},
  {"login":"eliza","name":"Элиза","password":"..."},
  {"login":"grisha","name":"Гриша","password":"СМЕНИ_МЕНЯ","admin":true}
]'
```
⚠️ ВАЖНО: `MANAGERS` перезаписывает список целиком — не потеряй существующие 4 записи и текущего
`admin`. Возьми актуальный `MANAGERS` с прода и допиши только последнюю строку.

## Деплой (прод не в git — файлами)
1. Codex вносит 3 правки + тесты, локально `pytest` зелёный.
2. Claude ревьюит (codex-reviewer) — гейт перед деплоем.
3. Копируем изменённые `app/config.py`, `app/admin/router.py` на VPS `/root/frunze-travel/`.
4. Дописываем строку в `MANAGERS` в `.env` (бэкап .env перед правкой).
5. `docker compose up -d --build app` (или restart), проверяем вход новым логином → видит обе воронки.

## Проверка приёмки
- Новый логин `grisha` заходит и видит вкладки Визы + Туры + Билеты, аналитику, LLM-бюджет.
- Существующие Адеми/Сезим/Медина/Элиза по-прежнему видят только свою воронку (не сломали скоуп).
- Существующий `admin` продолжает работать.
- pytest зелёный.
