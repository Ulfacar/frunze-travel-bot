# -*- coding: utf-8 -*-
"""Хеширование паролей менеджеров — с главным требованием «не сломать вход».

Пароли семи живых людей лежат в `prod.env` открытым текстом. Перевести их в хеши
нужно, но так, чтобы вход не оборвался ни у кого ни на секунду: поэтому проверка
обязана понимать ОБА формата, а перевод идти по одному человеку.
"""
import pytest

from app.core.passwords import hash_password, looks_hashed, verify_password


def test_a_hashed_password_verifies():
    stored = hash_password("talas-zaman-otton-73")
    assert looks_hashed(stored)
    assert verify_password("talas-zaman-otton-73", stored) is True


def test_a_wrong_password_is_rejected():
    stored = hash_password("talas-zaman-otton-73")
    assert verify_password("talas-zaman-otton-74", stored) is False
    assert verify_password("", stored) is False


def test_the_same_password_hashes_differently_every_time():
    """Соль случайная: одинаковые пароли не должны выглядеть одинаково в файле."""
    first = hash_password("limon-kedr-okean-42")
    second = hash_password("limon-kedr-okean-42")
    assert first != second
    assert verify_password("limon-kedr-okean-42", first)
    assert verify_password("limon-kedr-okean-42", second)


def test_a_plain_password_still_works():
    """Пока менеджера не перевели — он входит как раньше. Это условие перевода.

    Без этого пришлось бы менять все пароли разом, ночью, семи людям, которые завтра
    работают с клиентами.
    """
    assert verify_password("secret", "secret") is True
    assert verify_password("secret", "other") is False


def test_stray_spaces_do_not_break_the_plain_path():
    """Пробел при копипасте в prod.env не ронял вход раньше — не должен и теперь."""
    assert verify_password(" secret ", " secret ") is True
    assert verify_password("secret", "  secret  ") is True


def test_a_broken_hash_is_a_refusal_not_a_pass():
    """Битая строка — отказ. Иначе порча файла превратилась бы во вход без пароля."""
    for broken in ("scrypt$", "scrypt$abc$8$1$xx$yy", "scrypt$16384$8$1$!!!$!!!",
                   "scrypt$16384$8"):
        assert verify_password("secret", broken) is False, broken


def test_an_empty_stored_value_never_authenticates():
    """Пустой пароль в настройках не должен пускать никого — даже с пустой формой."""
    assert verify_password("", "") is False
    assert verify_password("anything", "") is False


def test_an_empty_password_is_not_hashable():
    """Пустой пароль не хешируем: такой хеш означал бы вход без пароля."""
    with pytest.raises(ValueError):
        hash_password("")


def test_hash_parameters_live_inside_the_string():
    """Стоимость можно поднять завтра, и старые хеши обязаны продолжать работать."""
    cheap = hash_password("limon-kedr-okean-42", n=2 ** 12)
    assert verify_password("limon-kedr-okean-42", cheap) is True
    assert "$4096$" in cheap
