import base64
import json

import pytest
from openai import OpenAIError

from models import LOCAL_USER, EditProfile, NewProfile, Profile
from conftest import FakeStream
import profile_store
from app import runtime, providers, story
from conftest import sse_blocks

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
    for block in sse_blocks(res.text):
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
    profile_store.save_store(runtime.settings, LOCAL_USER, profile_store.ProfileStore())
    raw = {"active": "a", "profiles": [{"id": "a", "name": "x", "base_url": "https://api.example.com/v1", "model": "m"}]}
    runtime.settings.profiles_file.write_text(json.dumps(raw))
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


def test_failed_image_logs_status_and_body(api, fake_client, caplog):
    setup_profile(api)
    reply_with(fake_client, "A\n\n[[image: a red barn]]\n\nB")

    class Rejected(OpenAIError):
        status_code = 400
        response = type("R", (), {"text": '{"code":"policy","error":"prompt rejected k' + "k" * 20 + '"}'})()

    def generate(**kw):
        raise Rejected("Error code: 400")

    fake_client.images.generate = generate
    with caplog.at_level("WARNING", logger="dolphinllm"):
        post(api, new_chat(api), content="x", illustrate=True)
    assert "400" in caplog.text and "prompt rejected" in caplog.text and "a red barn" in caplog.text
    assert "k" * 20 not in caplog.text


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


def test_history_sends_user_images_only_and_replays_illustration_directives(api, fake_client):
    setup_profile(api, vision=True)
    seen = []
    reply_with(fake_client, "A\n\n[[image: a red barn]]\n\nB", seen)
    generator(fake_client)
    cid = new_chat(api)
    post(api, cid, content="one", images=[USER_IMG], illustrate=True)
    post(api, cid, content="two", illustrate=True)

    history = seen[1]
    assert [p["type"] for p in history[1]["content"]] == ["text", "image_url"]
    assert history[2]["role"] == "assistant"
    assert history[2]["content"] == "A\n\n[[image: a red barn]]\n\nB"
    assert "image_url" not in json.dumps(history[2])


def test_history_for_handles_unknown_marker(api):
    from models import Chat, Message

    chat = Chat(id="a" * 32, messages=[Message(role="assistant", content=f"x [[img:{'b' * 32}]]")])
    assert story.history_for(chat)[0]["content"] == "x "


def test_illustrating_drops_html_block_instruction():
    from test_story import chat_with

    plain = story.system_for(chat_with())
    illustrated = story.system_for(chat_with(), illustrate=True)
    assert "style attributes" in plain
    assert "style attributes" not in illustrated
    assert "[[image:" in illustrated and "[[key]]" in illustrated


# --- failure events ---

def test_failed_image_emits_illustration_failed_before_done(api, fake_client):
    setup_profile(api)
    reply_with(fake_client, "A\n\n[[image: a red barn]]\n\nB")

    class Rejected(OpenAIError):
        status_code = 400
        response = type("R", (), {"text": '{"error":\n "prompt rejected k' + "k" * 20 + '"}'})()

    def generate(**kw):
        raise Rejected("Error code: 400")

    fake_client.images.generate = generate
    cid = new_chat(api)
    evs = events(post(api, cid, content="x", illustrate=True))
    names = [n for n, _ in evs]
    assert names.count("illustration_failed") == 1 and names[-1] == "done"
    data = dict(evs)["illustration_failed"]
    assert data["prompt"] == "a red barn" and data["status"] == 400
    assert "prompt rejected" in data["detail"] and "k" * 20 not in json.dumps(evs) and "\n" not in data["detail"]
    assert len(data["detail"]) <= 200
    assert "illustration" not in api.get(f"/api/chats/{cid}").text


def test_value_error_failure_has_null_status(api, fake_client):
    setup_profile(api)
    reply_with(fake_client, "A\n\n[[image: x]]\n\nB")
    generator(fake_client, data="")
    evs = events(post(api, new_chat(api), content="x", illustrate=True))
    assert dict(evs)["illustration_failed"] == {"prompt": "x", "status": None, "detail": "the provider returned no image data"}


def test_successful_illustrations_emit_no_failure(api, fake_client):
    setup_profile(api)
    reply_with(fake_client, STORY)
    generator(fake_client)
    assert "illustration_failed" not in [n for n, _ in events(post(api, new_chat(api), content="x", illustrate=True))]


