import { describe, expect, it } from "vitest";

import type { LoopModeInfo } from "../stores/loopStore";
import {
  firstLoopDescriptionMarkdown,
  resolveLoopModeDescriptionMarkdown,
} from "./loopModeDescription";

const t = (key: string) => {
  if (key === "loop.modes.goal.description") {
    return "设定目标并持续推进直到完成。";
  }
  return key;
};

describe("firstLoopDescriptionMarkdown", () => {
  it("returns empty for missing input", () => {
    expect(firstLoopDescriptionMarkdown()).toBe("");
    expect(firstLoopDescriptionMarkdown("")).toBe("");
  });

  it("keeps the first non-empty line including Markdown markers", () => {
    expect(
      firstLoopDescriptionMarkdown(
        "**UltraQA** — automated QA cycle engine\n\n" +
          "Usage:\n" +
          "  `/ultraqa [--tests|--build]`\n",
      ),
    ).toBe("**UltraQA** — automated QA cycle engine");
  });

  it("skips blank lines before the summary", () => {
    expect(
      firstLoopDescriptionMarkdown(
        "\n\n**Team** — multi-agent collaboration\n\nUsage",
      ),
    ).toBe("**Team** — multi-agent collaboration");
  });
});

describe("resolveLoopModeDescriptionMarkdown", () => {
  it("uses i18n for builtin modes", () => {
    const goal: Pick<LoopModeInfo, "id" | "source" | "description"> = {
      id: "goal",
      source: "builtin",
      description: "Set a goal and work until it is done.",
    };
    expect(resolveLoopModeDescriptionMarkdown(goal, t)).toBe(
      "设定目标并持续推进直到完成。",
    );
  });

  it("keeps Markdown on plugin/custom API descriptions", () => {
    const omp: Pick<LoopModeInfo, "id" | "source" | "description"> = {
      id: "plugin:ultrawork",
      source: "plugin",
      description:
        "**Ultrawork** — parallel task execution engine\n\n" +
        "Usage: `/ultrawork <task description>`",
    };
    expect(resolveLoopModeDescriptionMarkdown(omp, t)).toBe(
      "**Ultrawork** — parallel task execution engine",
    );
  });
});
