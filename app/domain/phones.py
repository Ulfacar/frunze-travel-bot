"""WP1B phone-identity normalization.

Rules (approved):

* strip the WhatsApp suffix (``...@c.us`` / ``@s.whatsapp.net`` / ``@g.us``),
  spaces, parentheses and dashes;
* Kyrgyz local forms ``+996XXXXXXXXX`` / ``996XXXXXXXXX`` / ``0XXXXXXXXX`` /
  ``XXXXXXXXX`` all collapse to the canonical ``996XXXXXXXXX`` (12 digits);
* a valid full international number (explicit leading ``+``, non-996 country
  code) is kept with its own country code as E.164 digits (no ``+``);
* ambiguous or too-short inputs are rejected with :class:`DomainError`;
* callers use ``provider_scope=""`` for phone identities so one person maps to a
  single Contact across every bot/profile (no per-bot duplication).

``assume_e164`` — для источников, где формат гарантирован протоколом. WhatsApp всегда
отдаёт полный номер без ``+`` (``905078174386@c.us``), и по общему правилу такие номера
отвергались как ambiguous: на проде 30.07 из-за этого 16 живых иностранных клиентов
(Турция, КЗ, УЗ, ОАЭ, РФ, Испания, США) остались без владельца, у одного 22 сообщения.
Общее правило не ослабляем — знание о формате принадлежит каналу, поэтому флаг
прокидывает ``live_assign.contact_for_channel`` только для WhatsApp. Результат совпадает
с ``+``-формой того же номера, поэтому один человек остаётся одним Contact.
"""
from __future__ import annotations

import re

from app.domain.models import DomainError

_KG_CC = "996"
_KG_SUBSCRIBER_LEN = 9          # digits after the 996 country code
_MIN_INTL_LEN = 8              # shortest plausible E.164 number
_MAX_INTL_LEN = 15            # E.164 maximum
# Без `+` доверяем длине от 11: 9-10 цифр — это ещё и диапазон telegram-id, а его нельзя
# принять за номер ни при каких условиях (иначе выдуманный Contact с реальным владельцем).
_MIN_BARE_E164_LEN = 11


def normalize_phone(raw: str, *, assume_e164: bool = False) -> str:
    """Return the canonical digit string for a phone identity, or raise DomainError.

    ``assume_e164`` разрешает номер без ``+``, когда формат гарантирован источником
    (WhatsApp). Флаг только ДОБАВЛЯЕТ приём: ни один вход, который сейчас проходит,
    результата не меняет.
    """
    if not raw or not isinstance(raw, str):
        raise DomainError("empty phone identity")
    # Drop a channel suffix like `...@c.us` and surrounding whitespace.
    head = raw.split("@", 1)[0].strip()
    had_plus = head.startswith("+")
    digits = re.sub(r"\D", "", head)          # removes spaces, parens, dashes, '+', etc.
    if not digits:
        raise DomainError("phone has no digits")

    # Kyrgyz country code already present (covers "+996…" and "996…").
    if digits.startswith(_KG_CC):
        if len(digits) != len(_KG_CC) + _KG_SUBSCRIBER_LEN:      # exactly 12
            raise DomainError("ambiguous KG phone length")
        return digits

    # Explicit international intent (leading '+') but not KG → keep its own code.
    if had_plus:
        if not (_MIN_INTL_LEN <= len(digits) <= _MAX_INTL_LEN):
            raise DomainError("invalid international phone length")
        return digits

    # Local trunk-zero form 0XXXXXXXXX → 996XXXXXXXXX.
    if digits.startswith("0"):
        rest = digits[1:]
        if len(rest) != _KG_SUBSCRIBER_LEN:
            raise DomainError("ambiguous local phone length")
        return _KG_CC + rest

    # Bare subscriber number XXXXXXXXX → 996XXXXXXXXX.
    if len(digits) == _KG_SUBSCRIBER_LEN:
        return _KG_CC + digits

    # Источник гарантирует E.164 (WhatsApp-формат без `+`) → принимаем как есть.
    if assume_e164 and _MIN_BARE_E164_LEN <= len(digits) <= _MAX_INTL_LEN:
        return digits

    # Anything else without an explicit country code is ambiguous → reject.
    raise DomainError("ambiguous phone number")
