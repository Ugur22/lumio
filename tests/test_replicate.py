"""Illustration through Replicate: `image_model` starting with `replicate:` skips the OpenAI client. Offline."""

import base64
import json

import httpx2
import pytest

import profile_store
import secret_store
from app import providers
from models import LOCAL_USER
from test_illustrate import PNG_BYTES, events, generator, new_chat, post, reply_with, setup_profile

TOKEN = "r8_" + "s3cr3t" * 5
API = "https://api.replicate.com/v1"
GET_URL = f"{API}/predictions/abc"
IMG_URL = "https://replicate.delivery/x/out.png"
TEXT = "Once.\n\n[[image: a red barn]]\n\nEnd."


@pytest.fixture(autouse=True)
def token_account(monkeypatch):
    # The real helper lives in profile_store on the other branch; this keeps the tests independent of it.
    monkeypatch.setattr(profile_store, "replicate_account", lambda user: f"replicate-{user.id}", raising=False)
    secret_store.set_key(TOKEN, f"replicate-{LOCAL_USER.id}")


@pytest.fixture
def sleeps(monkeypatch):
    seen = []
    monkeypatch.setattr(providers, "sleep", seen.append)
    return seen


def prediction(status="succeeded", output=(IMG_URL,), **extra):
    return {"status": status, "output": list(output) if isinstance(output, tuple) else output, "urls": {"get": GET_URL}, **extra}


def install(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(providers, "replicate_client", lambda: httpx2.Client(transport=httpx2.MockTransport(wrapped)))
    return seen


def png_response(request):
    return httpx2.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})


def route(post_body, get_bodies=(), download=png_response):
    gets = list(get_bodies)

    def handler(request):
        if request.url.host == "api.replicate.com":
            if request.method == "POST":
                return httpx2.Response(201, json=post_body)
            return httpx2.Response(200, json=gets.pop(0))
        return download(request)

    return handler


def generate(model="replicate:acme/flux", prompt="a red barn"):
    return providers.generate_replicate_image(TOKEN, model, prompt)


def test_parse_model():
    assert providers.parse_replicate_model("replicate:acme/flux") == ("acme", "flux", None)
    assert providers.parse_replicate_model("replicate:acme/flux-1.1:abc123") == ("acme", "flux-1.1", "abc123")
    for bad in ("replicate:", "replicate:flux", "replicate:a/b/c", "replicate:a/b:", "replicate:a/b:x y", "replicate:../x"):
        with pytest.raises(providers.ReplicateError):
            providers.parse_replicate_model(bad)


def test_success_via_prefer_wait(monkeypatch, sleeps):
    seen = install(monkeypatch, route(prediction()))
    data = generate()
    assert data.media_type == "image/png" and base64.b64decode(data.data) == PNG_BYTES
    post_req, download = seen
    assert str(post_req.url) == f"{API}/models/acme/flux/predictions"
    assert post_req.headers["authorization"] == f"Bearer {TOKEN}" and post_req.headers["prefer"] == "wait=60"
    assert json.loads(post_req.content) == {"input": {"prompt": "a red barn", "scheduler": "Euler flux beta"}}
    assert "authorization" not in download.headers  # the token never goes to the delivery host
    assert sleeps == []


def test_versioned_model_uses_the_predictions_endpoint(monkeypatch):
    seen = install(monkeypatch, route(prediction(output=IMG_URL)))  # a single string output is accepted too
    generate("replicate:acme/flux:v123")
    assert str(seen[0].url) == f"{API}/predictions"
    assert json.loads(seen[0].content)["version"] == "v123"


def test_success_via_polling(monkeypatch, sleeps):
    seen = install(monkeypatch, route(prediction("starting", output=None), [prediction("processing", output=None), prediction()]))
    assert generate().media_type == "image/png"
    gets = [r for r in seen if r.method == "GET" and r.url.host == "api.replicate.com"]
    assert len(gets) == 2 and all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in gets)
    assert len(sleeps) == 2


def test_polling_gives_up_after_the_cap(monkeypatch, sleeps):
    install(monkeypatch, route(prediction("processing", output=None), [prediction("processing", output=None)] * 500))
    with pytest.raises(providers.ReplicateError, match="too long"):
        generate()
    assert sum(sleeps) <= providers.REPLICATE_POLL_CAP_SECONDS


def test_poll_url_must_stay_on_replicate(monkeypatch, sleeps):
    body = prediction("starting", output=None)
    body["urls"] = {"get": "https://evil.example.com/p"}
    seen = install(monkeypatch, route(body))
    with pytest.raises(providers.ReplicateError, match="unexpected"):
        generate()
    assert len(seen) == 1


@pytest.mark.parametrize("status", ["failed", "canceled"])
def test_failed_prediction_carries_the_provider_error_without_the_token(monkeypatch, sleeps, status):
    install(monkeypatch, route(prediction("starting", output=None), [prediction(status, output=None, error=f"NSFW  detected {TOKEN}")]))
    with pytest.raises(providers.ReplicateError) as e:
        generate()
    assert "NSFW detected" in str(e.value) and TOKEN not in str(e.value)


