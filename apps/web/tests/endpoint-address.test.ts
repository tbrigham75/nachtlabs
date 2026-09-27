import { describe, expect, it } from "vitest";
import { isCleartextOffHost } from "../src/features/endpoint-address";

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
});
