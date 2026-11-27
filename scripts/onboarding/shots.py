"""Скриншоты для docs/onboarding/kak-rabotat-v-paneli.md. Нужен запущенный stand.py.

    .venv\\Scripts\\python.exe shots.py            все шаги
    .venv\\Scripts\\python.exe shots.py 05 06      только шаги с такими номерами

Стенд после прогона «грязный» (ответы отправлены, лид закрыт) — для повторного
прогона перезапустите stand.py.
"""
import os
import sys
import traceback

from playwright.sync_api import sync_playwright

B = os.environ.get("STAND_URL", "http://127.0.0.1:8111")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
IMG = os.path.join(REPO, "docs", "onboarding", "img")
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(IMG, exist_ok=True)
DESK = {"width": 1366, "height": 900}
MOB = {"width": 390, "height": 844}
ONLY = set(sys.argv[1:])
RESULTS = []

# Памятка для отправки клиенту — выдуманный минимальный PDF.
PDF = os.path.join(HERE, "pamyatka-dokumenty-ssha.pdf")
with open(PDF, "wb") as fh:
    fh.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
             b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")

MARK_JS = """([sels, labels]) => {
  document.querySelectorAll('.__mark').forEach(e => e.remove());
  sels.forEach((sel, i) => {
    let el = null;
    try { el = typeof sel === 'string' ? document.querySelector(sel) : null; } catch (e) {}
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (!r.width) return;
    const d = document.createElement('div');
    d.className = '__mark';
    d.style.cssText = `position:fixed;left:${r.left-5}px;top:${r.top-5}px;width:${r.width+10}px;`
      + `height:${r.height+10}px;border:3px solid #e11d48;border-radius:10px;z-index:99999;`
      + `pointer-events:none;box-shadow:0 0 0 3px rgba(225,29,72,.18)`;
    document.body.appendChild(d);
    const lab = labels && labels[i];
    if (lab) {
      const b = document.createElement('div');
      b.className = '__mark';
      b.textContent = lab;
      b.style.cssText = `position:fixed;left:${Math.max(4, r.left-14)}px;top:${Math.max(4, r.top-16)}px;`
        + `min-width:26px;height:26px;padding:0 6px;border-radius:13px;background:#e11d48;color:#fff;`
        + `font:700 15px/26px system-ui,sans-serif;text-align:center;z-index:100000;pointer-events:none`;
      document.body.appendChild(b);
    }
  });
}"""


def mark(pg, sels, labels=None):
    """Обвести элементы красной рамкой. sels — CSS-селекторы или Locator'ы."""
    css = []
    for i, sel in enumerate(sels):
        if isinstance(sel, str):
            css.append(sel)
        else:   # Locator → временный атрибут, чтобы найти его из JS
            sel.first.evaluate(f"e => e.setAttribute('data-mark', 'm{i}')")
            css.append(f"[data-mark=m{i}]")
    pg.evaluate(MARK_JS, [css, labels or []])


def unmark(pg):
    pg.evaluate("() => { document.querySelectorAll('.__mark').forEach(e => e.remove());"
                " document.querySelectorAll('[data-mark]').forEach(e => e.removeAttribute('data-mark')); }")


def shot(pg, name, full=False):
    path = os.path.join(IMG, f"{name}.png")
    pg.screenshot(path=path, full_page=full)
    unmark(pg)
    print("  shot", name)
    return path


def login(pg, user):
    pg.goto(B + "/admin/login")
    pg.fill("input[name=login]", user)
    pg.fill("input[name=password]", "demo")
    pg.click("button[type=submit]")
    pg.wait_for_load_state("networkidle")


def settle(pg, ms=700):
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(ms)


def open_chat_from_inbox(pg, name):
    pg.goto(B + "/admin")
    settle(pg)
    pg.locator("[data-attention] .card, .inbox-list .card", has_text=name).first.click()
    pg.wait_for_selector("#chat .chat-palma", timeout=15000)
    settle(pg, 900)


def step(num, title):
    def deco(fn):
        def run(browser):
            if ONLY and num not in ONLY:
                return
            print(num, title)
            try:
                fn(browser)
                RESULTS.append((num, title, "OK", ""))
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                RESULTS.append((num, title, "FAIL", repr(exc)[:200]))
        run.num = num
        return run
    return deco


