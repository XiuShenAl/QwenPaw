import { describe, expect, it } from "vitest";

import type { LoopModeInfo } from "../../stores/loopStore";
import { buildLoopSlashSuggestions } from "./loopSlashSuggestions";

const t = (key: string) => {
  if (key === "loop.modes.goal.description") {
    return "设定目标并持续推进直到完成。";
  }
  return key;
};

describe("buildLoopSlashSuggestions", () => {
  const modes: LoopModeInfo[] = [
    {
      id: "default",
      name: "default",
      slash_command: "",
      description: "default",
      source: "builtin",
    },
    {
      id: "goal",
      name: "goal",
      slash_command: "goal",
      description: "Set a goal and work until it is done.",
      source: "builtin",
    },
    {
      id: "plugin:ultrawork",
      name: "ultrawork",
      slash_command: "ultrawork",
      description: "**Ultrawork** — parallel\n\nUsage: `/ultrawork`",
      source: "plugin",
    },
    {
      id: "mission",
      name: "mission",
      slash_command: "clear",
      description: "should be reserved",
      source: "builtin",
    },
  ];

  it("skips empty/reserved commands and keeps first-line Markdown", () => {
    expect(buildLoopSlashSuggestions(modes, new Set(["clear"]), t)).toEqual([
      {
        command: "/goal",
        value: "goal",
        description: "设定目标并持续推进直到完成。",
      },
      {
        command: "/ultrawork",
        value: "ultrawork",
        description: "**Ultrawork** — parallel",
      },
    ]);
  });
});
