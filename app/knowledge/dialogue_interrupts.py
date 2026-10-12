"""Conservative RU/EN interruption triage, not a free-text eligibility parser.

Only a closed set of conversational acknowledgements can be admitted here.
Every other unrecognised statement needs a specialist; matching an exception
labels a request for review and never establishes the underlying legal fact.
"""
from dataclasses import dataclass
import re
import unicodedata

VERSION = 'kg-dialogue-interrupts/1'
MAX_TEXT = 2048

# Source: supplied v1.1 PDF, section 17. Each numbered row belongs to one family.
FAMILIES = {
    'identity_change': (1, 2, 3, 4, 5, 6, 28),
    'application_error': (7, 8, 53),
    'travel_change': (9, 23, 24, 42, 54),
    'current_stay': (10, 11, 12, 14),
    'refusal_or_ban': (13, 36, 51),
    'document_retrieval': (15, 26),
    'portal_problem': (16, 17, 19, 20, 27),
    'payment_refund': (18, 52),
    'processing_exception': (21, 22, 46),
    'family_or_group': (25, 29, 41, 50),
    'employment_or_sponsor': (30, 31, 32, 33, 34, 35, 38, 49),
    'unsafe_request': (37, 48),
    'passport_validity': (39,),
    'border_crossing': (40,),
    'registration_exception': (43, 44, 45),
    'source_dispute': (47, 56, 57),
    'unknown_history': (55,),
}

# Broad recall is intentional. These labels are review topics, not factual
# assertions; negative/quoted/mixed statements must not be converted into facts.
PATTERNS = {
    'identity_change': r'паспорт|гражданств|фамили|passport|citizenship|nationality|surname|name chang',
    'application_error': r'ошиб|опечат|анкет|mistake|incorrect|typo|application error',
    'travel_change': r'дат[аыуе]|продл|дольше|срок виз|тип виз|extend|extension|longer|shorter|travel date|visa type',
    'current_stay': r'уже в|въехал|просроч|выехать|срочно|overstay|already in|entered|cannot leave|urgent exit',
    'refusal_or_ban': r'отказ|запрет|депорт|refus|deni(?:ed|al)|entry ban|deport',
    'document_retrieval': r'e-?visa|электронн.*виз|reference|референс|номер заяв',
    'portal_problem': r'почт|e-?mail|верификац|загруз|портал|оплат.*(?:не|ошиб)|payment fail|upload|portal|verification',
    'payment_refund': r'возврат|списан|refund|charged|duplicate payment|another (?:card|account)',
    'processing_exception': r'рассмотр|дополнительн.*документ|праздник|выходн|processing|additional document|holiday|weekend',
    'family_or_group': r'семь|ребен|ребён|родител|групп|несовершеннолет|family|child|parents?|group|minor',
    'employment_or_sponsor': r'работодател|увол|квот|приглаша|гкнб|мид|журналист|employer|dismiss|quota|sponsor|summon|journalis|invitation withdraw',
    'unsafe_request': r'поддел|фиктив|взятк|подработ|работ.*турист|гарант|fake|forg|bribe|guarantee|work.*tourist|tourist.*work',
    'passport_validity': r'страниц|истека|blank page|expir|six months|6 months',
    'border_crossing': r'кпп|границ|по суше|border|crossing|land entry|checkpoint',
    'registration_exception': r'регистрац|registration|уехал.*30|away.*30',
    'source_dispute': r'закон|минтруд|амнист|новые правил|law|ministr|amnest|new rules|regulation',
    'unknown_history': r'сколько дней|не помню|не знаю|how many days|do not know|don.t know|can.t remember',
}
BENIGN = frozenset(('здравствуйте', 'добрый день', 'доброе утро', 'добрый вечер',
    'привет', 'спасибо', 'понятно', 'хорошо', 'hello', 'hi', 'good morning',
    'good afternoon', 'good evening', 'thank you', 'thanks', 'understood', 'ok', 'okay'))


@dataclass(frozen=True)
class Triage:
    reason: str | None
    families: tuple[str, ...] = ()
    source_rows: tuple[int, ...] = ()
    interpretation: str = 'review_topic_only'


def triage(value, *, kind='text', voice=False, consent_question=False):
    if type(value) is not str:
        return Triage('uncertain_answer')
    controls = any(unicodedata.category(c).startswith('C') and c not in '\n\r\t' for c in value)
    # Input may be unsuitable for ordinary answer parsing and still contain a
    # request to stop collection. Inspect the bounded raw input before rejecting
    # voice/format/length; invisible controls cannot conceal a privacy topic.
    scan = ''.join(c for c in value if not unicodedata.category(c).startswith('C') or c in '\n\r\t')
    text = ' '.join(unicodedata.normalize('NFKC', scan).casefold().split())
    privacy = re.search(r'соглас|мои данн|моих данн|обработк.*данн|consent|privacy|my data|personal information', text)
    withdrawal = (r'отзываю.*согласи|не (?:обрабатыва|собира|хран)|удалите.*данн|'
                  r'не (?:соглас(?:ен|на)|даю согласия)|'
                  r'no longer consent|revoke (?:permission|consent)|refuse.*(?:collect|process|stor)|'
                  r'withdraw.*consent|stop (?:processing|collecting|storing)|'
                  r'(?:do not|don.t) (?:process|collect|store)|delete my data')
    requested_stop = re.search(withdrawal, text) or consent_question and text.rstrip('.!') in ('нет', 'no', 'не согласен', 'не согласна', 'i refuse')
    if len(value) > MAX_TEXT or kind != 'text' or voice or controls:
        return Triage('consent_withdrawn', interpretation='possible_privacy_stop') if privacy or requested_stop else Triage('uncertain_answer')
    text = text.rstrip('.!')
    if not text:
        return Triage('uncertain_answer')
    # Collection is stopped conservatively even for ambiguous withdrawal wording;
    # a human can inspect the original incoming message in the existing inbox.
    if requested_stop:
        interpretation = 'possible_privacy_stop' if any(c in text for c in '\"«»“”') else 'collection_stop_request'
        return Triage('consent_withdrawn', interpretation=interpretation)
    if privacy:
        return Triage('consent_withdrawn', interpretation='possible_privacy_stop')
    if re.search(r'менеджер|оператор|человек|human|manager|operator|stop|стоп|прекратите', text):
        return Triage('manager_requested')
    if re.search(r'жалоб|надоел|раздраж|сколько можно|хватит вопрос|complaint|annoy|frustrat|too many questions|stop asking', text):
        return Triage('complaint')
    if re.search(r'уголов|судим|преступ|criminal|convict|crime', text):
        return Triage('criminal_mention')
    families = tuple(name for name, pattern in PATTERNS.items() if re.search(pattern, text))
    if families:
        reason = ('unsafe_request' if 'unsafe_request' in families else
                  'refund' if 'payment_refund' in families else
                  'legal_question' if 'refusal_or_ban' in families or 'source_dispute' in families else
                  'calendar_needed' if 'processing_exception' in families else 'special_process')
        return Triage(reason, families, tuple(sorted({n for f in families for n in FAMILIES[f]})))
    if text in BENIGN:
        return Triage(None, interpretation='closed_conversational_acknowledgement')
    # Yes/no/date/number alone can answer a risky question or withdraw consent.
    # They are not generic evidence of a safe or complete applicant profile.
    return Triage('uncertain_answer')
