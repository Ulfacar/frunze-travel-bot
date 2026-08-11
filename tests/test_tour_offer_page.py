"""ГЕЙТ: страница подборки `/t/<slug>` — та самая «Подробнее здесь» из сообщения бота.

Написан ДО реализации, исполнителем НЕ редактируется. ТЗ: `docs/task-tours-cards-v1.md`.

Владелец: «Гриша хочет её видеть, чтобы люди сами просматривали». Менеджеры шлют
`tourcart.ru/?tvcard=…`; разведка 11.08 показала, что в ответе XML-шлюза нет ни одного
вхождения `tvcard` — их ссылку собрать нельзя, поэтому страница наша.

Отдельно закреплены два свойства, которые легко потерять:
* страница ПУБЛИЧНА — её открывает клиент из WhatsApp, логина у него нет;
* на ней нет ничего о клиенте: ни телефона, ни имени, ни переписки. Только туры.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main
from app.config import settings
from app.core.state import DialogState
from app.integrations.crm import db as crm_db
from app.integrations.crm.db import Base, TourOffer
from app.integrations.tourvisor.client import TourSearch
from app.web import offers

PHONE = "996700555444"
USER_ID = f"frunze_tours:{PHONE}"


def _hotel(name="FIRST CLASS HOTEL", price=2765):
    return {
        "hotelname": name, "hotelstars": 5, "hotelrating": "3.5",
        "picturelink": "https://static.tourvisor.ru/hotel_pics/main400/1188.jpg",
        "hoteldescription": "реновация в 2024, аквапарк", "countryname": "Турция",
        "regionname": "Аланья", "seadistance": 50,
        "tours": {"tour": [{
            "price": price, "nights": 8, "operatorname": "Kompas (KZ)",
            "flydate": "20.08.2026", "adults": 3, "child": 1,
            "room": "standard room land view", "mealrussian": "AI - Все Включено",
            "tourid": "90264112887701", "currency": "EUR",
        }]},
    }


@pytest.fixture()
def offer_db(tmp_path, monkeypatch):
    """Своя SQLite под таблицу подборок — доменную БД теста не трогаем."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'offers.db').as_posix()}"

    async def _init():
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_init())
    sm = async_sessionmaker(create_async_engine(url, poolclass=NullPool),
                            expire_on_commit=False)
    monkeypatch.setattr(crm_db, "get_sessionmaker", lambda: sm)
    monkeypatch.setattr(settings, "public_base_url", "https://frunzetravel.kg", raising=False)
    return sm


def _create(found=None, state=None) -> str:
    found = found or TourSearch(lines=[], found=2, reason="ok", departure="Бишкек",
                                hotels=[_hotel(), _hotel("MC BEACH RESORT", 3409)])
    state = state or DialogState(user_id=USER_ID, funnel="tours", bot_id="frunze_tours")
    return asyncio.run(offers.create_offer(found, state))


def test_link_points_to_our_domain(offer_db):
    url = _create()
    assert url.startswith("https://frunzetravel.kg/t/")
    assert len(url.rsplit("/", 1)[1]) >= 8, "slug должен быть неугадываемым"


def test_page_shows_every_hotel_with_price(offer_db):
    slug = _create().rsplit("/", 1)[1]
    with TestClient(main.app) as client:
        resp = client.get(f"/t/{slug}")
    assert resp.status_code == 200
    body = resp.text
    assert "FIRST CLASS HOTEL" in body and "MC BEACH RESORT" in body
    assert "2 765" in body and "3 409" in body
    assert "standard room land view" in body and "Все Включено" in body


def test_page_shows_photos_and_description(offer_db):
    """Ровно то, чего не хватало в чате: фото и описание отеля."""
    slug = _create().rsplit("/", 1)[1]
    with TestClient(main.app) as client:
        body = client.get(f"/t/{slug}").text
    assert "static.tourvisor.ru/hotel_pics" in body
    assert "аквапарк" in body


def test_page_is_public_but_admin_is_not(offer_db):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: витрина открыта клиенту, панель менеджеров — нет."""
    slug = _create().rsplit("/", 1)[1]
    with TestClient(main.app) as client:
        assert client.get(f"/t/{slug}").status_code == 200
        # Идём по редиректам целиком: `/admin/` сначала отдаёт 307 на нормализацию слеша,
        # и проверка кода одного шага скрыла бы, чем всё кончилось.
        admin = client.get("/admin/", follow_redirects=True)
    assert admin.url.path.endswith("/login"), "панель без входа показываться не должна"


def test_page_leaks_no_client_data(offer_db):
    """На витрине нет ни телефона, ни ключа диалога: ссылку могут переслать кому угодно."""
    slug = _create().rsplit("/", 1)[1]
    with TestClient(main.app) as client:
        body = client.get(f"/t/{slug}").text
    assert PHONE not in body and USER_ID not in body


def test_page_is_not_indexed(offer_db):
    slug = _create().rsplit("/", 1)[1]
    with TestClient(main.app) as client:
        body = client.get(f"/t/{slug}").text
    assert "noindex" in body


def test_unknown_slug_is_404(offer_db):
    with TestClient(main.app) as client:
        resp = client.get("/t/nosuchslug")
    assert resp.status_code == 404
    assert "устарела" in resp.text


def test_almaty_fallback_is_stated_on_the_page(offer_db):
    """Вылет подменён на Алматы — клиент обязан увидеть это и на странице тоже."""
    found = TourSearch(lines=[], found=1, reason="ok", departure="Алматы",
                       fallback_departure=True, hotels=[_hotel()])
    slug = _create(found=found).rsplit("/", 1)[1]
    with TestClient(main.app) as client:
        body = client.get(f"/t/{slug}").text
    assert "Алматы" in body


def test_no_public_base_url_means_no_link(offer_db, monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: адрес не задан — ссылки нет, но и падения нет."""
    monkeypatch.setattr(settings, "public_base_url", "", raising=False)
    assert _create() == ""


def test_offer_survives_empty_hotels(offer_db):
    found = TourSearch(lines=[], found=0, reason="ok", departure="Бишкек", hotels=[])
    assert _create(found=found) == ""


def test_views_are_counted(offer_db):
    """Счётчик просмотров — будущий сигнал менеджеру «клиент смотрит подборку»."""
    slug = _create().rsplit("/", 1)[1]
    with TestClient(main.app) as client:
        client.get(f"/t/{slug}")
        client.get(f"/t/{slug}")

    async def _views():
        async with offer_db() as session:
            offer = await session.get(TourOffer, slug)
            return offer.views
    assert asyncio.run(_views()) == 2
