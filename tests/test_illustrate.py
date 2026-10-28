import base64
import json

import pytest
from openai import OpenAIError

import server
from models import EditProfile, NewProfile, Profile
from conftest import FakeStream

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"
PNG = base64.b64encode(PNG_BYTES).decode()
USER_IMG = {"media_type": "image/png", "data": PNG}
HEX = "[0-9a-f]{32}"


def setup_profile(api, image_model="img-1", vision=False):
    body = {"name": "P", "base_url": "https://api.example.com/v1", "model": "m", "key": "k" * 20, "vision": vision}
    if image_model:
        body["image_model"] = image_model
    pid = api.post("/api/profiles", json=body).json()["profiles"][-1]["id"]
    api.post(f"/api/profiles/{pid}/activate")
    return pid


def new_chat(api):
    return api.post("/api/chats").json()["id"]


def post(api, cid, **body):
    return api.post(f"/api/chats/{cid}/messages", json=body)


def events(res):
    out = []
    for block in res.text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def reply_with(fake_client, text, seen=None):
    def create(model, messages, stream, **kw):
        if seen is not None:
            seen.append(messages)
        return FakeStream([text[: len(text) // 2], text[len(text) // 2 :]])

    fake_client.chat.completions.create = create


def generator(fake_client, fail_on=(), data=PNG, log=None):
    def generate(**kw):
        if log is not None:
            log.append(kw)
        if any(f in kw["prompt"] for f in fail_on):
            raise OpenAIError("boom k" * 1 + " " + "k" * 20)
        return type("R", (), {"data": [type("D", (), {"b64_json": data})()]})()

    fake_client.images.generate = generate


STORY = "Once.\n\n[[image: a red barn at dawn]]\n\nThen.\n\n[[image: a fox in snow]]\n\nEnd."


# --- models ---

def test_image_model_defaults_and_xai_preset():
    assert Profile(id="a", name="x", base_url="https://api.openai.com/v1", model="m").image_model is None
    assert Profile(id="b", name="x", base_url="https://api.x.ai/v1", model="m").image_model == "grok-imagine-image-2.0"
    assert Profile(id="c", name="x", base_url="https://api.x.ai/v1", model="m", image_model=None).image_model is None


def test_old_profile_file_without_image_model_loads(api):
    server.profile_store.save_store(server.settings, server.profile_store.ProfileStore())
    raw = {"active": "a", "profiles": [{"id": "a", "name": "x", "base_url": "https://api.example.com/v1", "model": "m"}]}
    server.settings.profiles_file.write_text(json.dumps(raw))
    assert api.get("/api/profiles").json()["profiles"][0]["image_model"] is None


def test_edit_profile_can_set_and_clear_image_model(api):
    pid = setup_profile(api, image_model=None)
    listing = api.patch(f"/api/profiles/{pid}", json={"image_model": "img-2"}).json()
    assert listing["profiles"][-1]["image_model"] == "img-2"
    listing = api.patch(f"/api/profiles/{pid}", json={"name": "Q"}).json()
    assert listing["profiles"][-1]["image_model"] == "img-2"
    listing = api.patch(f"/api/profiles/{pid}", json={"image_model": None}).json()
    assert listing["profiles"][-1]["image_model"] is None
    assert EditProfile(image_model="  ").image_model is None
    assert NewProfile(name="n", base_url="https://a.b/v1", model="m", image_model="").image_model is None


# --- sending ---

def test_illustrate_without_image_model_is_422(api, calls):
    setup_profile(api, image_model=None)
    res = post(api, new_chat(api), content="story", illustrate=True)
    assert res.status_code == 422
    assert calls == []


def test_directives_become_images_on_the_assistant_message(api, fake_client):
    setup_profile(api)
    seen, log = [], []
    reply_with(fake_client, STORY, seen)
    generator(fake_client, log=log)
    cid = new_chat(api)

    res = post(api, cid, content="tell a story", illustrate=True)
    evs = events(res)

    assert "[[image:" in seen[0][0]["content"]
    assert log[0] == {"model": "img-1", "prompt": "a red barn at dawn", "n": 1, "response_format": "b64_json"}
    names = [n for n, _ in evs]
    assert names.count("image") == 2 and names[-1] == "done" and names.index("image") < names.index("done")
    chat = evs[-1][1]
    user, assistant = chat["messages"]
    assert user["images"] == []
    ids = [i["id"] for i in assistant["images"]]
    assert [i["prompt"] for i in assistant["images"]] == ["a red barn at dawn", "a fox in snow"]
    assert assistant["content"] == f"Once.\n\n[[img:{ids[0]}]]\n\nThen.\n\n[[img:{ids[1]}]]\n\nEnd."
    assert [d for n, d in evs if n == "image"][0] == {"id": ids[0], "media_type": "image/png", "prompt": "a red barn at dawn"}
    assert api.get(f"/api/chats/{cid}/images/{ids[0]}").content == PNG_BYTES
    assert api.get(f"/api/chats/{cid}").json()["messages"][1]["content"] == assistant["content"]


def test_system_prompt_mentions_directive_only_when_illustrating(api, fake_client):
    setup_profile(api)
    seen = []
    reply_with(fake_client, "plain", seen)
    generator(fake_client)
    cid = new_chat(api)
    post(api, cid, content="a")
    post(api, cid, content="b", illustrate=True)
    assert "[[image:" not in seen[0][0]["content"]
    assert "[[image:" in seen[1][0]["content"]


def test_directives_beyond_the_cap_are_removed(api, fake_client):
    setup_profile(api)
    text = "\n\n".join(f"P{i}\n\n[[image: scene {i}]]" for i in range(5))
    reply_with(fake_client, text)
    log = []
    generator(fake_client, log=log)

    chat = events(post(api, new_chat(api), content="x", illustrate=True))[-1][1]
    reply = chat["messages"][1]
    assert len(log) == 3 and len(reply["images"]) == 3
    assert "[[image:" not in reply["content"]
    assert "\n\n\n" not in reply["content"]


def test_failed_image_drops_only_its_directive_and_redacts_key(api, fake_client, caplog):
    setup_profile(api)
    reply_with(fake_client, STORY)
    generator(fake_client, fail_on=("barn",))

    with caplog.at_level("WARNING", logger="dolphinllm"):
        evs = events(post(api, new_chat(api), content="x", illustrate=True))
    assert not any(n == "error" for n, _ in evs)
    reply = evs[-1][1]["messages"][1]
    assert len(reply["images"]) == 1 and reply["images"][0]["prompt"] == "a fox in snow"
    assert "barn" not in reply["content"] and "Once." in reply["content"] and "End." in reply["content"]
    assert "k" * 20 not in caplog.text and "k" * 20 not in json.dumps(evs)


def test_non_image_payload_is_dropped(api, fake_client):
    setup_profile(api)
    reply_with(fake_client, "A\n\n[[image: x]]\n\nB")
    generator(fake_client, data=base64.b64encode(b"<svg/>").decode())
    reply = events(post(api, new_chat(api), content="x", illustrate=True))[-1][1]["messages"][1]
    assert reply["images"] == [] and reply["content"] == "A\n\nB"


def test_stray_directives_are_stripped_when_not_illustrating(api, fake_client):
    setup_profile(api)
    reply_with(fake_client, "A\n\n[[image: x]]\n\nB")
    generator(fake_client, log=(log := []))
    reply = events(post(api, new_chat(api), content="x"))[-1][1]["messages"][1]
    assert reply["content"] == "A\n\nB" and reply["images"] == [] and log == []


def test_history_sends_user_images_only_and_describes_illustrations(api, fake_client):
    setup_profile(api, vision=True)
    seen = []
    reply_with(fake_client, "A\n\n[[image: a red barn]]\n\nB", seen)
    generator(fake_client)
    cid = new_chat(api)
    post(api, cid, content="one", images=[USER_IMG], illustrate=True)
    post(api, cid, content="two")

    history = seen[1]
    assert [p["type"] for p in history[1]["content"]] == ["text", "image_url"]
    assert history[2]["role"] == "assistant"
    assert history[2]["content"] == "A\n\n[illustration: a red barn]\n\nB"
    assert "image_url" not in json.dumps(history[2])


def test_history_for_handles_unknown_marker(api):
    from models import Chat, Message

    chat = Chat(id="a" * 32, messages=[Message(role="assistant", content=f"x [[img:{'b' * 32}]]")])
    assert server.history_for(chat)[0]["content"] == "x [illustration]"
