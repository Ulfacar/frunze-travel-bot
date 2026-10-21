"""ГЕЙТ: бандл знаний по въезду в КР не меняется молча.

Написан ДО реализации движка и исполнителем НЕ редактируется.

Зачем. Движок режима въезда отвечает клиенту правилами из
`knowledge/kg_entry/draft-v1.1/`. Это юридический материал: лимиты дней, сроки
регистрации, нужно ли Единое разрешение. Любая правка этих файлов меняет то, что бот
говорит иностранцу про закон Кыргызстана — и должна быть видна в диффе как намеренная,
а не приехать попутно с рефакторингом.

Поэтому контрольная сумма бандла и раскладка статусов прибиты здесь числом. Если тест
упал — либо кто-то правил данные (тогда обнови числа отдельным осознанным коммитом с
указанием, что именно сверено с PDF), либо бандл испортился.

Отдельно закреплено: подтверждённых единиц НОЛЬ. Это не недоделка, а состояние приёмки
(J05): все 208 единиц импортированы как черновики, и пока Гриша не подтвердил их сверкой
с PDF, бот не имеет права произносить их как факт.
"""
from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parents[1] / "knowledge" / "kg_entry" / "draft-v1.1"
SOURCE_PDF = Path(__file__).resolve().parents[1] / "runs" / "specialist-source.pdf"

# Прибито 21.10.2026 по фактическому прогону preflight_bundle.
PINNED_BUNDLE_HASH = "bf9faa537ae600c433a064ab21b8d5969aa63ba99fc39ead224dc6fa5256dea5"
PINNED_SOURCE_HASH = "141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2"
PINNED_STATUS_COUNTS = {"blocked": 3, "decision_pending": 22, "needs_verification": 183}
PINNED_UNITS = 208


def _report():
    from app.knowledge.bundle import preflight_bundle
    if not SOURCE_PDF.exists():
        pytest.skip("нет runs/specialist-source.pdf — исходный PDF ТЗ не в рабочем дереве")
    return preflight_bundle(BUNDLE, SOURCE_PDF)


def test_bundle_is_valid_and_pinned():
    r = _report()
    assert r.ok and not r.errors, f"бандл знаний невалиден: {r.errors[:3]}"
    assert r.bundle_hash == PINNED_BUNDLE_HASH, (
        "контрольная сумма бандла изменилась — данные по визам КР правили. "
        "Это допустимо только отдельным коммитом со сверкой по PDF.")
    assert r.status_counts == PINNED_STATUS_COUNTS
    assert r.normalized_bundle["meta"]["source_hash"] == PINNED_SOURCE_HASH


def test_nothing_is_confirmed_yet():
    """Ноль подтверждённых — это текущее состояние приёмки, а не баг."""
    r = _report()
    units = r.normalized_bundle["units"]
    assert len(units) == PINNED_UNITS
    confirmed = [u for u in units if u.get("confirmation_status") == "confirmed"]
    assert confirmed == [], (
        "кто-то подтвердил единицы правкой бандла. Подтверждения живут отдельным "
        "оверлеем (knowledge/kg_entry/confirmations-v1.1.yaml), чтобы правка значения "
        "аннулировала подтверждение, а не протаскивала устаревший текст клиенту.")


def test_regime_data_the_core_relies_on_is_present():
    """Пять безвизовых режимов, три визовых, регистрация — иначе движку нечем отвечать."""
    r = _report()
    units = {u["unit_id"]: u for u in r.normalized_bundle["units"]}
    for uid, days, window in (("KG.VF.EAEU", 90, 180), ("KG.VF.NINETY_180", 90, 180),
                              ("KG.VF.CIS_BILATERAL", 60, 120), ("KG.VF.UZB", 60, 120)):
        v = units[uid]["value"]
        assert (v["days"], v["window_days"]) == (days, window), f"{uid} изменил лимит"
    assert units["KG.VF.ANNEX1_30_60"]["value"]["days"] == 30
    assert units["KG.VR.GENERAL"]["value"]["countries"] == "all_others"
    # 17 стран без освобождения от регистрации → 5 рабочих дней с границы.
    default = units["KG.REG.DEFAULT"]["value"]
    assert default["deadline_working_days_from_border"] == 5
    assert len(default["not_in_list"]) == 17 and "UZB" in default["not_in_list"]


def test_cis_bilateral_stays_unsayable_by_label():
    """Таджикистан, Азербайджан, Грузия помечены `verify` — их НЕЛЬЗЯ называть как факт.

    ТЗ: 60/120 по этим странам известно «по сообщениям СМИ о ПКМ № 437 и № 600, в П-541
    прямо не названо». Метка `verify` — машинное выражение этого запрета, и она не должна
    исчезнуть при подтверждении остальных режимов.
    """
    r = _report()
    units = {u["unit_id"]: u for u in r.normalized_bundle["units"]}
    assert units["KG.VF.CIS_BILATERAL"]["label"] == "verify"
    # А вот эти метками не помечены, то есть после подтверждения говорить можно.
    for uid in ("KG.VF.EAEU", "KG.VF.NINETY_180", "KG.VF.UZB", "KG.VF.ANNEX1_30_60",
                "KG.VR.GENERAL", "KG.REG.DEFAULT"):
        assert units[uid]["label"] == "none", f"{uid} получил метку — проверь источник"


def test_moldova_contradiction_stays_unresolved():
    """Молдова: ТЗ противоречит сам себе (90 дней против «нет в Перечне, 5 р.д.»).

    Импорт оставил значение пустым — и это правильный исход. Если однажды тест упадёт,
    значит кто-то выбрал сторону за Гришу; это продуктовое решение, не правка данных.
    """
    r = _report()
    mda = next((u for u in r.normalized_bundle["units"]
                if u["unit_id"] == "KG.REG.EXEMPT.MDA"), None)
    assert mda is not None
    assert mda.get("value") is None, "противоречие по Молдове разрешили молча"


def test_registration_exemptions_do_not_contradict_the_default():
    """Страна не может одновременно иметь освобождение и быть в списке «без освобождения»."""
    r = _report()
    units = r.normalized_bundle["units"]
    no_exempt = set(next(u for u in units
                         if u["unit_id"] == "KG.REG.DEFAULT")["value"]["not_in_list"])
    with_exempt = {u["unit_id"].rsplit(".", 1)[-1] for u in units
                   if u.get("kind") == "registration_exemption" and u.get("value")}
    assert not (no_exempt & with_exempt), f"противоречие по странам: {no_exempt & with_exempt}"


def test_bundle_is_copied_into_the_docker_image():
    """Молчаливая поломка, поймана перед выкатом 21.10.

    Dockerfile копирует каталоги знаний по одному, перечислением. Забыть строку — значит
    получить на проде движок, который отвечает «не знаю» на любой вопрос, при зелёном
    /health и зелёных тестах: локально файлы на месте, в образе их нет.
    """
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text("utf-8")
    assert "knowledge/kg_entry/draft-v1.1/" in dockerfile, (
        "бандл правил въезда не копируется в образ — на проде движок режима будет пуст")