def page(browser, vp=DESK, user=None):
    ctx = browser.new_context(viewport=vp, locale="ru-RU", timezone_id="Asia/Bishkek",
                              device_scale_factor=1 if vp is DESK else 2,
                              is_mobile=vp is MOB, has_touch=vp is MOB)
    pg = ctx.new_page()
    if user:
        login(pg, user)
    return pg


# ---------------------------------------------------------------------------------------
@step("01", "вход")
def s01(br):
    pg = page(br)
    pg.goto(B + "/admin/login")
    settle(pg)
    pg.fill("input[name=login]", "medina")
    pg.fill("input[name=password]", "demo")
    mark(pg, ["input[name=login]", "input[name=password]", "button[type=submit]"], ["1", "2", "3"])
    shot(pg, "01-vhod")
    pg.fill("input[name=password]", "nepravilno")
    pg.click("button[type=submit]")
    settle(pg)
    mark(pg, [".error, .alert, .login-error, [role=alert]"])
    shot(pg, "01b-vhod-oshibka")
    pg.context.close()


@step("02", "главная — Кому ответить сейчас")
def s02(br):
    pg = page(br, user="medina")
    settle(pg)
    assert "/admin/focus" in pg.url, pg.url
    mark(pg, [".focus-h", ".lead", ".queue.today", ".queue:not(.today)"], ["1", "2", "3", "4"])
    shot(pg, "02-glavnaya")
    pg.context.close()


@step("03", "входящие")
def s03(br):
    pg = page(br, user="medina")
    pg.goto(B + "/admin")
    settle(pg)
    first = pg.locator(".inbox-list .card, [data-attention] .card").first
    mark(pg, [".tab[data-tab=inbox]", first, pg.locator("text=/ждёт \\d+/").first, "input[type=search], input[name=q]"],
         ["1", "2", "3", "4"])
    shot(pg, "03-vhodyaschie")
    pg.context.close()


@step("04", "переписка: открыть, ответить, файл, вернуть боту")
def s04(br):
    pg = page(br, user="medina")
    open_chat_from_inbox(pg, "Айгерим")
    mark(pg, [".chat-who", "#chat .chat-log, #chat .chat-messages", "#chat textarea[name=text]"],
         ["1", "2", "3"])
    shot(pg, "04-chat-otkryt")
    print("  visa-fields form in chat:", pg.locator("#chat form[hx-post$='/visa-fields']").count(),
          "| 'Гражданство' on page:", pg.locator("text=Гражданство").count())
    ta = pg.locator("#chat textarea[name=text]")
    ta.fill("Здравствуйте, Айгерим! Да, в субботу офис работает с 10:00 до 15:00. "
            "Записать вас на 11:00?")
    mark(pg, ["#chat textarea[name=text]", "#chat .chat-send"], ["1", "2"])
    shot(pg, "05-chat-otvet-nabran")
    pg.click("#chat .chat-send")
    pg.wait_for_timeout(1500)
    settle(pg)
    mark(pg, [".chat-who", pg.locator("#chat .chat-who-btn", has_text="Вернуть боту")], ["1", "2"])
    shot(pg, "06-chat-otvet-otpravlen")
    # файл
    pg.set_input_files("#chat input[type=file][name=upload]", PDF)
    pg.wait_for_timeout(500)
    pg.fill("#chat .chat-file input[name=caption]", "Документы на США")
    mark(pg, [".chat-attach", "#chat .chat-file.is-simple"], ["1", "2"])
    shot(pg, "07-chat-fail")
    pg.click("#chat .chat-file.is-simple button[type=submit]")
    pg.wait_for_timeout(1500)
    settle(pg)
    shot(pg, "07b-chat-fail-otpravlen")
    # «Напомнить» — поставить себе звонок на завтра
    pg.locator("#chat .chat-remind > summary").click()
    pg.wait_for_timeout(400)
    pg.fill("#chat .chat-remind-form input[name=comment]", "Перезвонить, подтвердить запись на субботу")
    mark(pg, ["#chat .chat-remind > summary", "#chat .chat-remind-form"], ["1", "2"])
    shot(pg, "07c-chat-napomnit")
    pg.context.close()


@step("07", "поиск")
def s07(br):
    pg = page(br, user="medina")
    pg.goto(B + "/admin")
    settle(pg)
    box = pg.locator("input[type=search], input[name=q]").first
    box.fill("0106")
    pg.wait_for_timeout(1500)
    settle(pg)
    mark(pg, [box, pg.locator(".inbox-list .card, [data-attention] .card").first], ["1", "2"])
    shot(pg, "03b-poisk")
    pg.context.close()


