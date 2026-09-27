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
