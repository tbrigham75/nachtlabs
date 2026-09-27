"""Pinned-destination HTTP. Never resolves a hostname after credentials are selected."""

import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from nachtlabs.integrations.contracts import ProviderError

MAX_RESPONSE = 2 * 1024 * 1024
# Explicitly reject known cloud credential/metadata addresses even in private mode.
METADATA = {
    ipaddress.ip_address(v)
    for v in (
        "169.254.169.254",
        "169.254.170.2",
        "100.100.100.200",
        "168.63.129.16",
        "fd00:ec2::254",
    )
}


@dataclass(frozen=True)
class Endpoint:
    url: str
    addresses: tuple[str, ...]
    allow_private: bool = False
    allow_http: bool = False
    timeout_seconds: int = 15
    # Cleartext to a non-globally-routable address, which is otherwise refused.
    # Passed in rather than read from settings so validate() stays pure and
    # testable. Does not extend to publicly routable addresses, and does not
    # speak for agent execution, which the execution catalog gates separately.
    allow_private_http: bool = False

    def validate(self) -> None:
        try:
            parsed = urlsplit(self.url)
            port = parsed.port
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
                or port == 0
                or any(ord(c) < 33 or ord(c) > 126 for c in self.url)
                or "\\" in self.url
                or "%" in self.url
            ):
                raise ValueError
            if parsed.scheme == "http" and not self.allow_http:
                raise ValueError
            if len(self.addresses) != 1 or not 1 <= self.timeout_seconds <= 30:
                raise ValueError
            literal = None
            try:
                literal = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                pass
            for address in self.addresses:
                ip = ipaddress.ip_address(address)
                if "%" in address or (ip.version == 6 and ip.ipv4_mapped):
                    raise ValueError
                if (
                    ip in METADATA
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_unspecified
                    or ip.is_reserved
                ):
                    raise ValueError
                if not ip.is_global and not self.allow_private:
                    raise ValueError
                # Cleartext is allowed to loopback unconditionally, to a private
                # address only when the operator opted in, and to a publicly
                # routable address never: the switch reaches the operator's own
                # network and no further. The unsafe address classes above and
                # the explicit-pin and no-DNS rules are unaffected either way.
                if (
                    parsed.scheme == "http"
                    and not ip.is_loopback
                    and not (self.allow_private_http and not ip.is_global)
                ):
                    raise ValueError
                if literal is not None and literal != ip:
                    raise ValueError
        except (ValueError, TypeError):
            raise ProviderError("endpoint_policy") from None


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, endpoint: Endpoint, address: str, ca_file: Path | None):
        parsed = urlsplit(endpoint.url)
        self.tls = parsed.scheme == "https"
        self.ca_file = ca_file
        self.address = address
        self.transport_socket: socket.socket | None = None
        self.expired = threading.Event()
        super().__init__(
            parsed.hostname or "",
            parsed.port or (443 if self.tls else 80),
            timeout=endpoint.timeout_seconds,
        )

    def connect(self) -> None:
        # Only numeric pinned IPs reach socket creation; Host and TLS SNI retain the hostname.
        raw = socket.create_connection((self.address, self.port), self.timeout)
        self.transport_socket = raw
        try:
            if self.expired.is_set():
                raise TimeoutError
            self.sock = (
                ssl.create_default_context(
                    cafile=str(self.ca_file) if self.ca_file else None
                ).wrap_socket(raw, server_hostname=self.host)
                if self.tls
                else raw
            )
            self.transport_socket = self.sock
            if self.expired.is_set():
                self.abort()
                raise TimeoutError
        except BaseException:
            raw.close()
            raise

    def abort(self) -> None:
        self.expired.set()
        connection_socket = self.transport_socket
        if connection_socket:
            try:
                connection_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection_socket.close()


class PinnedJSON:
    def __init__(self, endpoint: Endpoint, headers: dict[str, str], ca_file: Path | None = None):
        endpoint.validate()
        if any(
            k.lower() not in {"authorization", "accept", "x-github-api-version"}
            or "\r" in v
            or "\n" in v
            for k, v in headers.items()
        ):
            raise ProviderError("credential_format")
        self.endpoint, self.headers, self.ca_file = endpoint, headers, ca_file

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if (
            method not in {"GET", "POST"}
            or not path.startswith("/")
            or path.startswith("//")
            or "\r" in path
            or "\n" in path
        ):
            raise ProviderError("request_policy")
        payload = json.dumps(body).encode() if body is not None else None
        if payload and len(payload) > 131072:
            raise ProviderError("request_too_large")
        # No implicit retries/failover: POST replay must be a caller's deliberate decision.
        connection = PinnedConnection(self.endpoint, self.endpoint.addresses[0], self.ca_file)
        deadline = time.monotonic() + self.endpoint.timeout_seconds
        timer = threading.Timer(self.endpoint.timeout_seconds, connection.abort)
        timer.daemon = True
        timer.start()
        response: http.client.HTTPResponse | None = None
        try:
            connection.request(
                method,
                path,
                body=payload,
                headers={
                    **self.headers,
                    "Accept-Encoding": "identity",
                    "Content-Type": "application/json",
                    "User-Agent": "NachtLabs/0.2",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ProviderError("redirect_blocked")
            if response.status in {401, 403}:
                raise ProviderError("provider_permission")
            if response.status == 404:
                raise ProviderError("provider_not_found")
            if response.status == 429:
                raise ProviderError("provider_rate_limited", True)
            if response.status >= 500:
                raise ProviderError("provider_unavailable", True)
            if not 200 <= response.status < 300:
                raise ProviderError("provider_rejected")
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise ProviderError("response_encoding")
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderError("provider_timeout", True)
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise ProviderError("response_too_large")
            if connection.expired.is_set():
                raise ProviderError("provider_timeout", True)
            return json.loads(b"".join(chunks))
        except ProviderError:
            raise
        except TimeoutError:
            raise ProviderError("provider_timeout", True) from None
        except ssl.SSLError:
            raise ProviderError("provider_tls") from None
        except (OSError, http.client.HTTPException):
            raise ProviderError(
                "provider_timeout" if connection.expired.is_set() else "provider_transport", True
            ) from None
        except (ValueError, UnicodeError):
            raise ProviderError(
                "provider_timeout" if connection.expired.is_set() else "provider_format"
            ) from None
        finally:
            timer.cancel()
            if response:
                response.close()
            connection.close()
