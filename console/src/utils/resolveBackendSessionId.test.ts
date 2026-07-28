import { beforeEach, describe, expect, it, vi } from "vitest";

const getBackendSessionId = vi.fn((id: string) => `mapped:${id}`);

vi.mock("../pages/Chat/sessionApi", () => ({
  default: {
    lastActiveChatId: "last-active",
    getBackendSessionId: (id: string) => getBackendSessionId(id),
  },
}));

import { resolveBackendSessionId } from "./resolveBackendSessionId";

describe("resolveBackendSessionId", () => {
  beforeEach(() => {
    getBackendSessionId.mockClear();
    delete (window as unknown as { currentSessionId?: string })
      .currentSessionId;
  });

  it("maps an explicit preferred id through sessionApi", () => {
    expect(resolveBackendSessionId("local-123")).toBe("mapped:local-123");
    expect(getBackendSessionId).toHaveBeenCalledWith("local-123");
  });

  it("falls back to window.currentSessionId then lastActiveChatId", () => {
    (window as unknown as { currentSessionId?: string }).currentSessionId =
      "win-sid";
    expect(resolveBackendSessionId("")).toBe("mapped:win-sid");

    delete (window as unknown as { currentSessionId?: string })
      .currentSessionId;
    expect(resolveBackendSessionId(null)).toBe("mapped:last-active");
  });
});
