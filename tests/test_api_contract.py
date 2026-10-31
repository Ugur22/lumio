import json

import server

# Replies the schema cannot describe: image bytes and an SSE stream (DELETE chat is a 204 with no body at all).
NOT_JSON = {
    ("GET", "/api/chats/{chat_id}/images/{image_id}"),
    ("POST", "/api/chats/{chat_id}/messages"),
}


def test_every_json_route_replies_with_a_named_model():
    """The frontend types are generated from the OpenAPI schema (make types); an anonymous dict or an undeclared reply would give them nothing to name."""
    anonymous = [
        f"{method.upper()} {path}"
        for path, operations in server.app.openapi()["paths"].items()
        for method, operation in operations.items()
        for code, reply in operation["responses"].items()
        if code.startswith("2")
        and "content" in reply
        and "$ref" not in json.dumps(reply["content"])
        and (method.upper(), path) not in NOT_JSON
    ]
    assert anonymous == []
