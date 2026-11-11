# -*- coding: utf-8 -*-
"""Касания до договора — напоминания МЕНЕДЖЕРУ (ответы Медины 11.11.2026).

Главный риск здесь не «сработает ли», а «по кому сработает». Формула взята своя, а не
`leadstate.is_silent` от автодожима: тот исключает перехваченные менеджером диалоги,
а касания Медины нужны ровно по её клиентам, которых она ведёт сама. Если бы касания
встали на `is_silent`, мы бы напоминали не про тех людей и молчали про тех, кто нужен.

Второй риск — объём. Сухой прогон дожима 07.09.2026 показал, что первое включение
отправило бы 818 сообщений залпом. Поэтому проверяем и ограничители.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core import touches

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def conv(**kw):
    base = dict(user_id="getvisa:996700000001", phone="996700000001", funnel="visa",
                channel="whatsapp", bot_id="getvisa", stage="qualification",
                intercepted=True, archived=False, outcome="", last_sender="manager",
                last_message_at=NOW - timedelta(days=2), assigned_to="medina")
    base.update(kw)
    return SimpleNamespace(**base)


def cfg(**kw):
    base = dict(touch_after_days=[1, 3, 6], touch_funnels=["visa"],
                touch_batch_limit=20, touch_max_age_days=30)
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_first_touch_comes_due_after_a_day_of_silence():
    """Её график: первое касание через 1 день, и текст — её собственный."""
    targets = touches.select_touch_targets([conv()], NOW, cfg())

    assert len(targets) == 1
    assert targets[0]["number"] == 1
    assert targets[0]["owner"] == "medina"
    assert "актуален ли для вас ещё вопрос оформления визы" in targets[0]["text"]


def test_a_fresh_conversation_is_not_touched():
    """Писали час назад — напоминать не о чем."""
    fresh = conv(last_message_at=NOW - timedelta(hours=1))
    assert touches.select_touch_targets([fresh], NOW, cfg()) == []


def test_an_intercepted_dialog_is_included_unlike_the_bot_followup():
    """Перехваченный диалог — ГЛАВНЫЙ случай, а не исключение.

    `leadstate.is_silent` такие отбрасывает: бот не пишет туда, где говорит человек.
    Касания же существуют именно для клиентов, которых менеджер ведёт сам.
    """
    from app.core.leadstate import is_silent

    taken = conv(intercepted=True)
    followup_cfg = SimpleNamespace(followup_max_pings=2, followup_after_hours=24,
                                   followup_interval_hours=84, followup_count=0)
    assert is_silent(taken, NOW, followup_cfg) is False, "дожим такие пропускает"
    assert len(touches.select_touch_targets([taken], NOW, cfg())) == 1


def test_a_client_waiting_for_us_is_not_a_touch():
    """Последним писал КЛИЕНТ — он ждёт нас. Это сторож «клиент ждёт», не касание."""
    waiting = conv(last_sender="client")
    assert touches.select_touch_targets([waiting], NOW, cfg()) == []


def test_an_unassigned_lead_has_nobody_to_remind():
    """Задачу ставим владельцу; нераспределённые лиды разбирает админ отдельно."""
    assert touches.select_touch_targets([conv(assigned_to="")], NOW, cfg()) == []


def test_other_directions_are_left_alone():
    """Пока только визы: по турам касания никто не заказывал."""
    assert touches.select_touch_targets([conv(funnel="tours")], NOW, cfg()) == []


def test_terminal_and_archived_leads_are_skipped():
    """Выигранный, потерянный и архивный клиент напоминаний не получает."""
    for kw in ({"outcome": "won"}, {"outcome": "lost"}, {"archived": True}):
        assert touches.select_touch_targets([conv(**kw)], NOW, cfg()) == [], kw


def test_the_schedule_walks_one_three_six():
    """Второе касание — через 3 дня, третье — через 6, четвёртого нет."""
    two_days = conv(last_message_at=NOW - timedelta(days=2))
    six_days = conv(last_message_at=NOW - timedelta(days=6))
    done = {two_days.user_id: 1}

    # Сделано одно касание, молчит 2 дня — до второго (3 дня) ещё рано.
    assert touches.select_touch_targets([two_days], NOW, cfg(), done_by_user=done) == []
    # Молчит 6 дней — второе касание пора.
    second = touches.select_touch_targets([six_days], NOW, cfg(),
                                          done_by_user={six_days.user_id: 1})
    assert second and second[0]["number"] == 2
    # Третье — тоже, а четвёртого в графике нет.
    third = touches.select_touch_targets([six_days], NOW, cfg(),
                                         done_by_user={six_days.user_id: 2})
    assert third and third[0]["number"] == 3
    assert touches.select_touch_targets([six_days], NOW, cfg(),
                                        done_by_user={six_days.user_id: 3}) == []


def test_a_long_dead_lead_is_not_a_touch_but_a_mailing():
    """Молчит дольше `touch_max_age_days` — напоминание читается как рассылка."""
    old = conv(last_message_at=NOW - timedelta(days=45))
    assert touches.select_touch_targets([old], NOW, cfg()) == []
    # Границу можно поднять осознанно — тогда лид снова в работе.
    assert len(touches.select_touch_targets([old], NOW, cfg(touch_max_age_days=60))) == 1


def test_the_batch_is_capped_and_first_touches_go_first():
    """Порция ограничена, и первыми идут те, кому пора ПЕРВОЕ касание.

    Это урок дожима 07.09.2026: без порции первое включение залпом разошлось бы по
    всей базе. А порядок важен потому, что первое касание возвращает клиента чаще
    третьего — при лимите выгоднее потратить его на новых.
    """
    many = [conv(user_id=f"getvisa:99670000{i:04d}",
                 last_message_at=NOW - timedelta(days=10)) for i in range(30)]
    done = {c.user_id: 2 for c in many[:15]}        # половине уже касались дважды

    picked = touches.select_touch_targets(many, NOW, cfg(touch_batch_limit=10),
                                          done_by_user=done)

    assert len(picked) == 10
    assert all(t["number"] == 1 for t in picked), "первое касание важнее третьего"


def test_the_due_schedule_is_a_setting_not_a_constant():
    """График правится настройкой: «5–7 дней» Медина назвала вилкой."""
    assert touches.due_after_days(1, cfg()) == 1
    assert touches.due_after_days(3, cfg()) == 6
    assert touches.due_after_days(4, cfg()) is None
    assert touches.due_after_days(3, cfg(touch_after_days=[1, 3, 7])) == 7


def test_one_manager_does_not_get_two_hundred_tasks_in_a_day():
    """Суточный бюджет менеджера — ограничитель, найденный замером, а не придуманный.

    11.11.2026 на боевых данных под первое касание подходило 201 визовый лид, а на
    выезде менеджер один. Порция за прогон такой завал только растягивает: человек
    всё равно приходит утром к двум сотням задач, и список дел перестаёт быть списком.
    """
    many = [conv(user_id=f"getvisa:99670001{i:04d}",
                 last_message_at=NOW - timedelta(days=5)) for i in range(201)]

    picked = touches.select_touch_targets(many, NOW,
                                          cfg(touch_daily_limit=10, touch_batch_limit=50))

    assert len(picked) == 10
    assert {t["owner"] for t in picked} == {"medina"}


def test_the_daily_budget_counts_what_was_already_created_today():
    """Если утром менеджеру уже создали касания, остаток бюджета учитывает их."""
    many = [conv(user_id=f"getvisa:99670002{i:04d}",
                 last_message_at=NOW - timedelta(days=5)) for i in range(20)]

    picked = touches.select_touch_targets(many, NOW, cfg(touch_daily_limit=10),
                                          today_by_owner={"medina": 8})

    assert len(picked) == 2, "бюджет 10, восемь уже отдано — остаётся два"


def test_the_budget_is_per_manager_not_global():
    """Бюджет считается на человека: у Элизы свой, у Медины свой."""
    mine = [conv(user_id=f"getvisa:99670003{i:04d}", assigned_to="medina",
                 last_message_at=NOW - timedelta(days=5)) for i in range(6)]
    hers = [conv(user_id=f"getvisa:99670004{i:04d}", assigned_to="eliza",
                 last_message_at=NOW - timedelta(days=5)) for i in range(6)]

    picked = touches.select_touch_targets(mine + hers, NOW, cfg(touch_daily_limit=4))

    by_owner = {}
    for target in picked:
        by_owner[target["owner"]] = by_owner.get(target["owner"], 0) + 1
    assert by_owner == {"medina": 4, "eliza": 4}


def test_fresh_leads_are_touched_before_the_dead_tail():
    """Внутри одного касания первыми идут САМЫЕ СВЕЖИЕ, а не самые давние.

    Нашёл сухой прогон на проде 11.11.2026: при обратном порядке первые двадцать задач
    достались клиентам, молчащим по 29 дней — почти мёртвым. График Медины (1, 3, 6
    дней) написан для тех, кого ещё можно вернуть. Тот же принцип в дожиме.
    """
    fresh = conv(user_id="getvisa:996700005001", last_message_at=NOW - timedelta(days=2))
    stale = conv(user_id="getvisa:996700005002", last_message_at=NOW - timedelta(days=29))

    picked = touches.select_touch_targets([stale, fresh], NOW, cfg(touch_batch_limit=1))

    assert len(picked) == 1
    assert picked[0]["silent_days"] == 2, "первым должен идти свежий лид"


def test_the_dead_tail_still_gets_its_turn_later():
    """Хвост не выбрасывается — он разбирается следующими прогонами, когда свежих нет."""
    stale = [conv(user_id=f"getvisa:99670000{i:04d}",
                  last_message_at=NOW - timedelta(days=20 + i)) for i in range(3)]

    picked = touches.select_touch_targets(stale, NOW, cfg())

    assert len(picked) == 3
    assert [t["silent_days"] for t in picked] == [20, 21, 22]


# --- Автозакрытие после всех касаний (ответ Медины, вопрос 4) -----------------

def closing_cfg(**kw):
    base = dict(touch_after_days=[1, 3, 6], touch_funnels=["visa"],
                auto_close_after_days=7, auto_close_batch_limit=20)
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_client_is_closed_after_all_touches_and_silence():
    """Её вопрос 4: три касания сделаны, клиент молчит — «Не реализовано»."""
    silent = conv(last_message_at=NOW - timedelta(days=10))
    done = {silent.user_id: 3}

    picked = touches.select_closable([silent], NOW, closing_cfg(), done_by_user=done)

    assert len(picked) == 1
    assert picked[0]["silent_days"] == 10


def test_touches_must_be_finished_first():
    """Два касания из трёх — рано закрывать, даже если молчит давно."""
    silent = conv(last_message_at=NOW - timedelta(days=30))
    assert touches.select_closable([silent], NOW, closing_cfg(),
                                   done_by_user={silent.user_id: 2}) == []


def test_silence_after_the_last_touch_is_required():
    """Все касания сделаны, но клиент молчит всего день — ещё читает третье сообщение.

    Счётчик касаний говорит лишь о том, что менеджеру поставили задачу. Закрывать
    по одному счётчику значит хоронить клиента в день последнего письма.
    """
    fresh = conv(last_message_at=NOW - timedelta(days=1))
    assert touches.select_closable([fresh], NOW, closing_cfg(),
                                   done_by_user={fresh.user_id: 3}) == []


def test_a_client_who_answered_is_not_closed():
    """Последним писал клиент — он не пропал, а ждёт нас."""
    answered = conv(last_sender="client", last_message_at=NOW - timedelta(days=20))
    assert touches.select_closable([answered], NOW, closing_cfg(),
                                   done_by_user={answered.user_id: 3}) == []


def test_a_finished_deal_is_never_reopened_as_lost():
    """Выигранную сделку автозакрытие не трогает — и уже закрытую тоже."""
    for outcome in ("won", "lost"):
        done_deal = conv(outcome=outcome, last_message_at=NOW - timedelta(days=30))
        assert touches.select_closable([done_deal], NOW, closing_cfg(),
                                       done_by_user={done_deal.user_id: 3}) == [], outcome


def test_closing_is_capped_and_oldest_first():
    """Порция ограничена; первыми уходят те, кто молчит дольше всех.

    Здесь порядок обратный касаниям: касание возвращает клиента, и там важны свежие,
    а закрытие лишь прибирает хвост — его и разбираем с конца.
    """
    many = [conv(user_id=f"getvisa:99670006{i:04d}",
                 last_message_at=NOW - timedelta(days=10 + i)) for i in range(30)]
    done = {c.user_id: 3 for c in many}

    picked = touches.select_closable(many, NOW, closing_cfg(auto_close_batch_limit=5),
                                     done_by_user=done)

    assert len(picked) == 5
    assert [t["silent_days"] for t in picked] == [39, 38, 37, 36, 35]


def test_other_directions_are_not_closed():
    """Только визы: по турам автозакрытие никто не заказывал."""
    tours = conv(funnel="tours", last_message_at=NOW - timedelta(days=30))
    assert touches.select_closable([tours], NOW, closing_cfg(),
                                   done_by_user={tours.user_id: 3}) == []
