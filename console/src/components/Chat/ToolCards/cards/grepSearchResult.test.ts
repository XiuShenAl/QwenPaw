import { describe, expect, it } from "vitest";
import {
  displayPartsForGrepPath,
  groupGrepFileHits,
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

describe("groupGrepFileHits", () => {
  it("collapses matches to one row per file with first hit line", () => {
    const lines = parseGrepResultLines(
      [
        "src/main.py:12:> def main():",
        "src/main.py:13:  pass",
        "src/util.py:3:> def main_helper():",
      ].join("\n"),
    );
    expect(groupGrepFileHits(lines)).toEqual([
      {
        path: "src/main.py",
        line: 12,
        hitCount: 1,
        matches: [{ line: 12, content: "def main():" }],
      },
      {
        path: "src/util.py",
        line: 3,
        hitCount: 1,
        matches: [{ line: 3, content: "def main_helper():" }],
      },
    ]);
  });

  it("keeps multiple hit lines under the same file for expand", () => {
    const lines = parseGrepResultLines(
      [
        "src/main.py:12:> def main():",
        "src/main.py:40:> def main_helper():",
      ].join("\n"),
    );
    expect(groupGrepFileHits(lines)).toEqual([
      {
        path: "src/main.py",
        line: 12,
        hitCount: 2,
        matches: [
          { line: 12, content: "def main():" },
          { line: 40, content: "def main_helper():" },
        ],
      },
    ]);
  });

  it("groups show_file=False headers and match lines", () => {
    const lines = parseGrepResultLines(
      ["pkg/a.txt", "1:> match_a", "2:> match_a2", "---", "pkg/b.txt", "1:> match_b"].join(
        "\n",
      ),
    );
    expect(groupGrepFileHits(lines)).toEqual([
      {
        path: "pkg/a.txt",
        line: 1,
        hitCount: 2,
        matches: [
          { line: 1, content: "match_a" },
          { line: 2, content: "match_a2" },
        ],
      },
      {
        path: "pkg/b.txt",
        line: 1,
        hitCount: 1,
        matches: [{ line: 1, content: "match_b" }],
      },
    ]);
  });
});

describe("displayPartsForGrepPath", () => {
  it("splits basename and directory", () => {
    expect(displayPartsForGrepPath("hello_omp/hello_omp/__main__.py")).toEqual({
      name: "__main__.py",
      directory: "hello_omp/hello_omp",
    });
    expect(displayPartsForGrepPath("readme.md")).toEqual({
      name: "readme.md",
      directory: "",
    });
  });
});
