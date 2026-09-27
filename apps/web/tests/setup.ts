import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);

// jsdom implements neither of these, and the shell uses both: matchMedia to
// follow the operating system colour scheme, and scrollTo for the anchor
// behaviour of in-page links. Stubbed once here so any component test that
// renders the shell works without each one repeating the shim.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
if (!window.scrollTo) {
  window.scrollTo = () => {};
}
