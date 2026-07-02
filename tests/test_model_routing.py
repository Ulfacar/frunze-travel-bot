from app.agent import routing


def test_choose_model_routes_all_funnels(monkeypatch):
    monkeypatch.setattr(routing.settings, "llm_model_main", "main-model")
    monkeypatch.setattr(routing.settings, "llm_model_cheap", "cheap-model")

    assert routing.choose_model("visa", escalated=False) == "cheap-model"
    assert routing.choose_model("visa", escalated=True) == "cheap-model"
    assert routing.choose_model("tickets", escalated=False) == "cheap-model"
    assert routing.choose_model("tickets", escalated=True) == "cheap-model"
    assert routing.choose_model("tours", escalated=False) == "cheap-model"
    assert routing.choose_model("tours", escalated=True) == "main-model"


def test_tours_input_precheck_escalates_commercial_messages():
    assert routing.should_escalate_tours_input("Можно скидку на этот тур?")
    assert routing.should_escalate_tours_input("Какая стоимость и как оплатить?")
    assert routing.should_escalate_tours_input("Хочу забронировать")
    assert not routing.should_escalate_tours_input("Хочу тур в Турцию на июль")
