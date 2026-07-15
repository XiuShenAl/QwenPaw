import { useCallback, useEffect, useRef, useState } from "react";
import { toolCallsApi } from "../api/modules/toolCalls";

const AUTO_POPUP_THRESHOLD = 30;

interface ToolCallControlState {
  offloadRemaining: number | null;
  killRemaining: number | null;
  showPopup: boolean;
  autoTriggered: boolean;
}

export function useToolCallControl(
  sessionId: string,
  toolCallId: string | undefined,
  status: string,
) {
  const [state, setState] = useState<ToolCallControlState>({
    offloadRemaining: null,
    killRemaining: null,
    showPopup: false,
    autoTriggered: false,
  });
  const timerRef = useRef<ReturnType<typeof setInterval>>();
  const fetchedRef = useRef(false);
  const startTimeRef = useRef<number>(0);
  const startRemainingRef = useRef<number>(0);

  useEffect(() => {
    if (status !== "calling" || !toolCallId || fetchedRef.current) return;
    fetchedRef.current = true;

    toolCallsApi.getInfo(sessionId, toolCallId).then((info) => {
      setState((s) => ({
        ...s,
        offloadRemaining: info.offload_remaining,
        killRemaining: info.kill_remaining,
      }));
    });

    return () => {
      fetchedRef.current = false;
    };
  }, [sessionId, toolCallId, status]);

  useEffect(() => {
    if (state.offloadRemaining === null || state.offloadRemaining <= 0) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = undefined;
      }
      return;
    }

    startTimeRef.current = performance.now();
    startRemainingRef.current = state.offloadRemaining;

    timerRef.current = setInterval(() => {
      const elapsed = (performance.now() - startTimeRef.current) / 1000;
      const remaining = Math.max(
        0,
        startRemainingRef.current - elapsed,
      );

      setState((s) => {
        const shouldAutoPopup =
          remaining <= AUTO_POPUP_THRESHOLD &&
          remaining > 0 &&
          !s.showPopup &&
          !s.autoTriggered;

        return {
          ...s,
          offloadRemaining: remaining,
          showPopup: shouldAutoPopup ? true : s.showPopup,
          autoTriggered: shouldAutoPopup ? true : s.autoTriggered,
        };
      });

      if (remaining <= 0 && timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = undefined;
        setState((s) => ({ ...s, showPopup: false }));
      }
    }, 1000);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = undefined;
      }
    };
    // Re-run when offloadRemaining is externally updated (e.g. extend response)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.offloadRemaining === null ? "null" : "has-value"]);

  const togglePopup = useCallback(() => {
    setState((s) => ({ ...s, showPopup: !s.showPopup }));
  }, []);

  const closePopup = useCallback(() => {
    setState((s) => ({ ...s, showPopup: false }));
  }, []);

  const updateRemaining = useCallback(
    (offload: number | null, kill: number | null) => {
      setState((s) => ({
        ...s,
        offloadRemaining: offload,
        killRemaining: kill,
      }));
    },
    [],
  );

  return { ...state, togglePopup, closePopup, updateRemaining };
}
