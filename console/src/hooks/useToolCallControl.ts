import { useCallback, useEffect, useRef, useState } from "react";
import { toolCallsApi } from "../api/modules/toolCalls";

const AUTO_POPUP_SECS = 30;

export interface ToolCallControlState {
  bannerVisible: boolean;
  offloadRemaining: number | null;
  killRemaining: number | null;
  autoTriggered: boolean;
  isBackground: boolean;
  bgElapsed: number;
  defaultPolicy: "offload" | "keep_foreground";
}

export function useToolCallControl(
  sessionId: string,
  toolCallId: string | undefined,
  status: string,
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
  const isCalling = status === "calling";

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
      }
    }, 1000);
  }, []);

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

  // One-time fetch when tool starts executing
  useEffect(() => {
    if (!isCalling || !toolCallId || !sessionId || fetchedRef.current) return;
    fetchedRef.current = true;

    Promise.all([
      toolCallsApi.getInfo(sessionId, toolCallId).catch(() => null),
      toolCallsApi.getOffloadPolicy().catch(() => null),
    ]).then(([info, policy]) => {
      const dp =
        (policy?.default_action as "offload" | "keep_foreground") ??
        "keep_foreground";
      setState((s) => ({ ...s, defaultPolicy: dp }));

      if (info) {
        applyServerValues(
          info.offload_remaining ?? null,
          info.kill_remaining ?? null,
        );
      }
    });
  }, [isCalling, sessionId, toolCallId, applyServerValues]);

  // Stop countdown when tool finishes
  useEffect(() => {
    if (!isCalling) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = undefined;
      }
      fetchedRef.current = false;
      autoTriggeredRef.current = false;
    }
  }, [isCalling]);

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
