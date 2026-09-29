import { describe, expect, it } from "vitest";
import {
  derivePin,
  isCleartextOffHost,
} from "../src/features/endpoint-address";

/*
  Two screens depend on this classification: the wizard's permanent notice and
  the Integrations badge. If they could reach different conclusions about one
  address, an operator would be shown a reassuring badge over an endpoint the
  wizard calls exposed, so the shared helper is pinned directly rather than only
  through the one caller that happened to need it.
*/
describe("isCleartextOffHost", () => {
  it("is false for any endpoint over https", () => {
    // The only arrangement where the question does not arise.
    expect(isCleartextOffHost("https://192.168.2.171", ["192.168.2.171"])).toBe(
      false,
    );
    expect(isCleartextOffHost("https://ollama.lan", ["192.168.2.171"])).toBe(
      false,
    );
  });

  it("is false for cleartext to loopback", () => {
    expect(isCleartextOffHost("http://127.0.0.1:11434", ["127.0.0.1"])).toBe(
      false,
    );
    expect(isCleartextOffHost("http://127.0.0.1:11434", ["127.0.0.5"])).toBe(
      false,
    );
    expect(isCleartextOffHost("http://[::1]:11434", ["::1"])).toBe(false);
  });

  it("is true for cleartext to a private address", () => {
    expect(
      isCleartextOffHost("http://192.168.2.171:11434", ["192.168.2.171"]),
    ).toBe(true);
    expect(isCleartextOffHost("http://10.0.0.5", ["10.0.0.5"])).toBe(true);
    expect(isCleartextOffHost("http://172.16.4.9:11434", ["172.16.4.9"])).toBe(
      true,
    );
  });

  it("is true for cleartext to a public address", () => {
    // Public cleartext is refused by the server outright, so an endpoint like
    // this cannot be saved. It is described as exposed rather than safe, which
    // is the same answer and the harmless one.
    expect(isCleartextOffHost("http://93.184.216.34", ["93.184.216.34"])).toBe(
      true,
    );
  });

  it("treats a hostname with a private pin as off-host", () => {
    // The pin is the routing target, so the pin decides, not the name.
    expect(
      isCleartextOffHost("http://ollama.lan:11434", ["192.168.2.171"]),
    ).toBe(true);
    expect(isCleartextOffHost("http://ollama.local:11434", ["127.0.0.1"])).toBe(
      false,
    );
  });

  it("treats an address it cannot read as exposed, not as safe", () => {
    // A scoped or malformed pin is the restrictive side of the same coin. Getting
    // this backwards would label an endpoint safe because the parser gave up.
    expect(
      isCleartextOffHost("http://ollama.lan:11434", ["fe80::1%eth0"]),
    ).toBe(true);
    expect(
      isCleartextOffHost("http://ollama.lan:11434", ["not-an-address"]),
    ).toBe(true);
    // An empty pin list is not asserted either way: the server requires at least
    // one pin, so no saved connection can reach this, and picking an answer for
    // it would be a rule about an input that does not exist rather than about an
    // endpoint an operator can actually configure.
  });

  it("reads the scheme case-insensitively", () => {
    expect(
      isCleartextOffHost("HTTP://192.168.2.171:11434", ["192.168.2.171"]),
    ).toBe(true);
  });

  describe("derivePin", () => {
    it("returns the address when the origin is written as a number", () => {
      // The common case, and the one the duplication used to get in the way of:
      // the server refuses a pin that differs from a numeric origin, so the only
      // possible answer is the origin's own address.
      expect(derivePin("http://192.168.2.171:11434")).toBe("192.168.2.171");
      expect(derivePin("https://10.1.2.3")).toBe("10.1.2.3");
      expect(derivePin("http://127.0.0.1:11434")).toBe("127.0.0.1");
    });

    it("returns null when the origin is a name, which is the case the pin is for", () => {
      // A name and an address do different jobs here: the certificate and the
      // Host header use the name, the socket uses the address. Only the operator
      // can say what the name means, so the interface must not guess.
      expect(derivePin("https://ollama.lan")).toBeNull();
      expect(derivePin("https://api.github.com")).toBeNull();
    });

    it("reads the IPv6 literal without its brackets or port", () => {
      // A URL considers the bracketed form to be the host, so the brackets and
      // the port both have to come off or the result is not a bare address.
      expect(derivePin("http://[::1]:11434")).toBe("::1");
    });

    it("returns null for an origin it cannot read", () => {
      // Null rather than an empty string, so the caller leaves the field alone
      // instead of clearing what the operator typed on every keystroke. The
      // half-typed states are the ones that matter here.
      expect(derivePin("")).toBeNull();
      expect(derivePin("   ")).toBeNull();
      expect(derivePin("http://")).toBeNull();
      expect(derivePin("ollama")).toBeNull();
      expect(derivePin("not a url at all")).toBeNull();
    });

    it("keeps a saved pin reachable for an origin that is a name", () => {
      // The Integrations screen edits an existing connection, including one
      // configured against a hostname. derivePin must answer null for that origin
      // so the screen leaves the stored pin alone instead of overwriting it with
      // nothing, which is the one behaviour that would silently break a working
      // name-based endpoint.
      expect(derivePin("https://ollama.lan")).toBeNull();
      expect(derivePin("https://gitea.internal:3000")).toBeNull();
    });

    it("agrees with the address the server would require", () => {
      // The client-side rule must not be looser than the server's. A numeric
      // origin and its pin are required to be the same address on the way in
      // (transport.py), so deriving one from the other can only ever produce
      // what the server would have accepted.
      const cases = [
        "http://192.168.2.171:11434",
        "https://10.1.2.3:443",
        "http://127.0.0.1:11434",
      ];
      for (const origin of cases) {
        const pin = derivePin(origin);
        expect(pin).not.toBeNull();
        expect(new URL(origin).hostname).toBe(pin);
      }
    });
  });
});
