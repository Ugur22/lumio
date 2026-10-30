import json

import pytest
from conftest import REPLY_PIECES, FakeStream

import server


DEFAULT_MODEL = server.settings.model


def make(api, name, **over):
    body = {"name": name, "base_url": "https://api.example.com/v1", "model": f"model-{name}", "key": "k" * 20} | over
    res = api.post("/api/profiles", json=body).json()
    return next(p["id"] for p in res["profiles"] if p["name"] == name)


def new_chat(api):
    return api.post("/api/chats").json()["id"]


def pick(api, cid, profile_id):
    return api.put(f"/api/chats/{cid}/behavior", json={"profile_id": profile_id})


def send(api, cid, text="hi", **extra):
    return api.post(f"/api/chats/{cid}/messages", json={"content": text, **extra})


@pytest.fixture
def models_used(fake_client):
    seen = []

    def create(model, messages, stream, **kw):
        seen.append(model)
        return FakeStream(REPLY_PIECES)

    fake_client.chat.completions.create = create
    return seen


def test_new_chat_is_stamped_with_the_default_profile(api):
    default = api.get("/api/profiles").json()["active"]

    assert api.post("/api/chats").json()["profile_id"] == default


def test_chat_with_its_own_profile_ignores_the_default_of_another_chat(api, models_used):
    other = make(api, "Other")
    a, b = new_chat(api), new_chat(api)
    assert pick(api, a, other).status_code == 200

    send(api, a)
    send(api, b)

    assert models_used == ["model-Other", DEFAULT_MODEL]


def test_activate_does_not_move_chats_that_have_their_own_profile(api, models_used):
    other = make(api, "Other")
    cid = new_chat(api)  # stamped with the original default
    api.post(f"/api/profiles/{other}/activate")

    send(api, cid)
    send(api, new_chat(api))

    assert models_used == [DEFAULT_MODEL, "model-Other"]


def test_deleted_profile_falls_back_to_the_default(api, models_used):
    other = make(api, "Other")
    cid = new_chat(api)
    pick(api, cid, other)
    api.delete(f"/api/profiles/{other}")

    assert send(api, cid).status_code == 200
    assert "model-Other" not in models_used


def test_null_clears_the_choice_and_omitting_it_keeps_it(api):
    other = make(api, "Other")
    cid = new_chat(api)
    pick(api, cid, other)

    kept = api.put(f"/api/chats/{cid}/behavior", json={"temperature": 0.5}).json()
    cleared = pick(api, cid, None).json()

    assert kept["profile_id"] == other
    assert cleared["profile_id"] is None


def test_unknown_or_malformed_profile_is_rejected(api):
    cid = new_chat(api)

    assert pick(api, cid, "nope1234").status_code == 404
    assert pick(api, cid, "../x").status_code == 422
    assert api.get(f"/api/chats/{cid}").json()["profile_id"] == "default"


def test_chat_file_without_profile_id_loads_and_follows_the_default(api, models_used):
    cid = new_chat(api)
    path = server.chat_path(cid)
    data = json.loads(path.read_text())
    del data["profile_id"]
    path.write_text(json.dumps(data))

    assert api.get(f"/api/chats/{cid}").json()["profile_id"] is None
    assert send(api, cid).status_code == 200
    assert models_used == [DEFAULT_MODEL]


def test_vision_check_uses_the_chats_profile(api, models_used):
    seeing = make(api, "Seeing", vision=True)
    blind = make(api, "Blind", vision=False)
    cid = new_chat(api)
    image = {"media_type": "image/png", "data": "iVBORw0KGgo="}

    pick(api, cid, blind)
    assert send(api, cid, images=[image]).status_code == 422
    pick(api, cid, seeing)
    assert send(api, cid, images=[image]).status_code == 200


def test_image_model_check_uses_the_chats_profile(api, models_used):
    plain = make(api, "Plain")
    cid = new_chat(api)
    pick(api, cid, plain)
    api.post(f"/api/profiles/{make(api, 'Painter', image_model='img-1')}/activate")

    assert send(api, cid, illustrate=True).status_code == 422


def test_switching_mid_chat_keeps_messages_and_next_send_uses_the_new_profile(api, models_used):
    other = make(api, "Other")
    cid = new_chat(api)
    send(api, cid, "first")
    before = api.get(f"/api/chats/{cid}").json()["messages"]

    pick(api, cid, other)
    assert api.get(f"/api/chats/{cid}").json()["messages"] == before
    send(api, cid, "second")

    assert models_used[-1] == "model-Other"
    assert models_used[0] == DEFAULT_MODEL


def test_context_uses_the_chats_window(api):
    small = make(api, "Small", context_window=8000)
    big = make(api, "Big", context_window=64000)
    a, b = new_chat(api), new_chat(api)
    pick(api, a, small)
    pick(api, b, big)

    assert api.get(f"/api/chats/{a}/context").json()["window"] == 8000
    assert api.get(f"/api/chats/{b}/context").json()["window"] == 64000
