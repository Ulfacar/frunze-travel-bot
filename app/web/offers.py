"""Страница подборки туров: `https://<домен>/t/<slug>` — «Подробнее здесь» из сообщения бота.

Зачем своя страница, а не ссылка TourVisor. Менеджеры шлют клиенту `tourcart.ru/?tvcard=…`,
и владелец просил то же самое у бота. Разведка 11.08 (`scripts/tourvisor_probe.py`) показала:
в ответе XML-шлюза нет ни одного вхождения `tvcard`/`tourcart` — эта ссылка рождается в
кабинете менеджера, программно её не собрать. Зато в ответе есть фото, описание, рейтинг и
расстояние до моря, то есть всё, из чего страница делается своими руками.

Своя страница вдобавок ведёт в НАШУ воронку. Ровно из-за обратного 03.08 убрали гугл-ссылки:
бот доводил оплаченного рекламой клиента до подбора и сам отправлял его в выдачу, где рядом
Booking и цены конкурентов.

Приватность: slug неугадываемый, страница закрыта от индексации, и на ней нет ничего о
клиенте — ни телефона, ни имени, ни истории переписки. Только туры, которые ему уже прислали
в чат.
"""
from __future__ import annotations

import html
import logging
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update

log = logging.getLogger("tour_offers")

router = APIRouter(tags=["offers"])

SLUG_ALPHABET = "abcdefghijkmnopqrstuvwxyz23456789"  # без похожих символов: l/1, o/0
SLUG_LEN = 10


def _slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LEN))


async def create_offer(found, state) -> str:
    """Сохранить подборку и вернуть ссылку. Пусто — сообщение уйдёт без ссылки.

    Никогда не поднимает исключение: подборка в чате важнее страницы.
    """
    from app.config import settings
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        return ""
    try:
        from app.integrations.crm.db import TourOffer, get_sessionmaker
        from app.integrations.tourvisor.cards import offer_items

        items = offer_items(found.hotels, departure=found.departure)
        if not items:
            return ""
        slug = _slug()
        payload = {
            "items": items,
            "fallback_departure": bool(getattr(found, "fallback_departure", False)),
        }
        sm = get_sessionmaker()
        async with sm() as session:
            session.add(TourOffer(slug=slug, user_id=getattr(state, "user_id", ""),
                                  bot_id=getattr(state, "bot_id", ""),
                                  departure=found.departure or "", payload=payload))
            await session.commit()
        return f"{base}/t/{slug}"
    except Exception:  # noqa: BLE001 — страница не стоит потерянного ответа клиенту
        log.warning("подборка не сохранена (key=%s)", getattr(state, "user_id", ""),
                    exc_info=True)
        return ""


@router.get("/t/{slug}", response_class=HTMLResponse)
async def offer_page(slug: str, request: Request) -> HTMLResponse:
    """Витрина подборки. Публичная намеренно: клиент открывает её из WhatsApp, без логина."""
    from app.integrations.crm.db import TourOffer, get_sessionmaker
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            offer = (await session.execute(
                select(TourOffer).where(TourOffer.slug == slug))).scalar_one_or_none()
            if offer is not None:
                # Счётчик просмотров — будущий сигнал менеджеру «клиент смотрит подборку».
                await session.execute(update(TourOffer).where(TourOffer.slug == slug)
                                      .values(views=(offer.views or 0) + 1))
                await session.commit()
    except Exception:  # noqa: BLE001
        log.warning("страница подборки не открылась (slug=%s)", slug, exc_info=True)
        offer = None
    if offer is None:
        return HTMLResponse(_not_found(), status_code=404)
    return HTMLResponse(_page(offer))


def _esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _card_html(item: dict) -> str:
    stars = f"{_esc(item['stars'])}★" if item.get("stars") else ""
    rating = f"<span class=\"rate\">{_esc(item['rating'])}</span>" if item.get("rating") else ""
    photo = (f"<img src=\"{_esc(item['picture'])}\" alt=\"\" loading=\"lazy\">"
             if item.get("picture") else "")
    where = ", ".join(x for x in (item.get("country"), item.get("region")) if x)
    route = f"{_esc(item['departure'])} → {_esc(where)}" if item.get("departure") else _esc(where)
    sea = (f"<li>до моря {_esc(item['seadistance'])} м</li>"
           if item.get("seadistance") else "")
    facts = "".join(f"<li>{_esc(x)}</li>" for x in (
        " · ".join(y for y in (item.get("flydate"),
                               f"{item['nights']} ночей" if item.get("nights") else "") if y),
        " · ".join(y for y in (item.get("room"), item.get("people")) if y),
        item.get("meal"),
        item.get("operator"),
    ) if x)
    desc = (f"<p class=\"desc\">{_esc(item['description'])}</p>"
            if item.get("description") else "")
    return f"""
    <article class="card">
      <div class="photo">{photo}</div>
      <div class="body">
        <h2>{_esc(item['name'])} <span class="stars">{stars}</span> {rating}</h2>
        <p class="route">{route}</p>
        <ul class="facts">{facts}{sea}</ul>
        {desc}
        <p class="price">{_esc(item['price'])} <span>{_esc(item['currency'])}</span></p>
      </div>
    </article>"""


