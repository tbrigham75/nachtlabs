/*
  Address classification for the endpoint rules, shared so that the setup wizard
  and the Integrations screen cannot reach different conclusions about the same
  address. The server is authoritative; this only has to agree with it, and
  anything it cannot classify is treated as the restrictive case.
*/

/** Address classes the server refuses for the pin, whatever the permissions.
 * Kept in step with METADATA in integrations/transport.py. */
export const NEVER_PERMITTED = new Set([
  "169.254.169.254",
  "169.254.170.2",
  "100.100.100.200",
  "168.63.129.16",
]);

type Parsed = { text: string; version: 4 | 6; parts: number[] };

export function parseIp(value: string): Parsed | null {
  const text = value.trim();
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(text);
  if (v4) {
    const parts = v4.slice(1, 5).map(Number);
    return parts.every((n) => n >= 0 && n <= 255)
      ? { text, version: 4, parts }
      : null;
  }
  // A deliberately conservative IPv6 shape check. The server is authoritative;
  // this only has to recognise enough to classify the address, and anything it
  // cannot classify is treated as not-loopback, which is the restrictive side.
  if (
    text.includes("%") ||
    !text.includes(":") ||
    !/^[0-9a-fA-F:]+$/.test(text)
  ) {
    return null;
  }
  return { text, version: 6, parts: [] };
}

export function isLoopbackIp(ip: Parsed): boolean {
  if (ip.version === 4) return ip.parts[0] === 127;
  return ip.text === "::1" || ip.text === "0:0:0:0:0:0:0:1";
}

/**
 * Whether the address counts as publicly routable, which is the server's test
 * for whether the private permission is needed at all.
 *
 * The server asks ipaddress.is_global, so loopback needs the permission too,
 * even though it is the operator's own machine: the wizard's loopback defaults
 * turn it on for exactly that reason. Anything not recognised here is treated as
 * non-global, which is the restrictive side of the same coin.
 */
export function isGlobalIp(ip: Parsed): boolean {
  if (ip.version === 6) return false;
  const [a, b] = ip.parts;
  if (a === 0 || a >= 224) return false; // unspecified, reserved, multicast
  if (a === 127) return false; // loopback
  if (a === 10) return false; // private
  if (a === 172 && b >= 16 && b <= 31) return false; // private
  if (a === 192 && b === 168) return false; // private
  if (a === 169 && b === 254) return false; // link local
  if (a === 100 && b >= 64 && b <= 127) return false; // carrier grade NAT
  return true;
}

/**
 * Whether an endpoint is cleartext to somewhere that is not this machine.
 *
 * This is the condition the wizard warns about permanently, so the badge and the
 * notice are driven by one function: a screen that disagreed with the other
 * about whether an endpoint is exposed is worse than no badge at all. An address
 * the parser does not recognise counts as not-loopback, so a shape this cannot
 * read is described as exposed rather than quietly described as safe.
 */
export function isCleartextOffHost(baseUrl: string, pins: string[]): boolean {
  if (!baseUrl.trim().toLowerCase().startsWith("http://")) return false;
  return pins.some((pin) => {
    const parsed = parseIp(pin);
    return parsed === null || !isLoopbackIp(parsed);
  });
}

/**
 * What the pinned address should be, given the origin being typed.
 *
 * The server already refuses a pin that disagrees with an origin written as a
 * number (`transport.py`), so in that case the answer is the origin's own
 * address and asking the operator to type it a second time could only ever
 * produce a copy or a refusal. Deriving it here removes the second typing
 * without relaxing anything: the mismatch rule stays in place, so a bug here
 * would be caught rather than quietly accepted.
 *
 * An origin written as a *name* is the case the pin is really for, because the
 * two do different jobs there. The socket connects to the pinned address while
 * the certificate and the Host header use the name. So a name yields null, and
 * the operator supplies the address it means right now.
 *
 * Null is also returned for an origin this cannot read, which includes the
 * half-typed state while the operator is still editing. Returning null there
 * rather than an empty string matters: the caller leaves the field alone
 * instead of clearing what the operator already entered on every keystroke.
 */
export function derivePin(baseUrl: string): string | null {
  const raw = baseUrl.trim();
  if (!raw) return null;
  // Take what a URL considers the host, so a port is not mistaken for part of
  // the address and an IPv6 literal arrives without its brackets.
  let host: string;
  try {
    host = new URL(raw).hostname;
  } catch {
    return null;
  }
  if (!host) return null;
  // A URL keeps the brackets around an IPv6 literal, and the pin is a bare
  // address, so they have to come off. Leaving them on would produce a value
  // parseIp rejects and the server refuses, which is worse than not deriving:
  // the field would be filled with something the form then calls invalid.
  const bare =
    host.startsWith("[") && host.endsWith("]") ? host.slice(1, -1) : host;
  return parseIp(bare) === null ? null : bare;
}

/**
 * The hostname an origin names, for use in a label or message.
 *
 * Null unless the origin actually parses and the host is a name, so a caller
 * cannot show a half-typed fragment or a bare address in a sentence that is
 * about a name. Used to phrase the pin field for the case where the operator
 * really is pinning.
 */
export function originName(baseUrl: string): string | null {
  const raw = baseUrl.trim();
  if (!raw) return null;
  let host: string;
  try {
    host = new URL(raw).hostname;
  } catch {
    return null;
  }
  if (!host) return null;
  const bare =
    host.startsWith("[") && host.endsWith("]") ? host.slice(1, -1) : host;
  return parseIp(bare) === null ? bare : null;
}
