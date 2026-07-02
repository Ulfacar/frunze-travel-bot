import asyncio

from app.agent.llm import OpenRouterMessages, _from_openai_response, _to_openai_messages, _to_openai_tools, llm_enabled


def test_openrouter_tool_schema_conversion():
    tools = [
        {
            "name": "search_tours",
            "description": "Find tours",
            "input_schema": {
                "type": "object",
                "properties": {"destination": {"type": "string"}},
                "required": ["destination"],
            },
        }
    ]

    converted = _to_openai_tools(tools)

    assert converted == [
        {
            "type": "function",
            "function": {
                "name": "search_tours",
                "description": "Find tours",
                "parameters": {
                    "type": "object",
                    "properties": {"destination": {"type": "string"}},
                    "required": ["destination"],
                },
            },
        }
    ]


def test_openrouter_message_conversion_keeps_tool_round_trip():
    messages = [
        {"role": "user", "content": "хочу тур"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "search_tours",
                    "input": {"destination": "Турция"},
                }
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "Hotel X"}]},
    ]

    converted = _to_openai_messages(messages)

    assert converted[1]["role"] == "assistant"
    assert converted[1]["tool_calls"][0]["function"]["name"] == "search_tours"
    assert '"destination": "Турция"' in converted[1]["tool_calls"][0]["function"]["arguments"]
    assert converted[2] == {"role": "tool", "tool_call_id": "call_1", "content": "Hotel X"}


def test_openrouter_response_conversion_to_agent_shape():
    resp = _from_openai_response(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "score_visa",
                                    "arguments": '{"country": "Германия"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )

    assert resp.stop_reason == "tool_use"
    assert resp.content[0].type == "tool_use"
    assert resp.content[0].name == "score_visa"
    assert resp.content[0].input == {"country": "Германия"}


def test_openrouter_response_parses_usage():
    resp = _from_openai_response(
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cost": 0.0123,
                "cache_read_input_tokens": 80,
                "cache_creation_input_tokens": 10,
            },
            "choices": [{"message": {"content": "ок"}}],
        }
    )

    assert resp.usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "cost": 0.0123,
        "cache_read_input_tokens": 80,
        "cache_creation_input_tokens": 10,
    }
    assert resp.model_dump()["usage"]["cache_read_input_tokens"] == 80


def test_openrouter_payload_adds_cache_control_for_anthropic_system(monkeypatch):
    payloads = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            payloads.append(json)
            return FakeResponse()

    from app.agent import llm

    monkeypatch.setattr(llm.settings, "openrouter_api_key", "key")
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(OpenRouterMessages().create(
        model="anthropic/test-model",
        max_tokens=123,
        temperature=0.2,
        system="system prompt",
        tools=[],
        messages=[{"role": "user", "content": "hi"}],
    ))

    content = payloads[0]["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["text"] == "system prompt"
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert payloads[0]["max_tokens"] == 123
    assert payloads[0]["temperature"] == 0.2


def test_openrouter_payload_can_skip_cache_control_for_volatile_system(monkeypatch):
    payloads = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            payloads.append(json)
            return FakeResponse()

    from app.agent import llm

    monkeypatch.setattr(llm.settings, "openrouter_api_key", "key")
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(OpenRouterMessages().create(
        model="anthropic/test-model",
        max_tokens=123,
        temperature=0.2,
        system="volatile system prompt",
        tools=[],
        messages=[{"role": "user", "content": "hi"}],
        cacheable_system=False,
    ))

    assert payloads[0]["messages"][0]["content"] == "volatile system prompt"
    assert "tools" not in payloads[0]


def test_openrouter_payload_keeps_non_anthropic_system_as_string(monkeypatch):
    payloads = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            payloads.append(json)
            return FakeResponse()

    from app.agent import llm

    monkeypatch.setattr(llm.settings, "openrouter_api_key", "key")
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(OpenRouterMessages().create(
        model="openai/test-model",
        max_tokens=123,
        temperature=0.2,
        system="system prompt",
        tools=[],
        messages=[{"role": "user", "content": "hi"}],
    ))

    assert payloads[0]["messages"][0]["content"] == "system prompt"


def test_llm_enabled_uses_openrouter_key_only(monkeypatch):
    from app.agent import llm

    monkeypatch.setattr(llm.settings, "openrouter_api_key", "")
    monkeypatch.setattr(llm.settings, "anthropic_api_key", "old-key")
    assert llm_enabled() is False

    monkeypatch.setattr(llm.settings, "openrouter_api_key", "or-key")
    assert llm_enabled() is True
