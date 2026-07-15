import { createContext, useContext } from "react";

const ToolCallSessionContext = createContext<string>("");

export const ToolCallSessionProvider = ToolCallSessionContext.Provider;

export function useToolCallSessionId(): string {
  const fromContext = useContext(ToolCallSessionContext);
  if (fromContext) return fromContext;
  return (
    (window as unknown as Record<string, unknown>).currentSessionId as string
  ) || "";
}
