"""Определение английского клиента и языковая заметка в ходе.

Замер прода 19.08.2026: из 21 англоязычного сообщения за месяц 18 получили ответ
по-русски. Правило «отвечай на языке клиента» жило в системном промпте, но весь промпт
и персона написаны по-русски, и модель уезжала в русский. Лечим тем же приёмом, что
дату (09.07) и график приёма (09.08): служебной заметкой на конкретный ход.

Ловушка, ради которой тесты и написаны: латиница ≠ английский. На проде латиницей
приходят названия отелей («KIMEROS PARK HOLIDAY VILLAGE 5») и транслит («Assalamu
alekum», «Aibike elmarby») — от русско- и кыргызоязычных клиентов.
"""
from app.core.lang import looks_english


def test_english_client_is_detected():
    assert looks_english("Hello! Can I get more info on this?") is True
    assert looks_english("Do you help with tourist visa to Europe?") is True
    assert looks_english("hi") is True


def test_hotel_names_and_translit_are_not_english():
    assert looks_english("*KIMEROS PARK HOLIDAY VILLAGE 5*") is False
    assert looks_english("Antalya Kremlin Kristal Barut Sera") is False
    assert looks_english("Assalamu alekum") is False
    assert looks_english("Aibike elmarby") is False


def test_russian_and_kyrgyz_are_not_english():
    assert looks_english("здравствуйте, нужна виза в Италию") is False
    assert looks_english("Саламатсызбы, виза керек эле") is False
    assert looks_english("") is False


def test_mixed_message_with_hotel_name_stays_russian():
    """Русский текст с латинским названием отеля — по-прежнему русский клиент."""
    assert looks_english("Здравствуйте, интересует AKKA ALINDA HOTEL на 7 ночей") is False
