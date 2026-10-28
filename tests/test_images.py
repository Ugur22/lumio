import base64
import json
import os
import time

import pytest
from pydantic import ValidationError

import images
import server
from models import MAX_IMAGES, ImageData, NewMessage, Profile

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
IMG = {"media_type": "image/png", "data": PNG}


def new_chat(api):
    return api.post("/api/chats").json()["id"]


def use_profile(api, vision):
    body = {"name": "P", "base_url": "https://api.example.com/v1", "model": "m", "key": "k" * 20, "vision": vision}
    pid = api.post("/api/profiles", json=body).json()["profiles"][-1]["id"]
    api.post(f"/api/profiles/{pid}/activate")


def post(api, cid, **body):
    return api.post(f"/api/chats/{cid}/messages", json=body)


def done(res):
    block = [b for b in res.text.strip().split("\n\n") if b.startswith("event: done")][0]
    return json.loads(block.split("data: ", 1)[1])


# --- models ---

def test_image_data_rejects_bad_base64():
    with pytest.raises(ValidationError):
        ImageData(media_type="image/png", data="not base64!!")


def test_image_data_rejects_unknown_media_type():
    with pytest.raises(ValidationError):
        ImageData(media_type="image/svg+xml", data=PNG)


def test_message_needs_text_or_image():
    with pytest.raises(ValidationError):
        NewMessage(content="  ")
    assert NewMessage(content="", images=[IMG]).images


def test_message_caps_image_count():
    with pytest.raises(ValidationError):
        NewMessage(images=[IMG] * (MAX_IMAGES + 1))


def test_old_xai_profile_defaults_to_vision():
    assert Profile(id="a", name="x", base_url="https://api.x.ai/v1", model="grok-4").vision
    assert not Profile(id="b", name="x", base_url="https://api.openai.com/v1", model="m").vision
    assert not Profile(id="c", name="x", base_url="https://api.x.ai/v1", model="m", vision=False).vision


# --- sending ---

def test_text_only_profile_rejects_images(api, calls):
    cid = new_chat(api)
    res = post(api, cid, content="look", images=[IMG])

    assert res.status_code == 422
    assert "can't read images" in res.json()["detail"]
    assert calls == []


def test_vision_profile_sends_content_parts_and_stores_a_ref(api, calls):
    use_profile(api, vision=True)
    cid = new_chat(api)
    chat = done(post(api, cid, content="what is this?", images=[IMG]))

    sent = calls[0][-1]["content"]
    assert sent[0] == {"type": "text", "text": "what is this?"}
    assert sent[1] == {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}}
    ref = chat["messages"][0]["images"][0]
    assert set(ref) == {"id", "media_type", "prompt"} and ref["prompt"] is None
    assert PNG not in json.dumps(chat)
    assert api.get(f"/api/chats/{cid}/images/{ref['id']}").content == base64.b64decode(PNG)


def test_image_only_message_gets_a_title(api, calls):
    use_profile(api, vision=True)
    chat = done(post(api, new_chat(api), images=[IMG]))

    assert chat["title"] == "Image"


def test_failed_call_stores_no_image_files(api, fake_client):
    from openai import OpenAIError

    def boom(**_):
        raise OpenAIError("down")

    fake_client.chat.completions.create = boom
    use_profile(api, vision=True)
    post(api, new_chat(api), content="x", images=[IMG])

    assert not server.settings.images_dir.exists() or not any(server.settings.images_dir.rglob("*.png"))


def test_history_resends_earlier_images_on_vision_profiles(api, calls):
    use_profile(api, vision=True)
    cid = new_chat(api)
    post(api, cid, content="one", images=[IMG])
    post(api, cid, content="two")

    first = calls[1][1]["content"]
    assert [p["type"] for p in first] == ["text", "image_url"]


def test_history_downgrades_images_on_text_only_profiles(api, calls):
    use_profile(api, vision=True)
    cid = new_chat(api)
    post(api, cid, content="one", images=[IMG])
    api.post("/api/profiles/default/activate")
    post(api, cid, content="two")

    assert calls[1][1]["content"] == f"one\n\n{server.IMAGE_UNSUPPORTED}"


# --- lifecycle ---

def test_pruned_image_becomes_a_placeholder_and_410(api, calls):
    use_profile(api, vision=True)
    cid = new_chat(api)
    chat = done(post(api, cid, content="one", images=[IMG]))
    ref = chat["messages"][0]["images"][0]
    old = time.time() - 40 * images.DAY
    for f in server.settings.images_dir.rglob("*.png"):
        os.utime(f, (old, old))

    assert images.prune(server.settings) == 1
    assert api.get(f"/api/chats/{cid}/images/{ref['id']}").status_code == 410
    post(api, cid, content="two")
    assert calls[1][1]["content"][-1] == {"type": "text", "text": server.IMAGE_GONE}


def test_prune_keeps_recent_images(api, calls):
    use_profile(api, vision=True)
    post(api, new_chat(api), content="x", images=[IMG])

    assert images.prune(server.settings) == 0
    assert any(server.settings.images_dir.rglob("*.png"))


def test_deleting_a_chat_deletes_its_images(api, calls):
    use_profile(api, vision=True)
    cid = new_chat(api)
    post(api, cid, content="x", images=[IMG])
    api.delete(f"/api/chats/{cid}")

    assert not (server.settings.images_dir / cid).exists()


def test_image_route_rejects_traversal_and_unknown_ids(api):
    cid = new_chat(api)

    assert api.get(f"/api/chats/{cid}/images/..%2F..%2Fsecret").status_code in (404, 422)
    assert api.get(f"/api/chats/{cid}/images/{'0' * 32}").status_code == 404
