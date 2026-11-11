"""Пароли менеджеров панели: хеш вместо открытого текста, без обрыва входа.

Сегодня `MANAGERS` в `prod.env` хранит пароли как есть, и `_check_credentials`
сравнивает их строкой. Это осознанное упрощение «для команды из нескольких человек»
(докстринг `ManagerConfig`), но файл с открытыми паролями кочует в бэкапы, в
копипасты и в чужие глаза, а менеджеров стало семеро и будет больше.

**Главное требование — не сломать вход.** Поэтому проверка понимает оба формата:
хеш, если строка им выглядит, и открытый пароль иначе. Значит перевод делается по
одному человеку и в любой момент, а не «все сразу в ночь перед показом».

Алгоритм — `hashlib.scrypt` из стандартной библиотеки. Не bcrypt и не argon2
намеренно: оба пришлось бы тащить в боевой образ, а scrypt уже есть везде, где есть
Python, и для задачи «семь паролей от внутренней панели» его с запасом.

Формат строки: `scrypt$<n>$<r>$<p>$<соль base64>$<хеш base64>`. Параметры лежат
внутри строки, поэтому старые хеши продолжат проверяться, даже если завтра поднимем
стоимость.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PREFIX = "scrypt$"
# n=2**14 — около 50 мс на проверку на нашем VPS. Вход в панель не горячий путь,
# а брутфорс дорожает на четыре порядка против голого сравнения строк.
_N = 2 ** 14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32


def looks_hashed(stored: str) -> bool:
    """Похожа ли строка на наш хеш. Пустая строка — не хеш (и не пароль)."""
    return str(stored or "").startswith(PREFIX)


def hash_password(password: str, *, n: int = _N, r: int = _R, p: int = _P) -> str:
    """Хеш пароля со случайной солью."""
    password = str(password or "")
    if not password:
        raise ValueError("пустой пароль не хешируем: это был бы вход без пароля")
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                         dklen=_KEY_BYTES)
    return (f"{PREFIX}{n}${r}${p}$"
            f"{base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}")


def verify_password(password: str, stored: str) -> bool:
    """Подходит ли пароль. Понимает и хеш, и старый открытый пароль.

    Открытый пароль сравнивается так же, как раньше — `compare_digest`, с обрезкой
    пробелов по краям: случайный пробел при копипасте в `prod.env` не должен ронять
    вход (это поведение было до хешей, и менять его заодно нельзя).
    """
    password = str(password or "").strip()
    stored = str(stored or "")
    if not stored:
        return False
    if not looks_hashed(stored):
        return hmac.compare_digest(password.encode("utf-8"),
                                   stored.strip().encode("utf-8"))
    try:
        _, n, r, p, salt_b64, key_b64 = stored.split("$", 5)
        key = hashlib.scrypt(password.encode("utf-8"),
                             salt=base64.b64decode(salt_b64),
                             n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(key_b64)))
    except (ValueError, TypeError):
        # Битый хеш — это не «пароль подошёл». Любая ошибка разбора = отказ.
        return False
    return hmac.compare_digest(key, base64.b64decode(key_b64))
