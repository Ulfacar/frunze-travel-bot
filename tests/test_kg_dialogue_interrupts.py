"""Source examples exercise interruption before interpreting an ordinary answer."""
import pytest

from app.knowledge.dialogue_interrupts import triage, FAMILIES

# Numbered examples derived from all 57 rows in supplied PDF v1.1 section17.
# This checks conservative triage only, not execution of the downstream SOP.
EXAMPLES = [
    ('Я потерял паспорт до поездки', 'I lost my passport before travelling'),
    ('Я потерял паспорт в Кыргызстане', 'My passport was lost inside Kyrgyzstan'),
    ('У меня новый паспорт', 'I have a replacement passport'),
    ('Виза осталась в старом паспорте', 'My visa is in my old passport'),
    ('Я сменил гражданство', 'My citizenship has changed'),
    ('После свадьбы поменялась фамилия', 'My surname changed after marriage'),
    ('В выданной визе ошибка', 'There is a mistake in my issued visa'),
    ('Я ошибся в анкете после оплаты', 'My paid application has an incorrect answer'),
    ('Я поменял даты поездки', 'My travel dates have changed'),
    ('Я уже в Кыргызстане и хочу новую визу', 'I am already in Kyrgyzstan and need a visa'),
    ('У меня просрочка пребывания', 'I have overstayed'),
    ('Я не могу выехать', 'I cannot leave the country'),
    ('Мне отказали в визе', 'My visa was refused'),
    ('Мне нужно срочно выехать', 'I need an urgent exit'),
    ('Я потерял файл электронной визы', 'I lost my e-Visa file'),
    ('Мне не приходит письмо на почту', 'My verification email has not arrived'),
    ('Оплата не проходит', 'My payment failed'),
    ('Деньги списались два раза', 'My card was charged twice'),
    ('Не загружается документ', 'The document upload fails'),
    ('Портал не работает', 'The portal is down'),
    ('Заявка слишком долго на рассмотрении', 'Processing is taking too long'),
    ('Запросили дополнительные документы', 'They requested additional documents'),
    ('Хочу поменять тип визы', 'I want to change the visa type'),
    ('Хочу продлить визу', 'I need a visa extension'),
    ('Хочу привезти семью', 'I want to bring my family'),
    ('Я потерял номер заявки', 'I lost the reference number'),
    ('Истекли 72 часа верификации', 'The verification link expired after 72 hours'),
    ('Я въехал по другому паспорту', 'I entered with a different passport'),
    ('Ребёнок родился в Кыргызстане', 'My child was born in Kyrgyzstan'),
    ('Работодатель меня уволил', 'My employer dismissed me'),
    ('Работник самовольно ушёл', 'The worker left without permission'),
    ('Работодатель в реестре недобросовестных', 'My employer is on the prohibited list'),
    ('Квоту аннулировали', 'Our quota was cancelled'),
    ('Мне позвонил ГКНБ', 'The security service summoned me'),
    ('Меня пригласили в МИД проверить документы', 'The ministry summoned me for a document check'),
    ('У меня запрет на въезд', 'I have an entry ban'),
    ('Хочу подработать по туристической визе', 'I want to work on a tourist visa'),
    ('Я журналист, въехал как турист', 'I entered as a tourist but work as a journalist'),
    ('В паспорте нет чистых страниц', 'My passport has no blank pages'),
    ('Я въезжаю по суше через другой КПП', 'I plan to use a different land border crossing'),
    ('Нас группа из пяти туристов', 'We are a group of five tourists'),
    ('Я гражданин США, хочу на 45 дней', 'I am American and want to stay for 45 days'),
    ('Я опоздал с регистрацией', 'My registration is overdue'),
    ('Я уехал из КР больше чем на 30 дней', 'I have been away for more than 30 days'),
    ('Ошибка в регистрации', 'My registration contains an error'),
    ('Как повлияют праздники на срок', 'How do holidays affect the deadline'),
    ('Изменилось законодательство', 'The law has changed'),
    ('Сделайте фиктивное приглашение', 'Can you provide a fake invitation'),
    ('Приглашающая сторона отозвала письмо', 'My sponsor withdrew the invitation'),
    ('Несовершеннолетний едет без родителей', 'A minor is travelling without parents'),
    ('Меня не пустили на границе с визой', 'I was denied entry at the border despite my visa'),
    ('Прошу возврат на другую карту', 'Please refund me to another card'),
    ('Сам подал e-Visa с ошибкой', 'I submitted an incorrect e-Visa application myself'),
    ('Визу выдали на сокращённый срок', 'The visa was issued for a shorter period'),
    ('Не помню сколько дней я провёл в КР', 'I cannot remember how many days I spent in Kyrgyzstan'),
    ('Для Узбекистана говорят три месяца без регистрации', 'I heard Uzbeks need no registration for three months'),
    ('Правда ли ЕР передали в Минтруд', 'Has the work permit moved to the labour ministry'),
]


