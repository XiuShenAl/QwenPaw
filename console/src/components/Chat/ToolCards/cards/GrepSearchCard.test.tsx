// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { pattern?: string; count?: number }) => {
      if (opts?.pattern) return `${key}:${opts.pattern}`;
      if (opts?.count !== undefined) return `${key}:${opts.count}`;
      return key;
    },
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    children,
    title,
  }: {
    children?: React.ReactNode;
    title?: string;
  }) => (
    <div>
      <div>{title}</div>
      {children}
    </div>
  ),
  DefaultBlock: ({ content }: { content: string }) => (
    <pre data-testid="default-block">{content}</pre>
  ),
}));

vi.mock("../shared/utils", async () => {
  const actual =
    await vi.importActual<typeof import("../shared/utils")>("../shared/utils");
  return {
    ...actual,
  };
});

vi.mock("@/utils/clipboard", () => ({
  copyText: vi.fn().mockResolvedValue(undefined),
}));

import GrepSearchCard from "./GrepSearchCard";

describe("GrepSearchCard", () => {
  it("renders clickable paths that open the editor at the match line", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-1",
          name: "grep_search",
          status: "done",
          params: { pattern: "def main", show_file: true },
          result: "src/main.py:12:> def main():\nsrc/util.py:3:> def main_helper():",
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "src/main.py" }));

    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail.target).toEqual({
      source: "workspace",
      path: "src/main.py",
      root: "project",
      line: 12,
      endLine: 12,
    });
    expect(event.detail.workspace).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "src/util.py" }));
    expect(listener).toHaveBeenCalledTimes(2);
    const second = listener.mock.calls[1][0] as CustomEvent;
    expect(second.detail.target).toMatchObject({
      path: "src/util.py",
      line: 3,
    });

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("falls back to DefaultBlock when there are no openable paths", () => {
    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-2",
          name: "grep_search",
          status: "done",
          params: { pattern: "zzz" },
          result: "No matches found for pattern: zzz",
        }}
      />,
    );

    expect(screen.getByTestId("default-block")).toHaveTextContent(
      "No matches found for pattern: zzz",
    );
    expect(
      screen.queryByRole("button", { name: /src\// }),
    ).not.toBeInTheDocument();
  });
});
