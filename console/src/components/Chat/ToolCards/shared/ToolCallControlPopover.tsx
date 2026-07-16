/**
 * OffloadBanner — renders below the tool card as a horizontal panel.
 *
 * Shows a circular countdown ring, action buttons, and a note about
 * the default offload policy.
 */

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { message } from "antd";
import { toolCallsApi } from "../../../../api/modules/toolCalls";
import styles from "./offloadBanner.module.less";

const CIRCUMFERENCE = 2 * Math.PI * 10;

interface OffloadBannerProps {
  sessionId: string;
  toolCallId: string;
  offloadRemaining: number | null;
  killRemaining: number | null;
  totalSeconds: number;
  defaultPolicy: "offload" | "keep_foreground";
  onClose: () => void;
  onUpdateRemaining: (offload: number | null, kill: number | null) => void;
}

export const OffloadBanner: React.FC<OffloadBannerProps> = ({
  sessionId,
  toolCallId,
  offloadRemaining,
  totalSeconds,
  defaultPolicy,
  onClose,
  onUpdateRemaining,
}) => {
  const { t } = useTranslation();
  const [collapsing, setCollapsing] = useState(false);
  const [displaySecs, setDisplaySecs] = useState(
    offloadRemaining !== null ? Math.ceil(offloadRemaining) : 0,
  );
  const startTimeRef = useRef(performance.now());
  const startSecsRef = useRef(displaySecs);
  const timerRef = useRef<ReturnType<typeof setInterval>>();
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (offloadRemaining === null || offloadRemaining <= 0) return;
    startTimeRef.current = performance.now();
    startSecsRef.current = Math.ceil(offloadRemaining);
    setDisplaySecs(startSecsRef.current);

    timerRef.current = setInterval(() => {
      const elapsed = (performance.now() - startTimeRef.current) / 1000;
      const remaining = Math.max(0, startSecsRef.current - elapsed);
      setDisplaySecs(Math.ceil(remaining));
      if (remaining <= 0) {
        clearInterval(timerRef.current);
        dismiss(true);
      }
    }, 1000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offloadRemaining]);

  const dismiss = (showToast = false) => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (showToast) {
      const label =
        defaultPolicy === "offload"
          ? t("tool.control.policyOffload")
          : t("tool.control.policyKeep");
      message.info(label);
    }
    setCollapsing(true);
    setTimeout(() => onClose(), 250);
  };

  const withGuard = async (action: string, fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(action);
    try {
      await fn();
    } catch (e) {
      console.error(`[OffloadBanner] ${action} failed:`, e);
    } finally {
      setBusy(null);
    }
  };

  const handleBackground = () =>
    withGuard("offload", async () => {
      await toolCallsApi.offload(sessionId, toolCallId);
      dismiss();
    });

  const handleKeep = () =>
    withGuard("keep", async () => {
      const res = await toolCallsApi.preventOffload(sessionId, toolCallId);
      onUpdateRemaining(res.offload_remaining, res.kill_remaining);
      dismiss();
    });

  const handleExtendOffload = () =>
    withGuard("extendOffload", async () => {
      const res = await toolCallsApi.extendOffload(sessionId, toolCallId, 30);
      onUpdateRemaining(res.offload_remaining, res.kill_remaining);
    });

  const handleExtendKill = () =>
    withGuard("extendKill", async () => {
      const res = await toolCallsApi.extendKill(sessionId, toolCallId, 30);
      onUpdateRemaining(res.offload_remaining, res.kill_remaining);
    });

  const handleCancel = () =>
    withGuard("cancel", async () => {
      await toolCallsApi.cancel(sessionId, toolCallId);
      dismiss();
    });

  const hasCountdown = offloadRemaining !== null && offloadRemaining > 0;
  const total = hasCountdown ? totalSeconds : 1;
  const pct = hasCountdown ? displaySecs / total : 0;
  const offset = CIRCUMFERENCE * (1 - pct);
  const isUrgent = displaySecs <= 5;
  const defaultLabel =
    defaultPolicy === "offload"
      ? t("tool.control.policyOffload")
      : t("tool.control.policyKeep");

  return (
    <div
      className={`${styles.offloadBanner} ${
        collapsing ? styles.collapsing : ""
      }`}
    >
      <div className={styles.offloadBar}>
        <div className={styles.offloadGear}>⚙️</div>
        <div className={styles.offloadInfo}>{t("tool.control.title")}</div>

        {hasCountdown && (
          <div className={styles.timerRing}>
            <svg viewBox="0 0 26 26" width="26" height="26">
              <circle className={styles.ringBg} cx="13" cy="13" r="10" />
              <circle
                className={`${styles.ringProgress} ${
                  isUrgent ? styles.urgent : ""
                }`}
                cx="13"
                cy="13"
                r="10"
                style={{
                  strokeDasharray: CIRCUMFERENCE,
                  strokeDashoffset: offset,
                }}
              />
            </svg>
            <div
              className={`${styles.timerCount} ${
                isUrgent ? styles.urgent : ""
              }`}
            >
              {displaySecs}
            </div>
          </div>
        )}
      </div>

      <div className={styles.offloadActions}>
        <button
          className={styles.offloadBtn}
          onClick={handleBackground}
          disabled={busy !== null}
        >
          <span className={styles.ico}>🌙</span> {t("tool.control.offload")}
        </button>
        <button
          className={styles.offloadBtn}
          onClick={handleKeep}
          disabled={busy !== null}
        >
          <span className={styles.ico}>⏳</span> {t("tool.control.keep")}
        </button>
        <button
          className={styles.offloadBtn}
          onClick={handleExtendOffload}
          disabled={busy !== null}
        >
          <span className={styles.ico}>🔄</span>{" "}
          {t("tool.control.extendOffload")}
        </button>
        <button
          className={styles.offloadBtn}
          onClick={handleExtendKill}
          disabled={busy !== null}
        >
          <span className={styles.ico}>⏱️</span> {t("tool.control.extendKill")}
        </button>
        <button
          className={`${styles.offloadBtn} ${styles.cancelAct}`}
          onClick={handleCancel}
          disabled={busy !== null}
        >
          <span className={styles.ico}>✕</span> {t("tool.control.cancel")}
        </button>
      </div>

      <div className={styles.offloadNote}>
        <div className={styles.noteDot} />
        {hasCountdown ? (
          <>{t("tool.control.autoAction", { seconds: displaySecs })}</>
        ) : (
          <>{t("tool.control.noCountdown")}</>
        )}
        <strong
          style={{
            color: "var(--ant-color-text, inherit)",
            marginLeft: 2,
          }}
        >
          {defaultLabel}
        </strong>
      </div>
    </div>
  );
};
