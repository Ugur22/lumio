import pytest
from conftest import REPLY_PIECES, FakeStream
from test_story import chat_with, new_chat, send

import server


def put(api, cid, **body):
    return api.put(f"/api/chats/{cid}/behavior", json=body)


@pytest.fixture
def kwargs_seen(fake_client):
    seen = []

    def create(model, messages, stream, **kw):
        seen.append({"messages": messages, **kw})
        return FakeStream(REPLY_PIECES)

    fake_client.chat.completions.create = create
    return seen


def test_system_prompt_leads_the_system_message():
    system = server.system_for(chat_with(system_prompt="  Write as a noir narrator.  "))

    assert system.startswith("Write as a noir narrator.\n\n")
    assert system.endswith(server.SYSTEM_PROMPT)


def test_blank_system_prompt_changes_nothing():
    assert server.system_for(chat_with(system_prompt="   ")) == server.SYSTEM_PROMPT


def test_chat_sends_no_sampling_parameters_by_default(api, kwargs_seen):
    send(api, new_chat(api), "hi")

    assert set(kwargs_seen[0]) == {"messages", "stream_options"}


def test_saved_behavior_reaches_the_next_request_and_stays_per_chat(api, kwargs_seen):
    a, b = new_chat(api), new_chat(api)
    res = put(api, a, system_prompt="Be terse.", temperature=1.3, top_p=0.9, frequency_penalty=-0.5, max_tokens=4000)
    assert res.status_code == 200 and res.json()["temperature"] == 1.3

    send(api, a, "hi")
    send(api, b, "hi")

    assert kwargs_seen[0]["temperature"] == 1.3
    assert kwargs_seen[0]["top_p"] == 0.9
    assert kwargs_seen[0]["frequency_penalty"] == -0.5
    assert kwargs_seen[0]["max_tokens"] == 4000
    assert kwargs_seen[0]["messages"][0]["content"].startswith("Be terse.")
    assert "temperature" not in kwargs_seen[1]
    assert not kwargs_seen[1]["messages"][0]["content"].startswith("Be terse.")


def test_zero_is_a_real_value_and_null_clears_it(api, kwargs_seen):
    cid = new_chat(api)
    put(api, cid, temperature=0)
    send(api, cid, "hi")
    assert kwargs_seen[0]["temperature"] == 0

    put(api, cid, temperature=None)
    send(api, cid, "again")
    assert "temperature" not in kwargs_seen[1]


@pytest.mark.parametrize(
    "body",
    [
        {"temperature": 2.5},
        {"temperature": -0.1},
        {"top_p": 1.5},
        {"frequency_penalty": 3},
        {"max_tokens": 0},
        {"system_prompt": "x" * 10_001},
    ],
)
def test_out_of_range_behavior_is_rejected(api, body):
    assert put(api, new_chat(api), **body).status_code == 422


def test_behavior_for_a_missing_chat_is_404(api):
    assert put(api, "f" * 32, temperature=1).status_code == 404


def test_chat_saved_before_behavior_existed_still_loads(api):
    cid = new_chat(api)
    chat = api.get(f"/api/chats/{cid}").json()

    assert chat["system_prompt"] == "" and chat["temperature"] is None and chat["max_tokens"] is None


def provider_error(raw, provider="Moonshot"):
    from openai import BadRequestError
    import httpx2 as httpx

    body = {"message": "Provider returned error", "code": 400, "metadata": {"raw": raw, "provider_name": provider}}
    res = httpx.Response(400, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    return BadRequestError("Error code: 400 - " + str(body), response=res, body=body)


def test_openrouter_upstream_reason_is_shown_not_just_provider_returned_error():
    e = provider_error('{"error": {"message": "invalid temperature: only 1 is allowed for this model"}}')

    assert server.error_text(e) == (
        "Provider returned error (Moonshot: invalid temperature: only 1 is allowed for this model)"
    )


def test_error_without_openrouter_metadata_keeps_the_sdk_message():
    assert server.error_text(server.OpenAIError("upstream down")) == "upstream down"


def test_rejected_request_reports_the_upstream_reason_to_the_client(api, fake_client):
    def boom(**_):
        raise provider_error("max_tokens too large")

    fake_client.chat.completions.create = boom
    res = api.post(f"/api/chats/{new_chat(api)}/messages", json={"content": "hi"})

    assert res.status_code == 502
    assert "Moonshot: max_tokens too large" in res.json()["detail"]
