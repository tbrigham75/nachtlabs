"""The endpoint shapes the interface accepts must be the shapes the API accepts.

The setup wizard checks the endpoint rules in the browser, because the API cannot
report why it refused: pydantic's own reason is suppressed so submitted values
cannot be echoed, and a whole-object rule can only name the path "body". That
duplication is only safe while the two agree, and the failure mode of a
disagreement is the worst kind: the client rejecting something the server would
have taken, so a working configuration looks impossible.

The table below is therefore the contract. Each row is asserted twice, once
through the real API and once through the browser's own check, in the paired
front-end test of the same name. Adding a rule means adding a row to both.
"""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

# (name, base_url, pin, allow_private, allow_http, accepted)
SHAPES: list[tuple[str, str, list[str], bool, bool, bool]] = [
    # Accepted: the shape an operator on a LAN reaches for once it is https.
    ("lan over https", "https://192.168.1.50", "192.168.1.50", True, False, True),
    ("hostname over https", "https://ollama.lan", "192.168.1.50", True, False, True),
    ("public over https", "https://93.184.216.34", "93.184.216.34", False, False, True),
    # The http permission is irrelevant once the scheme is https, and this is the
    # shape the wizard offers by default, so it has to be accepted.
    (
        "https with the http flag on",
        "https://192.168.1.50",
        "192.168.1.50",
        True,
        True,
        True,
    ),
    (
        "loopback over http",
        "http://127.0.0.1:11434",
        "127.0.0.1",
        True,
        True,
        True,
    ),
    # Refused: each of these reached the server and came back 422.
    ("lan over http", "http://192.168.1.50:11434", "192.168.1.50", True, True, False),
    ("lan over http, no private", "https://192.168.1.50", "192.168.1.50", False, False, False),
    ("loopback, no private", "http://127.0.0.1:11434", "127.0.0.1", False, True, False),
    ("pin disagrees with origin", "https://192.168.1.99", "192.168.1.50", True, False, False),
    ("origin with a path", "https://192.168.1.50/api", "192.168.1.50", True, False, False),
    ("origin with credentials", "https://u:p@192.168.1.50", "192.168.1.50", True, False, False),
    ("not a scheme", "192.168.1.50:11434", "192.168.1.50", True, False, False),
    ("link local address", "https://169.254.1.1", "169.254.1.1", True, False, False),
    ("cloud metadata address", "https://169.254.169.254", "169.254.169.254", True, False, False),
]


def connection(owner: TestClient, base_url: str, pin: str, private: bool, http: bool):
    return owner.post(
        "/api/v1/integrations",
        json={
            "name": f"Shape {base_url}",
            "provider": "ollama",
            "base_url": base_url,
            "pinned_addresses": [pin],
            "allow_private": private,
            "allow_http": http,
        },
    )


@pytest.mark.parametrize(
    ("base_url", "pin", "private", "http", "accepted"),
    [row[1:] for row in SHAPES],
    ids=[row[0] for row in SHAPES],
)
def test_api_agrees_with_the_published_shape_table(
    owner: TestClient,
    base_url: str,
    pin: str,
    private: bool,
    http: bool,
    accepted: bool,
) -> None:
    response = connection(owner, base_url, pin, private, http)
    if accepted:
        assert response.status_code == 201, response.text
    else:
        # One refusal shape, whatever the rule: the API suppresses the reason, so
        # the interface has to be the one that explains it.
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation"


def test_every_refused_shape_reports_nothing_useful_for_the_operator(
    owner: TestClient,
) -> None:
    """The gap that made a client-side check necessary in the first place.

    A whole-object rule reports the path "body", so "Check the indicated fields"
    names no field. Pinned here so the reason this duplication exists is not lost,
    and so a future change that does surface the reason can retire the client
    check rather than duplicate it.
    """
    response = connection(owner, "http://192.168.1.50:11434", "192.168.1.50", True, True)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["message"] == "Check the indicated fields"
    assert error["fields"] == ["body"]


def test_a_refused_shape_creates_nothing(owner: TestClient) -> None:
    before = owner.get("/api/v1/integrations").json()
    connection(owner, "http://192.168.1.50:11434", "192.168.1.50", True, True)
    assert owner.get("/api/v1/integrations").json() == before
