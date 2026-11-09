import pytest


def test_root_http_contract(api_client):
    response = api_client.get("/")

    assert response.status_code == 200
    assert response.headers.get("content-type") == "text/plain; charset=utf-8"
    if response.content != b"QA Interview Lab backend\n":
        pytest.fail("Root HTTP response does not match the documented plain text", pytrace=False)

    head = api_client.head("/")
    assert head.status_code == 200
    assert head.content == b""
