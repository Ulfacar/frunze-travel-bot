"""Конфигурация приложения (pydantic-settings, читает .env)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotConfig(BaseModel):
    """Один из продакшн-ботов: туры или визы.

    Каждый бот = свой профиль Wappi (WhatsApp-номер) + свой чат-бот Bitrix (imbot)
    в своей Открытой линии + своя CRM-воронка (category_id). Сценарий жёстко задаёт
    воронку, поэтому тур-боты не угадывают её по ключевым словам.
    Маршрутизация входящих событий Bitrix — по `bitrix_bot_id` (BOT_ID, который
    Bitrix присылает в событии imbot).
    """

    id: str                              # frunze_tours | getvisa
    scenario: Literal["tours", "visa"]
    title: str = ""                      # человекочитаемое имя профиля (FrunzeTravel…)
    manager_name: str = ""               # имя персоны в клиентских ответах
    wappi_profile_id: str = ""           # профиль Wappi Pro (WhatsApp)
    bitrix_bot_id: str = ""              # imbot BOT_ID — ключ маршрутизации входящих
    bitrix_line_id: str = ""             # CONFIG_ID Открытой линии
    category_id: str = ""                # CRM CATEGORY_ID воронки этого бота


class TelegramBotConfig(BaseModel):
    """Тестовый Telegram-бот — песочница («черновик») для обкатки правок, чтобы не
    экспериментировать на живых WhatsApp-номерах, где сидят реальные клиенты.

    Каждый бот = свой токен @BotFather + ЖЁСТКО заданный сценарий (как WhatsApp-бот):
    одна копия воронки туров, другая — виз. Поведение 1:1 с продакшн-ботами.
    """

    id: str                              # frunze_tours_tg | getvisa_tg
    scenario: Literal["tours", "visa"]
    token: str                           # токен бота от @BotFather
    title: str = ""                      # человекочитаемое имя (для логов/панели)


class ManagerConfig(BaseModel):
    """Аккаунт менеджера админ-панели. Список задаётся в env MANAGERS (JSON),
    как и BOTS. Пароль в открытом виде (как admin_password) — для простой команды
    из нескольких человек; хеширование можно добавить позже."""

    login: str
    name: str = ""
    password: str = ""
    admin: bool = False  # True → полный доступ ко всем воронкам и статистике (как admin_user)
    # Личный Telegram chat_id менеджера для персонального Morning Brief. ТОЛЬКО из env
    # (MANAGERS JSON); НЕ хардкодить в исходниках и НЕ логировать. Пусто → бриф этому
    # менеджеру не шлётся (календарь работает), в общую группу НЕ уходит.
    telegram_chat_id: str = ""


# Дефолтный реестр — 2 стартовых Wappi-бота. Реальные секреты приходят из .env
# (через JSON-переменную BOTS) либо проставляются в Фазе 0 после imbot.register.
DEFAULT_BOTS: list[BotConfig] = [
    BotConfig(id="frunze_tours", scenario="tours", title="FrunzeTravel2", manager_name="Адеми", wappi_profile_id="02a4708d-ec6c"),
    BotConfig(id="frunze_tours_sezim", scenario="tours", title="FrunzeTravel", manager_name="Сезим", wappi_profile_id="6a74fb33-16aa"),
    BotConfig(id="getvisa", scenario="visa", title="FrunzeTravel Visa", manager_name="Медина", wappi_profile_id="2f099bc3-478d"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = ""
    openrouter_app_name: str = "Frunze Travel Bot"
    openrouter_timeout_seconds: float = 60.0
    anthropic_api_key: str = ""
    llm_model_main: str = "anthropic/claude-3.5-sonnet"
    llm_model_cheap: str = "anthropic/claude-3-haiku"
    llm_max_tokens: int = 512
    llm_temperature: float = 0.3
    llm_history_max_messages: int = 40  # 0 = no window; send full history
    llm_daily_budget_usd: float = 0.0
    llm_daily_budget_soft_ratio: float = 0.8

    # Каналы
    telegram_bot_token: str = ""         # дев-демо: один бот с keyword-детектом воронки (легаси)
    # Тестовые Telegram-боты (песочница «черновик»): по боту на сценарий, жёсткая воронка.
    # JSON в env: TELEGRAM_BOTS='[{"id":"frunze_tours_tg","scenario":"tours","token":"123:abc"},
    #                             {"id":"getvisa_tg","scenario":"visa","token":"456:def"}]'.
    # Вебхук каждого: POST /webhook/telegram/<id>.
    telegram_bots: list[TelegramBotConfig] = []

    # Секрет проверки входящих вебхуков (defense-in-depth поверх IP-фильтра nginx).
    # Пусто → проверка выключена (обратная совместимость). Wappi/Bitrix: ?s=<secret>
    # или заголовок X-Webhook-Secret; Telegram: заголовок X-Telegram-Bot-Api-Secret-Token.
    webhook_secret: str = ""

    # Wappi Pro (WhatsApp): token аккаунтовый, profile_id — на каждого бота (см. bots)
    wappi_base_url: str = "https://wappi.pro"
    wappi_token: str = ""
    wappi_profile_id: str = ""           # дев-демо: одиночный профиль (легаси)
    capture_manager_echo: bool = False
    manager_silence_hours: int = Field(
        default=3, ge=1
    )                                      # часов молчания бота после ответа менеджера с телефона

    # TourVisor — кабинетные креды подходят и для XML API (проверено 19.06.2026)
    # Суточная квота тарифа TourVisor. При исчерпании бот не падает, а отвечает всем
    # «поиск временно недоступен» — тихо, без алерта. Счётчик + предупреждение владельцу
    # на пороге: узнать об исчерпании до клиентов, а не от клиентов. 0 = не следить.
    tourvisor_daily_quota: int = 3000
    tourvisor_quota_alert_ratio: float = 0.7
    tourvisor_login: str = ""
    tourvisor_pass: str = ""

    # Хранилище
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/frunze"
    redis_url: str = "redis://localhost:6379/0"
    state_backend: Literal["memory", "redis"] = "memory"  # прод: STATE_BACKEND=redis
    state_ttl_seconds: int = 7 * 24 * 3600  # неактивный диалог живёт 7 дней

    # CRM (портал один — облако getvisakg.bitrix24.kz; вебхук портал-уровня)
    crm_backend: Literal["stub", "postgres", "bitrix24"] = "stub"
    bitrix24_webhook_url: str = ""
    # ⚠️ Бот создаёт ЛИДЫ (не сделки): воронки Bitrix начинаются после оплаты, менеджер
    # конвертит Лид→Сделку сам. Поэтому CATEGORY_ID лиду НЕ задаётся — эта карта пока не
    # используется (оставлена на будущее, если заведём конвертацию/распределение по воронкам).
    bitrix_category_by_funnel: dict[str, str] = {}
    # [?] Внутренняя стадия бота → STATUS_ID ЛИДА Bitrix (напр. "IN_PROCESS"); пусто → не двигаем.
    bitrix_stage_map: dict[str, str] = {}
    # Зеркалирование диалога в Bitrix как ЛИД + комментарии (ТЗ 02.07 п.3). Отдельный
    # best-effort сайд-канал, НЕ зависит от crm_backend. Дефолт OFF — включается флагом из БД.
    bitrix_mirror_enabled: bool = False

    # Реестр ботов. Переопределяется JSON-строкой в env BOTS='[{...}, ...]'.
    bots: list[BotConfig] = DEFAULT_BOTS

    # Админ-панель (канбан + чат + перехват). Бэкенд лога диалогов и доступ.
    panel_backend: Literal["memory", "postgres"] = "memory"  # прод: PANEL_BACKEND=postgres
    admin_enabled: bool = True
    admin_user: str = "admin"
    admin_password: str = "frunze"  # ПРОД: переопределить ADMIN_PASSWORD!
    # Аккаунты менеджеров: JSON в env MANAGERS='[{"login":"sezim","name":"Сезим","password":"..."}]'.
    # Пусто → один менеджер из admin_user/admin_password (обратная совместимость).
    managers: list[ManagerConfig] = []
    # Watchdog-алерты: уведомлять админа в WhatsApp при тишине вебхуков / всплеске сбоев.
    # Пусто → алерты выключены. alert_bot_id — id бота (профиля), от чьего имени слать.
    alert_whatsapp_to: str = ""          # номер админа (chat_id), напр. 996700...@c.us или 996700...
    alert_bot_id: str = ""               # с какого бота слать (frunze_tours|getvisa)
    alert_silence_minutes: int = 30      # тишина дольше → алерт
    alert_fail_threshold: int = 5        # столько новых сбоев за тик → алерт
    alert_cooldown_minutes: int = 60     # не повторять один и тот же алерт чаще
    alert_awaiting_minutes: int = 10     # клиент ждёт живого менеджера дольше → алерт команде

    # Дебаунс входящих: клиенты пишут дробно (несколько коротких сообщений подряд). Бот ждёт
    # «тихое окно» этой длины, склеивает реплики и отвечает одним ходом LLM (без задвоений).
    # 0 = выключено (синхронная обработка как раньше). Прод: DEBOUNCE_SECONDS=8.
    debounce_seconds: float = 0.0

    # Автодожим: проактивный пинг клиентам, замолчавшим на этапе квалификации.
    readiness_rescore_enabled: bool = True   # ghost-ре-скоринг тира (застойный неготовый → noise)
    # Авто-исход через LLM (advisory): классифицирует won/lost/ghosted по переписке. ВЫКЛ по умолчанию
    # (стоит денег + пишет в отдельное поле outcome_inferred, ручной outcome не трогает).
    outcome_infer_enabled: bool = False
    outcome_infer_stale_hours: int = 24      # диалог без активности дольше → кандидат на классификацию
    outcome_infer_max_per_run: int = 20      # потолок вызовов LLM за прогон (бюджет)
    followup_enabled: bool = False
    # Гейт блока дожима и ценовой вилки в системном промпте.
    dozhim_enabled: bool = False
    followup_after_hours: int = 24       # молчит дольше → ПЕРВЫЙ мягкий пинг
    followup_max_pings: int = 2          # максимум пингов на клиента (ритм ~2×/неделю), потом стоп
    followup_interval_hours: int = 84    # между повторными пингами (~3.5 суток) — не чаще
    noise_stale_days: int = 3            # пустой greeting без ответа бота старше N дней = мусор
    followup_quiet_from: int = 22        # «тихие часы» (Бишкек, UTC+6): не слать с 22:00…
    followup_quiet_to: int = 9           # …до 09:00

    # Утренний «горячий лист» (Фаза 0 календаря звонков): раз в сутки утром по Бишкеку
    # cron-джоба собирает green/warm лидов и пушит менеджерам. ВЫКЛ по умолчанию. Экран
    # /admin/morning доступен всегда; Telegram-пуш — только если задан managers_telegram_chat_id
    # (+ telegram_bot_token). chat_id группы менеджеров можно завести позже без правки кода.
    morning_brief_enabled: bool = False
    morning_brief_hour: int = 9              # час Бишкека для отправки, окно [hour, hour+3); держать 0–20
    managers_telegram_chat_id: str = ""      # chat_id группы менеджеров (пусто → без Telegram-пуша)
    # Токен бота для пуша менеджерам. Пусто → фолбэк на telegram_bot_token (легаси демо-бот). Прод:
    # завести ВЫДЕЛЕННОГО бота менеджеров, чтобы пуш не зависел от тестовой песочницы.
    managers_telegram_bot_token: str = ""
    # Фикс-курс сом→$ ТОЛЬКО для тайбрейка сортировки чека в горячем листе (не для отображения —
    # там показываем как сказал клиент). Ручное обновление по необходимости, НЕ live-API. ~89 сом/$.
    som_to_usd_rate: float = 0.0112

    # Sprint 1 — персональный календарный Morning Brief менеджеру (задачи на сегодня +
    # ночные заявки) в его ЛИЧНЫЙ Telegram (ManagerConfig.telegram_chat_id). Отдельный
    # флаг от «горячего листа»; ВЫКЛ по умолчанию — включается на rollout. Окно отправки
    # и час берутся из morning_brief_hour (те же). Экран /admin/calendar работает всегда.
    calendar_brief_enabled: bool = False
    # Шаг 1 связки бот→календарь: при доставке брифа бот САМ ставит задачу-звонок
    # (kind=call, created_by='bot', на сегодня) на каждый owner-routed ночной лид —
    # чтобы утренний список звонков материализовался в календарь без ручного труда.
    # Идемпотентно: «ночные» уже исключают лидов с задачей на сегодня. Default OFF;
    # runtime key `calendar_autotask_enabled`. Требует calendar_brief_enabled.
    calendar_autotask_enabled: bool = False
    # P1.1 — главное требование встречи 29.07: «когда заявка заполнена — сразу скинуть,
    # чтобы клиент не ждал», ночью тоже. Пуш идёт ВЛАДЕЛЬЦУ диалога в личный Telegram в
    # момент, когда бот собрал заявку (stage → manager/office). Default OFF; runtime key
    # `instant_handoff_enabled`. Дедуп — условный UPDATE по conversations.handoff_notified_at.
    instant_handoff_enabled: bool = False
    # Ограничение из той же минуты записи: «главное, чтобы их это не доставало». Канал в
    # этом списке НЕ получает мгновенных пушей — его заявки уходят дайджестом в указанные
    # часы по Бишкеку. Это замена мгновенному пушу, а не добавка: два касания, не пять.
    instant_handoff_digest_bots: list[str] = []
    instant_handoff_digest_hours: list[int] = [12, 15, 19]
    # Еженедельная тур-сводка ВЛАДЕЛЬЦУ (Грише) в личный Telegram: закрывает «не вижу
    # цифр по турам → не оправдать таргет». Только честные факты + ручные продажи;
    # AI-оценка отдельной строкой с пометкой. Default OFF; runtime key
    # `tours_summary_enabled`. Получатель — менеджеры admin=True с telegram_chat_id.
    tours_summary_enabled: bool = False
    tours_summary_weekday: int = 0            # день недели отправки (0=Пн), окно = morning_brief_hour
    # Блок «ночные заявки» брифа: показывать только СВЕЖИХ клиентов (последняя активность
    # за последние N часов по Бишкеку), а не весь открытый пайплайн менеджера. 16ч —
    # окно «вечер→утро», покрывает ночь и не тащит вчерашние/недельные лиды. Список на
    # обзвон, а не свалка. Сортировка внутри — дольше всех ждёт наверху.
    night_lookback_hours: int = 16
    # Необязательный префикс абсолютных ссылок на клиента в Telegram-брифе (напр.
    # https://panel.frunzetravel.kg). Пусто → относительный путь /admin/conversation/...
    admin_base_url: str = ""

    # Секрет подписи cookie-сессии (Starlette SessionMiddleware). ПРОД: SESSION_SECRET!
    session_secret: str = "change-me-frunze-session-secret"
    # Быстрый вход на странице логина (кнопки «войти как …» без пароля) — ТОЛЬКО для демо.
    # Выключить (DEMO_LOGIN=false) перед боевым запуском с реальными клиентами.
    demo_login: bool = False

    # WP1B domain shadow bridge: mirror live Conversation events into the new domain
    # entities (Contact/Identity/Dialog) as a best-effort, fail-safe side effect.
    # Default OFF; can be flipped at runtime via app_flags key `domain_shadow_enabled`.
    # Shadow writes NEVER change bot answers, webhooks, outbound, or the source of truth.
    domain_shadow_enabled: bool = False
    # Visa round-robin ELIGIBILITY: explicit roster of visa-team manager logins (each
    # has its own Bitrix account). Temporary AVAILABILITY is a SEPARATE axis, toggled
    # per manager via app_flags key `manager_off:<login>`. The team is defined here —
    # NOT derived from the admin panel scope map. No cross-team (tours) routing.
    visa_manager_roster: list[str] = ["medina", "eliza"]

    # WP2 messaging foundation: mirror live inbound/outbound into the domain
    # CanonicalMessage/InboxEvent/OutboxJob ledgers. SEPARATE flag from the WP1B
    # contact/dialog shadow; default OFF; runtime key `messaging_shadow_enabled`.
    # These ledgers are NOT wired into live delivery and do NOT touch the Bitrix mirror.
    messaging_shadow_enabled: bool = False
    # Sprint 2: живое применение WP3-прав владения в админке. Default OFF; runtime
    # key `authz_enforce_enabled`. ON → писать можно только своим или ничьим клиентам
    # (ничей закрепляется за первым ответившим); чужой лид передаёт только полный
    # админ через «Переназначить». OFF → прежнее мягкое предупреждение «уже ведёт X».
    authz_enforce_enabled: bool = False
    # Sprint 2: авто-назначение нового ВИЗОВОГО лида по round-robin (least-recently-
    # assigned по visa_manager_roster). Default OFF; runtime key `visa_autoassign_enabled`.
    # Назначение НЕ перехватывает бота — фиксирует владельца + опц. личный TG-пуш.
    visa_autoassign_enabled: bool = False
    # Пилот: single-manager назначение туровых лидов (закрывает owner-gap Morning Brief —
    # без owner ночной туровый лид не попадает в личный бриф менеджера). Default OFF;
    # runtime key `tours_pilot_assign_enabled`. ТОЛЬКО bot_id=frunze_tours, ТОЛЬКО если у
    # контакта нет активного tours-owner. Владелец из tours_pilot_manager (не хардкод).
    tours_pilot_assign_enabled: bool = False
    tours_pilot_manager: str = "ademi"        # login Адеми (совпадает с BOT_SCOPE_BY_MANAGER)
    tours_pilot_bot_id: str = "frunze_tours"  # единственный боевой туровый WA-бот
    # Ночной режим: бот авто-отвечает ТОЛЬКО в ночное окно по Бишкеку (менеджеры днём
    # ведут вручную, ночью подхватывает бот). Default OFF; runtime key `night_mode_enabled`.
    # Окно [night_mode_from, night_mode_to) через полночь: 22→8 = с 22:00 до 08:00.
    # Работает поверх bots_enabled: если бот выключен кнопкой — ночь его не включит;
    # если включён — днём молчит, ночью отвечает. Входящие всё равно копятся в панель.
    night_mode_enabled: bool = False
    night_mode_from: int = 22                 # час Бишкека начала ночного окна (вкл)
    night_mode_to: int = 8                    # час Бишкека конца ночного окна (выкл)
    # Anti-loop thresholds (pure service; not enforced in the live path yet).
    antiloop_repeat_window_seconds: int = 60   # identical outbound within window = loop
    antiloop_runaway_window_seconds: int = 60  # window for the runaway burst check
    antiloop_runaway_max_outbound: int = 5     # >= N outbound w/o inbound in window = runaway

    def manager_list(self) -> list[ManagerConfig]:
        """Эффективный список менеджеров (с дефолтом из admin_user/admin_password)."""
        if self.managers:
            return self.managers
        return [ManagerConfig(login=self.admin_user, name="Менеджер", password=self.admin_password)]


settings = Settings()