def _page(offer) -> str:
    """Кнопки «написать» здесь намеренно нет.

    Клиент открывает страницу из чата, где ему эту подборку и прислали: увести его на
    отдельный контакт — значит потерять диалог, в котором уже собраны даты, состав и бюджет.
    Достаточно подсказать, что ответить в том же чате.
    """
    payload = offer.payload or {}
    items = payload.get("items") or []
    note = ("Вылет из Алматы — из Бишкека на эти даты туров нет."
            if payload.get("fallback_departure") else "")
    return _SHELL.format(
        cards="".join(_card_html(item) for item in items),
        count=len(items),
        note=f"<p class=\"note\">{_esc(note)}</p>" if note else "",
        button="<p class=\"cta\">Понравился вариант? Напишите название отеля в чат — "
               "менеджер проверит наличие мест и забронирует.</p>",
    )


def _not_found() -> str:
    return _SHELL.format(
        cards="<p class=\"empty\">Такой подборки нет — возможно, ссылка устарела. "
              "Напишите в чат, менеджер пришлёт актуальные варианты.</p>",
        count=0, note="", button="")


# Токены — из макета календаря (тил/оранж), который владелец утвердил 12.07. Светлая и тёмная
# тема, телефон первым: подборку открывают из WhatsApp.
_SHELL = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Подборка туров · Frunze Travel</title>
<style>
  :root {{
    --bg:#F7F5F1; --card:#FFFFFF; --ink:#1B1B1A; --muted:#6B6B66;
    --teal:#0E5C57; --orange:#DB7526; --line:#E6E2DA;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141613; --card:#1E211E; --ink:#F2F0EB; --muted:#A7A79F;
             --teal:#5FB3AC; --orange:#E8975A; --line:#2C302C; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  header {{ padding:24px 20px 8px; max-width:720px; margin:0 auto; }}
  header h1 {{ font-size:22px; margin:0 0 4px; color:var(--teal); }}
  header p {{ margin:0; color:var(--muted); font-size:14px; }}
  main {{ max-width:720px; margin:0 auto; padding:12px 20px 40px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
           overflow:hidden; margin:14px 0; }}
  .photo img {{ width:100%; height:200px; object-fit:cover; display:block; }}
  .body {{ padding:14px 16px 16px; }}
  h2 {{ font-size:17px; margin:0 0 6px; line-height:1.35; }}
  .stars {{ color:var(--orange); }}
  .rate {{ font-size:13px; color:var(--muted); font-weight:400; }}
  .route {{ margin:0 0 10px; color:var(--muted); font-size:14px; }}
  .facts {{ list-style:none; margin:0 0 10px; padding:0; font-size:14px; }}
  .facts li {{ padding:2px 0; }}
  .desc {{ margin:0 0 10px; font-size:13px; color:var(--muted); }}
  .price {{ margin:0; font-size:20px; font-weight:600; color:var(--teal); }}
  .price span {{ font-size:14px; font-weight:400; text-transform:uppercase; }}
  .note {{ background:rgba(219,117,38,.12); border-left:3px solid var(--orange);
           padding:10px 12px; border-radius:8px; font-size:14px; }}
  .cta {{ display:block; text-align:center; background:var(--teal); color:#fff;
          text-decoration:none; padding:14px; border-radius:12px; font-weight:600;
          margin:20px 0 8px; }}
  .empty {{ padding:24px 0; color:var(--muted); }}
  footer {{ max-width:720px; margin:0 auto; padding:0 20px 40px;
            color:var(--muted); font-size:13px; }}
</style>
</head><body>
<header>
  <h1>Подборка туров</h1>
  <p>Вариантов: {count}</p>
</header>
<main>
  {note}
  {cards}
  {button}
</main>
<footer>Цены и наличие мест меняются в течение дня — точную стоимость подтвердит менеджер.</footer>
</body></html>"""
