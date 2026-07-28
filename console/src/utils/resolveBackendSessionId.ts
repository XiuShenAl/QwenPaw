import sessionApi from "../pages/Chat/sessionApi";

/**
 * Resolve a backend-compatible session_id for tool-call APIs.
 *
 * Prefer an explicit id (e.g. from Chat hydration), then window.currentSessionId,
 * then the last intentional chat selection. Always map through sessionApi so
 * local-timestamp library ids become the coordinator's session_id.
 */
export function resolveBackendSessionId(preferred?: string | null): string {
  const raw =
    (preferred && preferred.trim()) ||
    ((window as unknown as { currentSessionId?: string }).currentSessionId ??
      "") ||
    sessionApi.lastActiveChatId ||
    "";
  if (!raw) return "";
  return sessionApi.getBackendSessionId(raw);
}
