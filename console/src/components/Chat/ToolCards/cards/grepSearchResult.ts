import { parseInternalFileLink } from "../../../../features/files-workspace/internalFileLinks";
import type { FileTarget } from "../../../../features/files-workspace/types";

/** `path:line:> content` / `path:line:  content` (show_file=True). */
const MATCH_WITH_PATH_RE = /^(.*?):(\d+):([> ]) (.*)$/;
/** `line:> content` (show_file=False, after a file header). */
const MATCH_NO_PATH_RE = /^(\d+):([> ]) (.*)$/;

export type GrepResultLine =
  | {
      kind: "match";
      path: string;
      line: number;
      hit: boolean;
      content: string;
      raw: string;
    }
  | {
      kind: "match_no_path";
      path: string | null;
      line: number;
      hit: boolean;
      content: string;
      raw: string;
    }
  | { kind: "file_header"; path: string; raw: string }
  | { kind: "separator"; raw: string }
  | { kind: "text"; raw: string };

function normalizeDisplayPath(rawPath: string): string {
  return rawPath.trim().replace(/\\/g, "/").replace(/^(?:\.\/)+/, "");
}

/** Paths the workspace preview API can open (project-relative, no `..`). */
export function toOpenableFileTarget(
  rawPath: string,
  line?: number,
): FileTarget | null {
  const path = normalizeDisplayPath(rawPath);
  if (!path) return null;
  const parsed = parseInternalFileLink(path);
  if (!parsed) return null;
  return {
    ...parsed,
    root: "project",
    line,
    endLine: line,
  };
}

function looksLikeFileHeader(line: string): boolean {
  if (!line || line === "---") return false;
  if (MATCH_WITH_PATH_RE.test(line) || MATCH_NO_PATH_RE.test(line)) {
    return false;
  }
  if (line.startsWith("(") || line.startsWith("No matches")) return false;
  if (/\s/.test(line)) return false;
  return toOpenableFileTarget(line) !== null;
}

export function parseGrepResultLines(text: string): GrepResultLine[] {
  if (!text) return [];

  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const parsed: GrepResultLine[] = [];
  let currentPath: string | null = null;

  for (const raw of lines) {
    if (raw === "---") {
      parsed.push({ kind: "separator", raw });
      continue;
    }

    const withPath = MATCH_WITH_PATH_RE.exec(raw);
    if (withPath) {
      const path = normalizeDisplayPath(withPath[1]);
      const line = Number(withPath[2]);
      if (path && Number.isFinite(line) && toOpenableFileTarget(path, line)) {
        currentPath = path;
        parsed.push({
          kind: "match",
          path,
          line,
          hit: withPath[3] === ">",
          content: withPath[4],
          raw,
        });
        continue;
      }
    }

    const noPath = MATCH_NO_PATH_RE.exec(raw);
    if (noPath) {
      const line = Number(noPath[1]);
      if (Number.isFinite(line)) {
        parsed.push({
          kind: "match_no_path",
          path: currentPath,
          line,
          hit: noPath[2] === ">",
          content: noPath[3],
          raw,
        });
        continue;
      }
    }

    if (looksLikeFileHeader(raw)) {
      currentPath = normalizeDisplayPath(raw);
      parsed.push({ kind: "file_header", path: currentPath, raw });
      continue;
    }

    parsed.push({ kind: "text", raw });
  }

  return parsed;
}

export function hasOpenableGrepPaths(lines: GrepResultLine[]): boolean {
  return lines.some(
    (line) =>
      line.kind === "match" ||
      line.kind === "file_header" ||
      (line.kind === "match_no_path" && line.path !== null),
  );
}

export function dispatchOpenFilePreview(
  target: FileTarget,
  trigger: HTMLElement | null,
  options?: { workspace?: boolean },
): void {
  window.dispatchEvent(
    new CustomEvent("qwenpaw:open-file-preview", {
      detail: {
        target,
        trigger,
        // Prefer the coding workspace editor so line navigation / highlight works.
        workspace: options?.workspace ?? false,
      },
    }),
  );
}