def test_readable_reason_unwraps_json_error_bodies():
    body = '{"code":"imagine:content-moderated","error":"Generated image rejected by content moderation.","usage":{"cost_in_usd_ticks":1}}'
    assert providers.readable_reason(body) == "Generated image rejected by content moderation."
    assert providers.readable_reason('{"error":{"message":"bad  prompt"}}') == "bad prompt"
    assert providers.readable_reason("plain text") == "plain text"
    assert providers.readable_reason('{"other":1}') == '{"other":1}'


# --- directives that used to vanish silently ---

def serve_pieces(fake_client, pieces):
    fake_client.chat.completions.create = lambda **kw: FakeStream(pieces)


def send_illustrated(api, fake_client, pieces):
    setup_profile(api)
    serve_pieces(fake_client, pieces)
    generator(fake_client, log=(log := []))
    evs = events(post(api, new_chat(api), content="x", illustrate=True))
    return evs, log


@pytest.mark.parametrize(
    "directive, prompt",
    [
        ("[[image: a sign reading [exit], dusk]]", "a sign reading [exit], dusk"),
        ("[[image: a barn\nat dawn,\n  in mist]]", "a barn at dawn, in mist"),
        ("[[image:no space]]", "no space"),
    ],
)
def test_directives_the_clients_accept_get_a_picture(api, fake_client, directive, prompt):
    evs, log = send_illustrated(api, fake_client, ["Once.\n\n", directive, "\n\nThen."])
    reply = evs[-1][1]["messages"][1]
    assert [e["prompt"] for e in reply["images"]] == [prompt] and [k["prompt"] for k in log] == [prompt]
    assert "[[image" not in reply["content"] and reply["content"].startswith("Once.\n\n[[img:")


@pytest.mark.parametrize(
    "pieces",
    [["A\n\n[[image: a barn]", "]\n\nB"], ["A\n\n[[image: a barn]", "]"], ["A\n\n[[image: a barn]]"], ["A\n\n[[image: a b", "arn]", "]"]],
)
def test_a_directive_closing_across_chunks_or_at_the_very_end_gets_a_picture(api, fake_client, pieces):
    evs, log = send_illustrated(api, fake_client, pieces)
    reply = evs[-1][1]["messages"][1]
    assert [k["prompt"] for k in log] == ["a barn"] and len(reply["images"]) == 1
    assert "[[image" not in reply["content"]


def test_an_unclosed_directive_is_never_left_as_text_and_is_reported(api, fake_client, caplog):
    with caplog.at_level("WARNING", logger="dolphinllm"):
        evs, log = send_illustrated(api, fake_client, ["A\n\n[[image: a barn at da", "wn, and it was cut off"])
    reply = evs[-1][1]["messages"][1]
    assert log == [] and reply["images"] == [] and "[[image" not in reply["content"] and reply["content"].startswith("A")
    failed = [d for n, d in evs if n == "illustration_failed"]
    assert len(failed) == 1 and "never closed" in failed[0]["detail"] and failed[0]["status"] is None
    assert "never closed" in caplog.text


def test_an_empty_directive_is_removed_and_reported(api, fake_client):
    evs, log = send_illustrated(api, fake_client, ["A\n\n[[image:  ]]\n\nB"])
    reply = evs[-1][1]["messages"][1]
    assert log == [] and reply["content"] == "A\n\nB"
    assert [d["detail"] for n, d in evs if n == "illustration_failed"] == ["the picture description was empty"]


def test_directives_over_the_cap_are_reported_not_silent(api, fake_client, caplog):
    with caplog.at_level("WARNING", logger="dolphinllm"):
        evs, log = send_illustrated(api, fake_client, [f"P{i}\n\n[[image: scene {i}]]\n\n" for i in range(5)])
    reply = evs[-1][1]["messages"][1]
    assert len(log) == 3 and len(reply["images"]) == 3 and "[[image" not in reply["content"]
    failed = [d for n, d in evs if n == "illustration_failed"]
    assert [d["prompt"] for d in failed] == ["scene 3", "scene 4"]
    assert all("at most 3" in d["detail"] for d in failed) and "at most 3" in caplog.text
    assert [n for n, _ in evs][-1] == "done"


