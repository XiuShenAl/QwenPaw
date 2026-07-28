import type { LoopModeInfo } from "../stores/loopStore";

/**
 * First non-empty line of loop/plugin help text, Markdown markers preserved.
 *
 * OMP CommandSpec.help_text is a multi-line Markdown doc; menus only need the
 * summary line, which is then rendered with restricted inline Markdown.
 */
export function firstLoopDescriptionMarkdown(description?: string): string {
  if (!description) return "";
  return (
    description
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => line.length > 0) ?? ""
  );
}

/** Builtin modes use i18n; plugin/custom use API text — keep Markdown. */
export function resolveLoopModeDescriptionMarkdown(
  mode: Pick<LoopModeInfo, "id" | "source" | "description">,
  t: (key: string) => string,
): string {
  const raw =
    mode.source === "builtin"
      ? t(`loop.modes.${mode.id}.description`)
      : mode.description;
  return firstLoopDescriptionMarkdown(raw);
}
