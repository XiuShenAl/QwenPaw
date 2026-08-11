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
    summaryAction,
    defaultExpanded,
  }: {
    children?: React.ReactNode;
    title?: string;
    summaryAction?: React.ReactNode;
    defaultExpanded?: boolean;
  }) => (
    <div data-expanded={String(Boolean(defaultExpanded))}>
      <div>{title}</div>
      {summaryAction}
      {children}
    </div>
  ),
  DefaultBlock: ({ content }: { content: string }) => (
    <pre data-testid="default-block">{content}</pre>
  ),
}));

vi.mock("../shared/utils", async () => {
  const actual = await vi.importActual<typeof import("../shared/utils")>(
    "../shared/utils",
  );
  return {
    ...actual,
  };
});

import GrepSearchCard from "./GrepSearchCard";

const multiFileResult = [
  "src/main.py:12:> def main():",
  "src/main.py:13:  pass",
  "src/util.py:3:> def main_helper():",
].join("\n");

describe("GrepSearchCard", () => {
  it("keeps raw Output visible and hides the clickable list until preview is opened", () => {
    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-1",
          name: "grep_search",
          status: "done",
          params: { pattern: "def main", show_file: true },
          result: multiFileResult,
        }}
      />,
    );

    expect(screen.getByTestId("default-block")).toHaveTextContent(
      "src/main.py:12:> def main():",
    );
    expect(
      screen.queryByRole("button", { name: "src/main.py" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "files.preview" }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("toggles an isolated clickable result panel from the preview action", () => {
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
          result: multiFileResult,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "files.preview" }));
    expect(
      screen.getByRole("button", { name: "files.preview" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("default-block")).toBeInTheDocument();

    const mainRow = screen.getByRole("button", { name: "src/main.py" });
    expect(mainRow).toHaveTextContent("main.py");
    fireEvent.click(mainRow);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(
      (listener.mock.calls[0][0] as CustomEvent).detail.target,
    ).toMatchObject({
      path: "src/main.py",
      line: 12,
      root: "project",
    });
    expect((listener.mock.calls[0][0] as CustomEvent).detail.workspace).toBe(
      true,
    );

    fireEvent.click(screen.getByRole("button", { name: "files.preview" }));
    expect(
      screen.queryByRole("button", { name: "src/main.py" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("default-block")).toBeInTheDocument();

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("expands a file group so each match line can open a different target", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-multi",
          name: "grep_search",
          status: "done",
          params: { pattern: "def main" },
          result: [
            "src/main.py:12:> def main():",
            "src/main.py:40:> def main_helper():",
          ].join("\n"),
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "files.preview" }));
    expect(
      screen.getByRole("button", { name: "src/main.py" }),
    ).toHaveTextContent("2");

    fireEvent.click(screen.getByRole("button", { name: "Expand src/main.py" }));
    fireEvent.click(screen.getByRole("button", { name: "src/main.py:40" }));
    expect(
      (listener.mock.calls[0][0] as CustomEvent).detail.target,
    ).toMatchObject({
      path: "src/main.py",
      line: 40,
    });

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("does not show preview when there are no openable paths", () => {
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
      screen.queryByRole("button", { name: "files.preview" }),
    ).not.toBeInTheDocument();
  });
});