def test_directives_with_illustrate_off_are_removed_and_reported(api, fake_client, caplog):
    setup_profile(api)
    serve_pieces(fake_client, ["A\n\n[[image: a sign [exit], dusk]]\n\n[[image: a barn\nat dawn]]\n\nB"])
    generator(fake_client, log=(log := []))
    with caplog.at_level("INFO", logger="dolphinllm"):
        evs = events(post(api, new_chat(api), content="x"))
    reply = evs[-1][1]["messages"][1]
    assert log == [] and reply["images"] == [] and "[[image" not in reply["content"] and reply["content"].startswith("A")
    failed = [d for n, d in evs if n == "illustration_failed"]
    assert len(failed) == 2 and all("off" in d["detail"] for d in failed)
    assert failed[1]["prompt"] == "a barn at dawn" and "illustrations were off" in caplog.text


# --- illustrate off: nothing of a directive reaches the client or the model ---

def streamed(evs):
    return "".join(d["text"] for n, d in evs if n == "delta")


@pytest.mark.parametrize(
    "pieces",
    [
        ["A\n\n[[image: a sign [exit], dusk]]\n\nB"],
        ["A\n\n[", "[image: a sign [exit], ", "dusk]", "]\n\nB"],
        ["A\n\n[[ima", "ge: a sign [exit], dusk]]\n\nB"],
        ["A\n\n[[image:", " a sign\n[exit], dusk]]", "\n\nB"],
        list("A\n\n[[image: a sign [exit], dusk]]\n\nB"),
    ],
)
def test_directives_never_reach_the_delta_stream_when_illustrate_is_off(api, fake_client, pieces):
    setup_profile(api)
    serve_pieces(fake_client, pieces)
    evs = events(post(api, new_chat(api), content="x"))
    assert "[[" not in streamed(evs) and "image" not in streamed(evs)
    assert streamed(evs).replace("\n", "") == "AB" == evs[-1][1]["messages"][1]["content"].replace("\n", "")
    assert [d["detail"] for n, d in evs if n == "illustration_failed"] == ["illustrations were off for this message"]


def test_other_brackets_and_partial_openers_are_streamed_when_illustrate_is_off(api, fake_client):
    setup_profile(api)
    serve_pieces(fake_client, ["see [1] and [[note]]", " then [[ima", "ge ok] and a final [[", "image"])
    evs = events(post(api, new_chat(api), content="x"))
    text = "see [1] and [[note]] then [[image ok] and a final [[image"
    assert streamed(evs) == text and evs[-1][1]["messages"][1]["content"] == text


def test_a_directive_cut_off_by_the_end_of_the_reply_is_not_streamed_or_saved(api, fake_client):
    setup_profile(api)
    serve_pieces(fake_client, ["A\n\n[[image: a barn at da", "wn"])
    evs = events(post(api, new_chat(api), content="x"))
    assert streamed(evs).strip() == "A" == evs[-1][1]["messages"][1]["content"].strip()


def test_directives_still_stream_as_text_when_illustrating(api, fake_client):
    evs, _ = send_illustrated(api, fake_client, ["A\n\n[[image: a barn]]\n\nB"])
    assert "[[image: a barn]]" in streamed(evs)


def test_history_and_prompt_stop_cueing_directives_when_illustrate_is_off(api, fake_client):
    setup_profile(api)
    seen = []
    reply_with(fake_client, "Once.\n\n[[image: a red barn]]\n\nThen.\n\n[[image: a broken [one], x]]\n\nEnd.", seen)
    generator(fake_client)
    cid = new_chat(api)
    post(api, cid, content="one", illustrate=True)
    reply_with(fake_client, "Next.", seen)
    post(api, cid, content="next chapter")

    system, *history = seen[1]
    assert history[1] == {"role": "assistant", "content": "Once.\n\nThen.\n\nEnd."}
    assert "[[img:" not in json.dumps(seen[1]) and "red barn" not in json.dumps(history)
    assert "do not write [[image:" in system["content"]
    assert "do not write [[image:" not in seen[0][0]["content"]


def test_the_no_pictures_note_is_only_for_chats_that_had_pictures(api, fake_client):
    setup_profile(api)
    seen = []
    reply_with(fake_client, "plain", seen)
    cid = new_chat(api)
    post(api, cid, content="a")
    post(api, cid, content="b")
    assert "[[image:" not in seen[1][0]["content"]


def test_a_picture_only_reply_is_not_sent_as_a_blank_turn_when_illustrate_is_off(api, fake_client):
    setup_profile(api)
    seen = []
    reply_with(fake_client, "[[image: a barn]]", seen)
    generator(fake_client)
    cid = new_chat(api)
    post(api, cid, content="draw", illustrate=True)
    reply_with(fake_client, "ok", seen)
    post(api, cid, content="now words")
    assert [m["role"] for m in seen[1]] == ["system", "user"]
