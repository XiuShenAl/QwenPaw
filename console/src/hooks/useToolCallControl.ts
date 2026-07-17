import { useCallback, useEffect, useRef, useState } from "react";
import { toolCallsApi } from "../api/modules/toolCalls";
import { registerBackgroundTask } from "./useBackgroundTaskWatcher";
import { useBackgroundTasksStore } from "../stores/backgroundTasksStore";

const AUTO_POPUP_SECS = 30;
const OFFLOAD_POLL_MS = 2000;

export interface ToolCallControlState {
  bannerVisible: boolean;
  offloadRemaining: number | null;
  killRemaining: number | null;
  autoTriggered: boolean;
  isBackground: boolean;
  bgElapsed: number;
  defaultPolicy: "offload" | "keep_foreground";
}

function resolveSessionId(sessionId: string): string {
  return (
    sessionId ||
    ((window as unknown as { currentSessionId?: string })
      .currentSessionId as string) ||
    ""
  );
}

export function useToolCallControl(
  sessionId: string,
  toolCallId: string | undefined,
  status: string,
  toolName?: string,
) {
  const [state, setState] = useState<ToolCallControlState>({
    bannerVisible: false,
    offloadRemaining: null,
    killRemaining: null,
    autoTriggered: false,
    isBackground: false,
    bgElapsed: 0,
    defaultPolicy: "keep_foreground",
  });

  const timerRef = useRef<ReturnType<typeof setInterval>>();
  const serverOffloadRef = useRef<number | null>(null);
  const serverKillRef = useRef<number | null>(null);
  const serverTimestampRef = useRef<number>(0);
  const fetchedRef = useRef(false);
  const autoTriggeredRef = useRef(false);
  const autoOffloadRegisteredRef = useRef(false);
  const defaultPolicyRef = useRef<"offload" | "keep_foreground">(
    "keep_foreground",
  );
  const toolNameRef = useRef(toolName || toolCallId || "");
  toolNameRef.current = toolName || toolCallId || "";
  const prevCallingRef = useRef(false);
  const isCalling = status === "calling";

  const tryRegisterBackground = useCallback(
    (reason: string) => {
      if (autoOffloadRegisteredRef.current || !toolCallId) return false;
      if (
        useBackgroundTasksStore
          .getState()
          .tasks.some((t) => t.toolCallId === toolCallId)
      ) {
        autoOffloadRegisteredRef.current = true;
        return true;
      }
      autoOffloadRegisteredRef.current = true;
      void reason;
      registerBackgroundTask({
        sessionId: resolveSessionId(sessionId),
        toolCallId,
        toolName: toolNameRef.current || toolCallId,
      });
      setState((s) => ({
        ...s,
        isBackground: true,
        bannerVisible: false,
      }));
      return true;
    },
    [sessionId, toolCallId],
  );

  const registerIfAutoOffloaded = useCallback(() => {
    if (defaultPolicyRef.current !== "offload") return;
    tryRegisterBackground("local-countdown-zero");
  }, [tryRegisterBackground]);

  const startLocalCountdown = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = undefined;
    }
    if (serverOffloadRef.current === null || serverOffloadRef.current <= 0) {
      return;
    }

    timerRef.current = setInterval(() => {
      const elapsed = (performance.now() - serverTimestampRef.current) / 1000;
      const offR =
        serverOffloadRef.current !== null
          ? Math.max(0, serverOffloadRef.current - elapsed)
          : null;
      const killR =
        serverKillRef.current !== null
          ? Math.max(0, serverKillRef.current - elapsed)
          : null;

      setState((s) => {
        const shouldAutoPopup =
          offR !== null &&
          offR <= AUTO_POPUP_SECS &&
          offR > 0 &&
          !s.bannerVisible &&
          !autoTriggeredRef.current;

        if (shouldAutoPopup) {
          autoTriggeredRef.current = true;
        }

        return {
          ...s,
          offloadRemaining: offR,
          killRemaining: killR,
          bannerVisible: shouldAutoPopup ? true : s.bannerVisible,
          autoTriggered: shouldAutoPopup ? true : s.autoTriggered,
        };
      });

      if (offR !== null && offR <= 0) {
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = undefined;
        }
        registerIfAutoOffloaded();
        setState((s) => (s.bannerVisible ? { ...s, bannerVisible: false } : s));
      }
    }, 1000);
  }, [registerIfAutoOffloaded]);

  const applyServerValues = useCallback(
    (offload: number | null, kill: number | null) => {
      serverOffloadRef.current = offload;
      serverKillRef.current = kill;
      serverTimestampRef.current = performance.now();
      setState((s) => ({
        ...s,
        offloadRemaining: offload,
        killRemaining: kill,
      }));
      startLocalCountdown();
    },
    [startLocalCountdown],
  );

  // One-time fetch when tool starts executing (sessionId may still be empty).
  useEffect(() => {
    if (!isCalling || !toolCallId || fetchedRef.current) return;
    fetchedRef.current = true;
    autoOffloadRegisteredRef.current = false;

    const sid = resolveSessionId(sessionId);

    Promise.all([
      sid
        ? toolCallsApi.getInfo(sid, toolCallId).catch(() => null)
        : Promise.resolve(null),
      toolCallsApi.getOffloadPolicy().catch(() => null),
    ]).then(([info, policy]) => {
      const dp =
        (policy?.default_action as "offload" | "keep_foreground") ??
        "keep_foreground";
      defaultPolicyRef.current = dp;
      setState((s) => ({ ...s, defaultPolicy: dp }));

      if (info) {
        if (info.status === "offloaded") {
          tryRegisterBackground("initial-getInfo-offloaded");
        }
        applyServerValues(
          info.offload_remaining ?? null,
          info.kill_remaining ?? null,
        );
      }
    });
  }, [
    isCalling,
    sessionId,
    toolCallId,
    applyServerValues,
    tryRegisterBackground,
  ]);

  // Poll backend status while calling — catches system auto-offload even when
  // the tool card leaves "calling" before the local countdown hits zero.
  useEffect(() => {
    if (!isCalling || !toolCallId) return;

    let cancelled = false;
    const poll = async () => {
      if (cancelled || autoOffloadRegisteredRef.current) return;
      const sid = resolveSessionId(sessionId);
      if (!sid) return;
      try {
        const info = await toolCallsApi.getInfo(sid, toolCallId);
        if (cancelled) return;
        if (info.status === "offloaded") {
          tryRegisterBackground("poll-offloaded");
        }
      } catch {
        /* ignore transient errors */
      }
    };

    void poll();
    const id = setInterval(poll, OFFLOAD_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [isCalling, sessionId, toolCallId, tryRegisterBackground]);

  // When the card leaves "calling" (offloaded ToolResponse often flips status
  // immediately), register if the offload deadline was reached / backend says so.
  useEffect(() => {
    const wasCalling = prevCallingRef.current;
    prevCallingRef.current = isCalling;

    if (isCalling) return;

    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = undefined;
    }

    if (!wasCalling || !toolCallId || autoOffloadRegisteredRef.current) {
      fetchedRef.current = false;
      autoTriggeredRef.current = false;
      return;
    }

    const elapsed = (performance.now() - serverTimestampRef.current) / 1000;
    const offR =
      serverOffloadRef.current !== null
        ? Math.max(0, serverOffloadRef.current - elapsed)
        : null;

    // Deadline reached (or about to) under offload policy → treat as auto-offload.
    if (
      defaultPolicyRef.current === "offload" &&
      serverOffloadRef.current !== null &&
      offR !== null &&
      offR <= 2
    ) {
      tryRegisterBackground("leave-calling-deadline");
      fetchedRef.current = false;
      autoTriggeredRef.current = false;
      return;
    }

    const sid = resolveSessionId(sessionId);
    if (sid) {
      void toolCallsApi
        .getInfo(sid, toolCallId)
        .then((info) => {
          if (info.status === "offloaded") {
            tryRegisterBackground("leave-calling-getInfo");
          }
        })
        .catch(() => {
          /* entry may already be in completed cache as completed after fast bg finish */
        });
    }

    fetchedRef.current = false;
    autoTriggeredRef.current = false;
  }, [isCalling, sessionId, toolCallId, tryRegisterBackground]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const toggleBanner = useCallback(() => {
    setState((s) => ({ ...s, bannerVisible: !s.bannerVisible }));
  }, []);

  const closeBanner = useCallback(() => {
    setState((s) => ({ ...s, bannerVisible: false }));
  }, []);

  const updateRemaining = useCallback(
    (offload: number | null, kill: number | null) => {
      applyServerValues(offload, kill);
    },
    [applyServerValues],
  );

  const setBackground = useCallback((elapsed: number) => {
    setState((s) => ({
      ...s,
      isBackground: true,
      bgElapsed: elapsed,
      bannerVisible: false,
    }));
  }, []);

  return {
    ...state,
    toggleBanner,
    closeBanner,
    updateRemaining,
    setBackground,
  };
}