@step("08", "меню чата и закрытие лида")
def s08(br):
    pg = page(br, user="medina")
    open_chat_from_inbox(pg, "Нурлан")
    pg.click("#chat details.chat-menu > summary")
    pg.wait_for_timeout(400)
    mark(pg, ["#chat details.chat-menu > summary", "#chat .chat-menu-body .chat-outcomes"], ["1", "2"])
    shot(pg, "08-chat-menyu")
    pg.locator("#chat .chat-menu-body .chat-chip", has_text="Клиент отказался").first.click()
    pg.wait_for_timeout(1200)
    if not pg.locator("#chat details.chat-menu[open]").count():
        pg.click("#chat details.chat-menu > summary")
        pg.wait_for_timeout(400)
    mark(pg, ["#chat .chat-lost-reasons"])
    shot(pg, "09-prichina-otkaza")
    pg.locator("#chat .chat-lost-reasons .chat-chip", has_text="Высокая стоимость услуг").click()
    pg.wait_for_timeout(1200)
    if not pg.locator("#chat details.chat-menu[open]").count():
        pg.click("#chat details.chat-menu > summary")
        pg.wait_for_timeout(400)
    mark(pg, ["#chat .chat-lost-reasons .chat-chip.selected",
              "#chat .chat-menu-body .chat-outcomes .chat-chip.selected"])
    shot(pg, "10-prichina-vybrana")
    pg.context.close()


@step("11", "доска виз")
def s11(br):
    pg = page(br, user="medina")
    pg.goto(B + "/admin")
    settle(pg)
    pg.click(".tab[data-funnel=visa]")
    pg.wait_for_selector("#board [data-board]", timeout=20000)
    settle(pg, 1200)
    mark(pg, ["#board .col[data-col=greeting] .col-head", "#board .col[data-col=qualification] .col-head",
              "#board .stat.needs-reply", "#board .stat.mine-filter", "#board .col-more"],
         ["1", "2", "3", "4", "5"])
    shot(pg, "11-doska-viz")
    pg.evaluate("() => { const b = document.querySelector('#board .board'); b.scrollLeft = b.scrollWidth; }")
    pg.wait_for_timeout(500)
    mark(pg, ["#board .col[data-col=silent] .col-head", "#board .col[data-col=follow_up] .col-head",
              "#board .col[data-col=office] .col-head", "#board .col[data-col=manager] .col-head"],
         ["4", "5", "6", "7"])
    shot(pg, "11b-doska-viz-dalshe")
    pg.evaluate("() => { const b = document.querySelector('#board .board'); b.scrollLeft = 0; }")
    more = pg.locator("#board .col-more").first
    more.scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    mark(pg, [more])
    shot(pg, "11c-doska-eschyo-pokazat-vse")
    pg.goto(B + "/admin"); settle(pg)
    pg.click(".tab[data-funnel=visa]")
    pg.wait_for_selector("#board [data-board]", timeout=20000)
    settle(pg, 1000)
    # перетаскивание: Азамат из «Новый лид» в «В работе»
    card = pg.locator("#board .col[data-col=greeting] .card", has_text="Азамат").first
    target = pg.locator("#board .col[data-col=qualification]")
    card.scroll_into_view_if_needed()
    cb = card.bounding_box()
    tb = target.bounding_box()
    pg.mouse.move(cb["x"] + 40, cb["y"] + 20)
    pg.mouse.down()
    for k in range(1, 16):
        pg.mouse.move(cb["x"] + 40 + (tb["x"] + 60 - cb["x"] - 40) * k / 15,
                      cb["y"] + 20 + (tb["y"] + 70 - cb["y"] - 20) * k / 15)
        pg.wait_for_timeout(40)
    pg.mouse.up()
    pg.wait_for_timeout(1500)
    settle(pg)
    moved = pg.locator("#board .col[data-col=qualification] .card", has_text="Азамат").count()
    print("  drag moved:", moved)
    mark(pg, [pg.locator("#board .col[data-col=qualification] .card", has_text="Азамат")])
    shot(pg, "12-doska-peretaschil")
    # фильтр «Требуют ответа»
    pg.click("#board .stat.needs-reply")
    pg.wait_for_timeout(700)
    mark(pg, ["#board .stat.needs-reply"])
    shot(pg, "13-doska-trebuyut-otveta")
    pg.click("#board .stat.needs-reply")
    # «Мои лиды»
    pg.click("#board .stat.mine-filter")
    pg.wait_for_timeout(1500)
    settle(pg)
    mark(pg, ["#board .stat.mine-filter"])
    shot(pg, "14-doska-moi-lidy")
    pg.context.close()