def test_http_error_from_the_api(monkeypatch):
    install(monkeypatch, lambda r: httpx2.Response(401, json={"detail": "Invalid token"}))
    with pytest.raises(providers.ReplicateError, match="401: Invalid token") as e:
        generate()
    assert e.value.status_code == 401


def test_download_that_is_not_an_image(monkeypatch):
    install(monkeypatch, route(prediction(), download=lambda r: httpx2.Response(200, content=b"<html>nope</html>")))
    with pytest.raises(providers.ReplicateError, match="unsupported image"):
        generate()


def test_oversize_download(monkeypatch):
    monkeypatch.setattr(providers, "MAX_IMAGE_BYTES", 100)
    install(monkeypatch, route(prediction(), download=lambda r: httpx2.Response(200, content=PNG_BYTES + b"0" * 200)))
    with pytest.raises(providers.ReplicateError, match="too large"):
        generate()


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "localhost"])
def test_delivery_url_on_a_private_address_is_refused(monkeypatch, host):
    seen = install(monkeypatch, route(prediction(output=(f"http://{host}/out.png",))))
    with pytest.raises(providers.ReplicateError, match="public"):
        generate()
    assert len(seen) == 1  # only the prediction request was made


def test_redirect_to_a_private_address_is_refused(monkeypatch):
    def download(request):
        return httpx2.Response(302, headers={"location": "http://10.0.0.5/internal.png"})

    seen = install(monkeypatch, route(prediction(), download=download))
    with pytest.raises(providers.ReplicateError, match="public"):
        generate()
    assert [r.url.host for r in seen] == ["api.replicate.com", "replicate.delivery"]


def test_public_redirect_is_followed(monkeypatch):
    def download(request):
        if request.url.host == "replicate.delivery":
            return httpx2.Response(302, headers={"location": "https://cdn.example.com/out.png"})
        return png_response(request)

    install(monkeypatch, route(prediction(), download=download))
    assert generate().media_type == "image/png"


def test_too_many_redirects(monkeypatch):
    install(monkeypatch, route(prediction(), download=lambda r: httpx2.Response(302, headers={"location": IMG_URL})))
    with pytest.raises(providers.ReplicateError, match="too many"):
        generate()


def replicate_chat(api, fake_client, image_model="replicate:acme/flux"):
    setup_profile(api, image_model=image_model)
    reply_with(fake_client, TEXT)
    return new_chat(api)


def test_replicate_model_dispatches_there_and_not_to_the_openai_client(api, fake_client, monkeypatch):
    log = []
    generator(fake_client, log=log)
    install(monkeypatch, route(prediction()))
    evs = events(post(api, replicate_chat(api, fake_client), content="x", illustrate=True))
    assert log == []
    names = [n for n, _ in evs]
    assert names.count("image") == 1 and "illustration_failed" not in names and names[-1] == "done"


def test_plain_model_still_uses_the_openai_path(api, fake_client, monkeypatch):
    log = []
    generator(fake_client, log=log)
    seen = install(monkeypatch, route(prediction()))
    evs = events(post(api, replicate_chat(api, fake_client, "img-1"), content="x", illustrate=True))
    assert len(log) == 1 and seen == [] and [n for n, _ in evs].count("image") == 1


def test_missing_token_is_409_before_streaming(api, fake_client):
    secret_store.delete_key(f"replicate-{LOCAL_USER.id}")
    cid = replicate_chat(api, fake_client)
    res = post(api, cid, content="x", illustrate=True)
    assert res.status_code == 409 and res.json()["detail"] == "No Replicate key. Add one in Providers."
    assert api.get(f"/api/chats/{cid}").json()["messages"] == []


def test_missing_token_does_not_matter_without_illustrate(api, fake_client):
    secret_store.delete_key(f"replicate-{LOCAL_USER.id}")
    assert post(api, replicate_chat(api, fake_client), content="x").status_code == 200


def test_malformed_replicate_model_is_422(api, fake_client):
    res = post(api, replicate_chat(api, fake_client, "replicate:nonsense"), content="x", illustrate=True)
    assert res.status_code == 422


def test_failures_never_expose_the_token(api, fake_client, monkeypatch, caplog, sleeps):
    install(monkeypatch, route(prediction("starting", output=None), [prediction("failed", output=None, error=f"bad things {TOKEN}")]))
    cid = replicate_chat(api, fake_client)
    with caplog.at_level("INFO", logger="dolphinllm"):
        res = post(api, cid, content="x", illustrate=True)
    failure = [d for n, d in events(res) if n == "illustration_failed"][0]
    assert "bad things" in failure["detail"]
    assert TOKEN not in res.text and TOKEN not in caplog.text
    assert TOKEN not in api.get(f"/api/chats/{cid}").text


def test_transport_error_becomes_a_failure_without_the_url(api, fake_client, monkeypatch, caplog):
    def handler(request):
        raise httpx2.ConnectError(f"cannot reach {request.url}", request=request)

    install(monkeypatch, handler)
    with caplog.at_level("INFO", logger="dolphinllm"):
        evs = events(post(api, replicate_chat(api, fake_client), content="x", illustrate=True))
    failure = [d for n, d in evs if n == "illustration_failed"][0]
    assert failure["status"] is None and "replicate.com" not in failure["detail"] and TOKEN not in caplog.text
    assert evs[-1][0] == "done"
