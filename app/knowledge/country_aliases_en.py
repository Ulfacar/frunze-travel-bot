"""Английские названия стран → ISO3. То, чего нет в бандле.

Зачем. `knowledge/kg_entry/draft-v1.1/countries.yaml` знает 365 алиасов, но только
русские названия и сами коды: «Индия» находится, `India` — нет. А приёмка въездного
бота — иностранец, который пишет в WhatsApp по-английски. Без этого слоя ядро падает на
первом же шаге, ещё до любых правил.

Покрыты ровно те 110 кодов, которые встречаются в безвизовых и визовых режимах и в
правилах регистрации — то есть всё, по чему движок вообще может что-то ответить. Страна
вне этого списка даёт None, то есть передачу менеджеру; это правильный исход, а не пробел.

Разговорные варианты («UAE», «UK», «South Korea», «Czechia») добавлены там, где человек
почти наверняка напишет именно так. Политически спорных самоназваний здесь нет: это
технический справочник соответствия кодам ISO 3166-1.
"""
from __future__ import annotations

import re
import unicodedata

# Основное английское название на каждый код.
_PRIMARY: dict[str, str] = {
    "AFG": "Afghanistan", "ALB": "Albania", "AND": "Andorra",
    "ARE": "United Arab Emirates", "ARG": "Argentina", "ARM": "Armenia",
    "AUS": "Australia", "AUT": "Austria", "AZE": "Azerbaijan", "BEL": "Belgium",
    "BGD": "Bangladesh", "BGR": "Bulgaria", "BHR": "Bahrain", "BHS": "Bahamas",
    "BIH": "Bosnia and Herzegovina", "BLR": "Belarus", "BRA": "Brazil",
    "BRB": "Barbados", "BRN": "Brunei", "CAN": "Canada", "CHE": "Switzerland",
    "CHL": "Chile", "CHN": "China", "CRI": "Costa Rica", "CUB": "Cuba",
    "CYP": "Cyprus", "CZE": "Czech Republic", "DEU": "Germany", "DMA": "Dominica",
    "DNK": "Denmark", "DZA": "Algeria", "ECU": "Ecuador", "EGY": "Egypt",
    "ESP": "Spain", "EST": "Estonia", "FIN": "Finland", "FRA": "France",
    "GBR": "United Kingdom", "GEO": "Georgia", "GRC": "Greece", "HRV": "Croatia",
    "HUN": "Hungary", "IDN": "Indonesia", "IND": "India", "IRL": "Ireland",
    "IRN": "Iran", "IRQ": "Iraq", "ISL": "Iceland", "ISR": "Israel", "ITA": "Italy",
    "JOR": "Jordan", "JPN": "Japan", "KAZ": "Kazakhstan", "KOR": "South Korea",
    "KWT": "Kuwait", "LAO": "Laos", "LBN": "Lebanon", "LIE": "Liechtenstein",
    "LKA": "Sri Lanka", "LTU": "Lithuania", "LUX": "Luxembourg", "LVA": "Latvia",
    "MAR": "Morocco", "MCO": "Monaco", "MDA": "Moldova", "MDV": "Maldives",
    "MEX": "Mexico", "MKD": "North Macedonia", "MLT": "Malta", "MNE": "Montenegro",
    "MNG": "Mongolia", "MYS": "Malaysia", "NGA": "Nigeria", "NIC": "Nicaragua",
    "NLD": "Netherlands", "NOR": "Norway", "NPL": "Nepal", "NZL": "New Zealand",
    "OMN": "Oman", "PAK": "Pakistan", "PER": "Peru", "PHL": "Philippines",
    "POL": "Poland", "PRK": "North Korea", "PRT": "Portugal", "QAT": "Qatar",
    "ROU": "Romania", "RUS": "Russia", "SAU": "Saudi Arabia", "SGP": "Singapore",
    "SLV": "El Salvador", "SMR": "San Marino", "SRB": "Serbia", "SVK": "Slovakia",
    "SVN": "Slovenia", "SWE": "Sweden", "SYR": "Syria", "THA": "Thailand",
    "TJK": "Tajikistan", "TKM": "Turkmenistan", "TUN": "Tunisia", "TUR": "Turkey",
    "UKR": "Ukraine", "USA": "United States", "UZB": "Uzbekistan",
    "VAT": "Vatican", "VEN": "Venezuela", "VNM": "Vietnam", "YEM": "Yemen",
    "ZAF": "South Africa",
}

# Разговорные и альтернативные написания, которые человек правда набирает.
_EXTRA: dict[str, str] = {
    "uae": "ARE", "emirates": "ARE", "uk": "GBR", "great britain": "GBR",
    "britain": "GBR", "england": "GBR", "usa": "USA", "us": "USA",
    "united states of america": "USA", "america": "USA",
    "korea": "KOR", "republic of korea": "KOR", "south korea": "KOR",
    "dprk": "PRK", "north korea": "PRK",
    "czechia": "CZE", "czech": "CZE", "holland": "NLD",
    "russian federation": "RUS", "turkiye": "TUR", "turkey": "TUR",
    "macedonia": "MKD", "bosnia": "BIH", "vatican city": "VAT", "holy see": "VAT",
    "viet nam": "VNM", "lao pdr": "LAO", "kyrgyz": "KGZ", "kyrgyzstan": "KGZ",
    "saudi": "SAU", "iran islamic republic of": "IRN", "ivory": "",
}


def _norm(text: str) -> str:
    """Нижний регистр без диакритики и пунктуации: «Côte d'Ivoire» → «cote d ivoire»."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^0-9a-zA-Z\s]+", " ", folded.lower())
    return re.sub(r"\s+", " ", folded).strip()


def _build() -> dict[str, str]:
    table: dict[str, str] = {}
    for iso3, name in _PRIMARY.items():
        table[_norm(name)] = iso3
        table[_norm(iso3)] = iso3
    for alias, iso3 in _EXTRA.items():
        if iso3:
            table[_norm(alias)] = iso3
    return table


_TABLE = _build()


def iso3_for_en(text: str) -> str | None:
    """ISO3 по английскому названию или коду. None — не знаем, значит к менеджеру.

    Кыргызстан сознательно НЕ возвращается как гражданство: клиент-иностранец говорит о
    стране своего паспорта, а «Kyrgyzstan» в его реплике — это пункт назначения. Решать
    такую двусмысленность должен человек.
    """
    key = _norm(text)
    if not key or key in ("kgz", "kyrgyz", "kyrgyzstan", "kirghizia"):
        return None
    return _TABLE.get(key)
