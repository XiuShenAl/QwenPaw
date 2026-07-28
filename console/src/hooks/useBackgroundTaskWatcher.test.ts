import { beforeEach, describe, expect, it, vi } from "vitest";

const cancelApi = vi.fn();
const messageError = vi.fn();

vi.mock("../api/modules/toolCalls", () => ({
  toolCallsApi: {
    cancel: (...args: unknown[]) => cancelApi(...args),
    getOutput: vi.fn(),
  },
  subscribeToolCallStream: () => () => {},
  extractOutputText: () => "",
}));

vi.mock("antd", () => ({
  message: {
    error: (...args: unknown[]) => messageError(...args),
    info: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock("../i18n", () => ({
  default: { t: (_k: string, fallback: string) => fallback },
}));

vi.mock("../utils/resolveBackendSessionId", () => ({
  resolveBackendSessionId: (preferred?: string | null) => preferred || "",
}));

import { useBackgroundTasksStore } from "../stores/backgroundTasksStore";
import {
  cancelBackgroundTask,
  stopBackgroundWatchersNotInSession,
} from "./useBackgroundTaskWatcher";

describe("useBackgroundTaskWatcher session isolation", () => {
  beforeEach(() => {
    cancelApi.mockReset();
    messageError.mockReset();
    useBackgroundTasksStore.setState({ tasks: [] });
  });

  it("removes empty-session tasks when switching to another session", () => {
    const store = useBackgroundTasksStore.getState();
    store.addTask({
      toolCallId: "tc-a",
      toolName: "a",
      sessionId: "sid-a",
      startTime: 1,
    });
    store.addTask({
      toolCallId: "tc-empty",
      toolName: "e",
      sessionId: "",
      startTime: 2,
    });
    store.addTask({
      toolCallId: "tc-b",
      toolName: "b",
      sessionId: "sid-b",
      startTime: 3,
    });

    stopBackgroundWatchersNotInSession("sid-b");

    const left = useBackgroundTasksStore
      .getState()
      .tasks.map((t) => t.toolCallId)
      .sort();
    expect(left).toEqual(["tc-b"]);
  });

  it("refuses cancel when sessionId is empty", async () => {
    await expect(cancelBackgroundTask("", "tc-1")).rejects.toThrow(
      /Missing backend session id/,
    );
    expect(cancelApi).not.toHaveBeenCalled();
    expect(messageError).toHaveBeenCalled();
  });
});
