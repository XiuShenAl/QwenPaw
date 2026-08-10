import { describe, expect, it } from "vitest";
import {
  hasOpenableGrepPaths,
  parseGrepResultLines,
  toOpenableFileTarget,
} from "./grepSearchResult";

describe("toOpenableFileTarget", () => {
  it("accepts relative project paths with a line", () => {
    expect(toOpenableFileTarget("src/main.py", 12)).toEqual({
      source: "workspace",
      path: "src/main.py",
      root: "project",
      line: 12,
      endLine: 12,
    });
  });

  it("rejects absolute and parent paths", () => {
    expect(toOpenableFileTarget("/tmp/main.py", 1)).toBeNull();
    expect(toOpenableFileTarget("../secret.py", 1)).toBeNull();
  });
});

describe("parseGrepResultLines", () => {
  it("parses show_file=True match lines", () => {
    const lines = parseGrepResultLines(
      "src/main.py:12:> def main():\nsrc/main.py:13:  pass",
    );
    expect(lines).toEqual([
      {
        kind: "match",
        path: "src/main.py",
        line: 12,
        hit: true,
        content: "def main():",
        raw: "src/main.py:12:> def main():",
      },
      {
        kind: "match",
        path: "src/main.py",
        line: 13,
        hit: false,
        content: "pass",
        raw: "src/main.py:13:  pass",
      },
    ]);
    expect(hasOpenableGrepPaths(lines)).toBe(true);
  });

  it("parses show_file=False grouped results", () => {
    const lines = parseGrepResultLines(
      ["a.txt", "1:> match_a", "---", "b.txt", "1:> match_b"].join("\n"),
    );
    expect(lines).toEqual([
      { kind: "file_header", path: "a.txt", raw: "a.txt" },
      {
        kind: "match_no_path",
        path: "a.txt",
        line: 1,
        hit: true,
        content: "match_a",
        raw: "1:> match_a",
      },
      { kind: "separator", raw: "---" },
      { kind: "file_header", path: "b.txt", raw: "b.txt" },
      {
        kind: "match_no_path",
        path: "b.txt",
        line: 1,
        hit: true,
        content: "match_b",
        raw: "1:> match_b",
      },
    ]);
  });

  it("keeps status footers as plain text", () => {
    const lines = parseGrepResultLines(
      "src/app.py:1:> hi\n\n(Results truncated due to size.)",
    );
    expect(lines[0]).toMatchObject({ kind: "match", path: "src/app.py" });
    expect(lines[1]).toEqual({ kind: "text", raw: "" });
    expect(lines[2]).toEqual({
      kind: "text",
      raw: "(Results truncated due to size.)",
    });
  });

  it("does not treat empty results as linkable", () => {
    const lines = parseGrepResultLines("No matches found for pattern: foo");
    expect(hasOpenableGrepPaths(lines)).toBe(false);
  });
});