@step("15", "мои дела и касания")
def s15(br):
    pg = page(br, user="medina")
    pg.goto(B + "/admin/calendar")
    settle(pg)
    task = pg.locator("text=Касание 1").first.locator("xpath=ancestor::*[.//button[contains(., 'Сделано')]][1]")
    mark(pg, ["a.nav-link[href='/admin/calendar']", task,
              pg.locator("button", has_text="Сделано").first,
              pg.locator("text=Открыть чат").first], ["1", "2", "3", "4"])
    shot(pg, "15-moi-dela-kasaniya")
    pg.locator("button", has_text="Сделано").first.click()
    pg.wait_for_timeout(1500)
    settle(pg)
    shot(pg, "16-kasanie-sdelano")
    pg.context.close()


@step("17", "договоры")
def s17(br):
    pg = page(br, user="medina")
    open_chat_from_inbox(pg, "Бакыт")
    pg.click("#chat details.chat-menu > summary")
    pg.wait_for_timeout(400)
    mark(pg, [pg.locator("#chat .chat-menu-action", has_text="Открыть карточку до договора"),
              pg.locator("#chat .chat-menu-action", has_text="Договор подписан")], ["1", "2"])
    shot(pg, "17-chat-menyu-dogovor")
    pg.locator("#chat .chat-menu-action", has_text="Открыть карточку до договора").click()
    settle(pg)
    shot(pg, "17b-kartochka-do-dogovora", full=True)
    open_chat_from_inbox(pg, "Бакыт")
    pg.click("#chat details.chat-menu > summary")
    pg.wait_for_timeout(400)
    pg.locator("#chat .chat-menu-action", has_text="Договор подписан").click()
    settle(pg)
    shot(pg, "18-forma-dogovora", full=True)
    pg.goto(B + "/admin/work")
    settle(pg)
    shot(pg, "19-dogovory-v-rabote")
    pg.context.close()


@step("20", "меню Ещё")
def s20(br):
    pg = page(br, user="medina")
    pg.click("details.more-nav > summary")
    pg.wait_for_timeout(400)
    mark(pg, ["details.more-nav .more-pop"])
    shot(pg, "20-menyu-eschyo")
    pg.context.close()


@step("21", "телефон")
def s21(br):
    pg = page(br, vp=MOB, user="medina")
    settle(pg)
    shot(pg, "21-tel-glavnaya")
    pg.goto(B + "/admin")
    settle(pg)
    shot(pg, "22-tel-vhodyaschie")
    pg.locator(".inbox-list .card, [data-attention] .card", has_text="Азамат").first.click()
    pg.wait_for_selector("#chat .chat-palma", timeout=15000)
    settle(pg, 900)
    shot(pg, "23-tel-chat")
    pg.goto(B + "/admin")
    settle(pg)
    pg.click(".tab[data-funnel=visa]")
    pg.wait_for_selector("#board [data-board]", timeout=20000)
    settle(pg, 1000)
    shot(pg, "24-tel-doska")
    pg.goto(B + "/admin/calendar")
    settle(pg)
    shot(pg, "25-tel-moi-dela")
    pg.context.close()


@step("26", "туры (Даулет)")
def s26(br):
    pg = page(br, user="daulet")
    settle(pg)
    shot(pg, "26-tury-glavnaya")
    pg.goto(B + "/admin")
    settle(pg)
    tab = pg.locator(".tab[data-funnel=tours]")
    tab.click()
    pg.wait_for_selector("#board [data-board]", timeout=20000)
    settle(pg, 1000)
    mark(pg, [".tab[data-funnel=tours]", "#board .board"], ["1", "2"])
    shot(pg, "27-tury-doska")
    pg.context.close()


if __name__ == "__main__":
    steps = [v for k, v in list(globals().items()) if callable(v) and hasattr(v, "num")]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for st in steps:
            st(browser)
        browser.close()
    print("\nИТОГ:")
    for r in RESULTS:
        print(" ", *r)
