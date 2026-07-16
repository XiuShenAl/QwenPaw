export function useToolCallSessionId(): string {
  return (
    ((window as unknown as Record<string, unknown>)
      .currentSessionId as string) || ""
  );
}
