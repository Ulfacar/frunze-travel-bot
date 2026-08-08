"""ГЕЙТ: график работы — правило в коде, а не пожелание в промпте.

Написан ДО реализации и исполнителем НЕ редактируется.

Авария 06.08, визовый канал, диалог с Кубатом (скриншот от владельца + сообщения
14952-14958 в базе прода):

    бот: Понял, в выходной день. Какой день вам подходит лучше. суббота или воскресенье?
    бот: Хорошо, воскресенье. Какое время вам удобно? Например, утро, день или вечер?
    бот: Отлично, Кубат! Вас записали на консультацию в воскресенье вечером.

По визам график пн–сб 10:00–19:00: в воскресенье закрыто, и «вечера» не существует ни
в один день — в 19:00 офис закрывается. Бот предложил закрытый день САМ, клиента об этом
никто не просил.

Причина не в формулировке промпта. График подставляется в знания строкой, а что из неё
следует, решает модель — и решает по-разному: в ночь на 07.08 тот же бот дважды ответил
правильно («воскресенье выходной»), а сутками раньше записал на воскресенье вечером.
Один вопрос, разные ответы = правила нет. Это первый закон Венома: агент нужен там, где
нужен естественный язык, всё остальное — код.

За 21 день: getvisa упомянул воскресенье 7 раз, 4 из них без оговорки «выходной»;
frunze_tours — 4 раза, 3 без оговорки.

Требуется от реализации (app/core/schedule.py):

    is_open(bot_id, local_dt) -> bool
    next_open_days(bot_id, local_dt, count) -> list[date]
    schedule_note(bot_id, local_dt) -> str      # служебная строка в промпт, как дата
    violates_schedule(bot_id, text, local_dt) -> str   # "" | причина
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

VISA_BOT = "getvisa"
TOURS_BOT = "frunze_tours"

# 2026-08-09 — воскресенье, 2026-08-08 — суббота, 2026-08-10 — понедельник.
SUNDAY = date(2026, 8, 9)
SATURDAY = date(2026, 8, 8)
MONDAY = date(2026, 8, 10)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)


# --- сама авария ---------------------------------------------------------------

def test_visa_office_is_closed_on_sunday():
    """Главный тест: ровно то, что бот предложил Кубату."""
    from app.core.schedule import is_open

    assert is_open(VISA_BOT, _at(SUNDAY, 15)) is False
    assert is_open(VISA_BOT, _at(SATURDAY, 15)) is True
    assert is_open(VISA_BOT, _at(MONDAY, 15)) is True


def test_evening_is_outside_hours_on_every_day():
    """«Вечер» не существует ни в один день: в 19:00 закрываются оба направления."""
    from app.core.schedule import is_open

    for bot_id in (VISA_BOT, TOURS_BOT):
        assert is_open(bot_id, _at(MONDAY, 19, 30)) is False, bot_id
        assert is_open(bot_id, _at(MONDAY, 21)) is False, bot_id


def test_visa_opens_later_than_tours():
    """Визы с 10:00, туры с 09:00 — разные графики у разных каналов."""
    from app.core.schedule import is_open

    assert is_open(TOURS_BOT, _at(MONDAY, 9, 30)) is True
    assert is_open(VISA_BOT, _at(MONDAY, 9, 30)) is False


def test_visits_are_closed_on_sunday_on_both_channels():
    """Решение владельца 09.08 (уточнено после первой редакции гейта): «консультация
    можно хоть каждый день, но записи, когда чел должен придти, — по будням», суббота
    считается рабочей. Это перекрывает документ, где туры значились как «ежедневно»."""
    from app.core.schedule import is_open

    assert is_open(TOURS_BOT, _at(SUNDAY, 15)) is False
    assert is_open(TOURS_BOT, _at(SATURDAY, 15)) is True


# --- что подставляем в промпт --------------------------------------------------

def test_next_open_days_skips_closed_ones():
    from app.core.schedule import next_open_days

    days = next_open_days(VISA_BOT, _at(SATURDAY, 20), count=2)
    assert SUNDAY not in days
    assert days[0] == MONDAY


def test_schedule_note_names_today_and_the_closed_day():
    """Служебная заметка читается моделью на каждом ходу — она обязана называть и
    сегодняшний день, и ближайшие допустимые, иначе модель снова начнёт угадывать."""
    from app.core.schedule import schedule_note

    note = schedule_note(VISA_BOT, _at(SUNDAY, 15))
    assert "воскресень" in note.lower()
    assert "10:00" in note and "19:00" in note
    assert "10.08" in note or "понедельник" in note.lower()


def test_schedule_note_is_channel_specific():
    from app.core.schedule import schedule_note

    assert "09:00" in schedule_note(TOURS_BOT, _at(MONDAY, 12))
    assert "10:00" in schedule_note(VISA_BOT, _at(MONDAY, 12))


# --- детектор нарушения в исходящем тексте -------------------------------------

def test_detects_the_exact_message_that_broke():
    """Дословный текст с прода (сообщение 14956) и со скриншота владельца."""
    from app.core.schedule import violates_schedule

    text = ("Отлично, Кубат! Вас записали на консультацию в воскресенье вечером. "
            "Офис находится в Бишкеке, ул. Тоголок Молдо, 5. Менеджер свяжется с вами, "
            "чтобы уточнить точное время.")
    assert violates_schedule(VISA_BOT, text, _at(SATURDAY, 7, 33)) != ""
    assert violates_schedule(TOURS_BOT, text, _at(SATURDAY, 7, 33)) != ""


def test_a_call_on_sunday_is_allowed():
    """Разговор владелец разрешил в любой день, и глушить его нельзя: бот работает
    ночами, и созвон в воскресенье — нормальная договорённость, а не ошибка."""
    from app.core.schedule import violates_schedule

    text = "Хорошо, тогда созвонимся в воскресенье, менеджер наберёт вас."
    assert violates_schedule(VISA_BOT, text, _at(SATURDAY, 7, 33)) == ""


def test_visit_wording_on_sunday_is_flagged():
    from app.core.schedule import violates_schedule

    text = "Отлично, ждём вас в офисе в воскресенье!"
    assert violates_schedule(VISA_BOT, text, _at(SATURDAY, 7, 33)) != ""


def test_correct_refusal_is_not_flagged():
    """Ложноположительный, обязан пройти: бот ПРАВИЛЬНО объясняет, что воскресенье
    выходной. Такое сообщение трогать нельзя — оно и есть желаемое поведение."""
    from app.core.schedule import violates_schedule

    text = ("Да, воскресенье выходной. Мы работаем пн–сб с 10:00 до 19:00. "
            "Когда вам удобнее — завтра (суббота) или в понедельник?")
    assert violates_schedule(VISA_BOT, text, _at(SATURDAY, 7, 33)) == ""


def test_ordinary_messages_are_not_flagged():
    """Ложноположительные: обычная переписка не должна попадать под детектор."""
    from app.core.schedule import violates_schedule

    for text in ("Здравствуйте! Я Медина, ваш менеджер 😊",
                 "Подскажите, на какие даты планируете поездку?",
                 "Вот что нашлось на 5 октября, 7 ночей, Аланья.",
                 "Стоимость визы в США — 250 долларов."):
        assert violates_schedule(VISA_BOT, text, _at(MONDAY, 12)) == "", text


def test_evening_time_is_flagged_on_both_channels():
    from app.core.schedule import violates_schedule

    text = "Записал вас на понедельник в 20:00, ждём в офисе!"
    assert violates_schedule(VISA_BOT, text, _at(MONDAY, 12)) != ""
    assert violates_schedule(TOURS_BOT, text, _at(MONDAY, 12)) != ""


def test_time_inside_hours_is_fine():
    from app.core.schedule import violates_schedule

    text = "Записал вас на понедельник в 14:00, ждём в офисе!"
    assert violates_schedule(VISA_BOT, text, _at(MONDAY, 12)) == ""


# --- ложноположительные, найденные замером на 1636 реальных сообщениях -----------
# Все четыре случая детектор помечал в первой редакции. Включи мы её как есть —
# бот перестал бы отправлять КОРРЕКТНЫЕ ответы, в том числе те, где он сам называет
# часы работы. Это и есть закон 5 Венома в действии: калибровка на истории до прода.

def test_stating_the_working_hours_is_not_a_proposal():
    """Самый частый ложный: бот верно называет график, а 19:00 в нём — граница, а не
    предложенное время."""
    from app.core.schedule import violates_schedule

    for text in ("Отлично! Наш офис находится в Бишкеке, ул. Тоголок Молдо, 5. "
                 "Мы работаем Пн–Сб с 10:00 до 19:00. Когда вам удобнее прийти?",
                 "Я в чате круглосуточно 😊 А офис работает с 09:00 до 19:00. "
                 "Могу помочь прямо здесь или записать в офис."):
        assert violates_schedule(VISA_BOT, text, _at(MONDAY, 12)) == "", text


def test_flight_times_are_not_appointment_times():
    from app.core.schedule import violates_schedule

    text = ("Понял, два билета: один в 13:40, второй в 19:10. "
            "Уточню: это для туристов из офиса или для вас?")
    assert violates_schedule(TOURS_BOT, text, _at(MONDAY, 12)) == ""


def test_a_date_is_not_a_time():
    """«вылет 05.08» — это дата, а не 05:08."""
    from app.core.schedule import violates_schedule

    text = ("Отлично! CARMEN SUITE в Аланье, вылет 05.08, 7 ночей, 4 звезды, от 1290 EUR. "
            "Давайте забронируем? Удобнее подойти в офис завтра?")
    assert violates_schedule(TOURS_BOT, text, _at(MONDAY, 12)) == ""


def test_kyrgyz_refusal_is_not_flagged():
    """Бот на кыргызском ПРАВИЛЬНО говорит, что сегодня закрыто. Слова-исключения
    обязаны знать не только русский: половина клиентов пишет на кыргызском."""
    from app.core.schedule import violates_schedule

    text = ("Офис: г. Бишкек, ул. Тоголок Молдо, 5. Бүгүн (воскресенье) жабык. "
            "Дүйшөмбүдөн баштап 09:00–19:00 иштейбиз. Эртең келе аласызбы?")
    assert violates_schedule(TOURS_BOT, text, _at(SUNDAY, 12)) == ""