@pytest.mark.parametrize('row,messages', enumerate(EXAMPLES, 1))
def test_every_source_exception_interrupts_before_answer_parsing(row, messages):
    for text in messages:
        result = triage(text)
        assert result.reason is not None, (row, text)
        assert result.interpretation in ('review_topic_only', 'collection_stop_request')


def test_source_rows_are_complete_and_unique():
    assert len(EXAMPLES) == 57
    assert sorted(n for rows in FAMILIES.values() for n in rows) == list(range(1, 58))


@pytest.mark.parametrize('text', [
    'I no longer consent to storing my data', 'I refuse to let you collect my data',
    'I revoke permission to process my data', 'Я больше не согласен на обработку моих данных',
    'не даю согласия', 'Отзываю свое согласие', 'Do not process my data',
    'Stop collecting my data', 'Удалите мои данные',
])
def test_privacy_stop_precedes_general_exception_classification(text):
    assert triage(text).reason == 'consent_withdrawn'


@pytest.mark.parametrize('text', ['Do not store this', 'Stop collecting information about me',
    'Не храните информацию обо мне', 'Не собирайте ничего больше',
    'Revoke permission to process these records'])
def test_every_collection_stop_detector_precedes_unsupported_input_guards(text):
    assert triage(text).reason=='consent_withdrawn'
    assert triage(text,voice=True).reason=='consent_withdrawn'
    assert triage(text+' x'*1100).reason=='consent_withdrawn'


@pytest.mark.parametrize('text', ['здравствуйте', 'Спасибо!', 'hello', 'Thank you.', 'ok'])
def test_closed_acknowledgements_can_continue_only_after_context_checks(text):
    assert triage(text).reason is None


@pytest.mark.parametrize('text', ['да', 'no', '2026-10-20', '45', '????????',
    'I do not have an entry ban', 'Он сказал «подделать паспорт», я против',
    'Hello but I have a ban', 'hello\u200b', 'x' * 2049, None])
def test_ambiguous_negated_quoted_mixed_and_malformed_never_become_safe_facts(text):
    result = triage(text)
    assert result.reason is not None
    assert result.interpretation == 'review_topic_only'


def test_consent_no_and_untrusted_media_never_enter_ordinary_answer_path():
    assert triage('no', consent_question=True).reason == 'consent_withdrawn'
    assert triage('hello', voice=True).reason == 'uncertain_answer'
    assert triage('hello', kind='non_text').reason == 'uncertain_answer'


@pytest.mark.parametrize('text,reason', [
    ('Хочу менеджера', 'manager_requested'), ('I need a human', 'manager_requested'),
    ('Меня раздражают ваши вопросы', 'complaint'), ('Too many questions', 'complaint'),
    ('У меня уголовное дело', 'criminal_mention'), ('I was convicted', 'criminal_mention'),
])
def test_non_slot_interrupts_are_immediate(text, reason):
    assert triage(text).reason == reason
