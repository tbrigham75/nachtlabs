import { describe, expect, it } from "vitest";
import {
  endpointProblems,
  type EndpointInput,
} from "../src/features/llm-setup";

/*
  The client's mirror of the server's Endpoint.validate().

  These are the rules the API cannot report, because it suppresses pydantic's
  reason on purpose and a whole-object rule can only name the path "body". An
  operator used to be told only "Check the indicated fields" for a plain-HTTP
  LAN endpoint, which is the single most likely thing to get wrong.
*/

const ok = (over: Partial<EndpointInput> = {}): EndpointInput => ({
  baseUrl: "https://192.168.1.50",
  pin: "192.168.1.50",
  allowPrivate: true,
  allowHttp: false,
  ...over,
});

describe("endpointProblems", () => {
  it("accepts the shape that the API accepts: LAN address over https", () => {
    // Verified against the running API: this returns 201.
    expect(endpointProblems(ok())).toEqual([]);
  });

  it("accepts a loopback endpoint over plain http", () => {
    expect(
      endpointProblems(
        ok({
          baseUrl: "http://127.0.0.1:11434",
          pin: "127.0.0.1",
          allowHttp: true,
        }),
      ),
    ).toEqual([]);
  });

  it("accepts a hostname in the origin with a different pin", () => {
    // The pin is the routing target and the hostname is only for the Host
    // header and TLS, so the two need not be textually equal.
    expect(
      endpointProblems(
        ok({ baseUrl: "https://ollama.lan", pin: "192.168.1.50" }),
      ),
    ).toEqual([]);
  });

  it("explains that plain http only works for loopback", () => {
    // The exact case that produced "Check the indicated fields".
    const problems = endpointProblems(
      ok({ baseUrl: "http://192.168.1.50:11434", allowHttp: true }),
    );
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/Plain HTTP is only accepted for a loopback/);
    expect(problems[0]).toContain("https://");
    expect(problems[0]).toContain("192.168.1.50");
  });

  it("does not raise the http complaint when allow-http is already off", () => {
    // Same address, https: nothing to say about http.
    expect(endpointProblems(ok({ allowHttp: false }))).toEqual([]);
  });

  it("accepts an https endpoint with the http permission left on", () => {
    // The permission only matters when the scheme is http, so an https origin
    // carrying the flag is still fine. This is the shape the wizard offers by
    // default, and rejecting it would block a configuration the API accepts.
    expect(endpointProblems(ok({ allowHttp: true }))).toEqual([]);
  });

  it("asks for the http permission when the scheme needs it", () => {
    const problems = endpointProblems(
      ok({
        baseUrl: "http://127.0.0.1:11434",
        pin: "127.0.0.1",
        allowHttp: false,
      }),
    );
    expect(problems.some((p) => /Permit HTTP for this loopback/.test(p))).toBe(
      true,
    );
  });

  it("asks for the private permission when it is missing", () => {
    const problems = endpointProblems(ok({ allowPrivate: false }));
    expect(
      problems.some((p) => /Permit this private or loopback/.test(p)),
    ).toBe(true);
  });

  it("also needs the private permission for a loopback address", () => {
    // 127.0.0.0/8 is not globally routable, so the server requires the
    // permission there too. The wizard's loopback defaults turn it on for
    // exactly this reason; an earlier version of this file assumed otherwise
    // and was wrong.
    const problems = endpointProblems(
      ok({
        baseUrl: "http://127.0.0.1:11434",
        pin: "127.0.0.1",
        allowHttp: true,
        allowPrivate: false,
      }),
    );
    expect(
      problems.some((p) => /Permit this private or loopback/.test(p)),
    ).toBe(true);
  });

  it("flags a pin that disagrees with an IP in the origin", () => {
    const problems = endpointProblems(
      ok({ baseUrl: "https://192.168.1.99", pin: "192.168.1.50" }),
    );
    expect(problems.some((p) => /must be the same address/.test(p))).toBe(true);
  });

  it("rejects a cloud metadata address outright", () => {
    for (const address of [
      "169.254.169.254",
      "169.254.170.2",
      "100.100.100.200",
      "168.63.129.16",
    ]) {
      const problems = endpointProblems(
        ok({ baseUrl: `https://${address}`, pin: address }),
      );
      expect(problems.join(" "), address).toMatch(/metadata|never permitted/);
    }
  });

  it("rejects a pin that is not a single numeric address", () => {
    for (const pin of [
      "ollama.lan",
      "192.168.1",
      "192.168.1.5.5",
      "192.168.1.256",
      "",
    ]) {
      const problems = endpointProblems(
        ok({ pin, baseUrl: "https://192.168.1.50" }),
      );
      expect(problems.length, pin).toBeGreaterThan(0);
    }
  });

  it("rejects an origin carrying a path, query, fragment or credentials", () => {
    expect(
      endpointProblems(ok({ baseUrl: "https://host/console" }))[0],
    ).toMatch(/path/);
    expect(endpointProblems(ok({ baseUrl: "https://host?a=1" }))[0]).toMatch(
      /query/,
    );
    expect(endpointProblems(ok({ baseUrl: "https://host#x" }))[0]).toMatch(
      /query or fragment/,
    );
    expect(endpointProblems(ok({ baseUrl: "https://u:p@host" }))[0]).toMatch(
      /credentials/,
    );
  });

  it("rejects an origin that is not http or https", () => {
    expect(endpointProblems(ok({ baseUrl: "ftp://192.168.1.50" }))[0]).toMatch(
      /http:\/\/ or https:\/\//,
    );
    expect(endpointProblems(ok({ baseUrl: "192.168.1.50" }))[0]).toMatch(
      /http:\/\/ or https:\/\//,
    );
  });

  it("tolerates a single trailing slash on the origin", () => {
    expect(endpointProblems(ok({ baseUrl: "https://192.168.1.50/" }))).toEqual(
      [],
    );
  });

  it("classifies IPv6 loopback as loopback", () => {
    expect(
      endpointProblems(
        ok({ baseUrl: "http://[::1]:11434", pin: "::1", allowHttp: true }),
      ),
    ).toEqual([]);
  });

  it("treats an unclassifiable address as not loopback, which is the safe side", () => {
    // A zone-scoped or odd address cannot be classified here, so it must not be
    // waved through as if it were loopback.
    const problems = endpointProblems(
      ok({
        baseUrl: "https://[fe80::1%eth0]",
        pin: "fe80::1%eth0",
        allowHttp: true,
      }),
    );
    expect(problems.length).toBeGreaterThan(0);
  });

  it("reports the non-routable v4 ranges the server treats as non-global", () => {
    for (const pin of [
      "10.1.2.3",
      "172.16.0.9",
      "192.168.0.9",
      "169.254.1.1",
      "100.64.0.1",
    ]) {
      expect(
        endpointProblems(
          ok({ baseUrl: `https://${pin}`, pin, allowPrivate: false }),
        ).some((p) => /Permit this private or loopback/.test(p)),
        pin,
      ).toBe(true);
    }
  });

  it("does not treat a public address as needing the private permission", () => {
    expect(
      endpointProblems(
        ok({
          baseUrl: "https://93.184.216.34",
          pin: "93.184.216.34",
          allowPrivate: false,
        }),
      ),
    ).toEqual([]);
  });

  it("says more than the first problem when several apply", () => {
    const problems = endpointProblems(
      ok({
        baseUrl: "http://10.0.0.9:11434",
        pin: "10.0.0.9",
        allowPrivate: false,
        allowHttp: true,
      }),
    );
    expect(problems.length).toBeGreaterThan(1);
  });
});
