import React, { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckOutlined, CopyOutlined } from "@ant-design/icons";
import { copyText } from "@/utils/clipboard";
import styles from "../shared/toolCards.module.less";
import {
  dispatchOpenFilePreview,
  toOpenableFileTarget,
  type GrepResultLine,
} from "./grepSearchResult";

export interface GrepSearchOutputProps {
  content: string;
  lines: GrepResultLine[];
}

function openPath(
  path: string,
  line: number | undefined,
  trigger: HTMLElement,
): void {
  const target = toOpenableFileTarget(path, line);
  if (!target) return;
  dispatchOpenFilePreview(target, trigger, { workspace: true });
}

const GrepResultRow: React.FC<{ entry: GrepResultLine }> = ({ entry }) => {
  if (entry.kind === "separator") {
    return <div className={styles.grepResultSeparator}>---</div>;
  }

  if (entry.kind === "text") {
    return <div className={styles.grepResultPlain}>{entry.raw || "\u00a0"}</div>;
  }

  if (entry.kind === "file_header") {
    return (
      <div className={styles.grepResultRow}>
        <button
          type="button"
          className={styles.grepResultPath}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            openPath(entry.path, undefined, event.currentTarget);
          }}
        >
          {entry.path}
        </button>
      </div>
    );
  }

  if (entry.kind === "match") {
    return (
      <div
        className={
          entry.hit ? styles.grepResultRowHit : styles.grepResultRowContext
        }
      >
        <button
          type="button"
          className={styles.grepResultPath}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            openPath(entry.path, entry.line, event.currentTarget);
          }}
        >
          {entry.path}
        </button>
        <span className={styles.grepResultMeta}>
          :{entry.line}:{entry.hit ? ">" : " "}{" "}
        </span>
        <span className={styles.grepResultContent}>{entry.content}</span>
      </div>
    );
  }

  // match_no_path
  const path = entry.path;
  return (
    <div
      className={
        entry.hit ? styles.grepResultRowHit : styles.grepResultRowContext
      }
    >
      {path ? (
        <button
          type="button"
          className={styles.grepResultLineRef}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            openPath(path, entry.line, event.currentTarget);
          }}
          title={`${path}:${entry.line}`}
        >
          {entry.line}
        </button>
      ) : (
        <span className={styles.grepResultMeta}>{entry.line}</span>
      )}
      <span className={styles.grepResultMeta}>
        :{entry.hit ? ">" : " "}{" "}
      </span>
      <span className={styles.grepResultContent}>{entry.content}</span>
    </div>
  );
};

const GrepSearchOutput: React.FC<GrepSearchOutputProps> = ({
  content,
  lines,
}) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = useCallback(() => {
    void copyText(content)
      .then(() => {
        if (timerRef.current) clearTimeout(timerRef.current);
        setCopied(true);
        timerRef.current = setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {});
  }, [content]);

  return (
    <div className={styles.defaultBlock}>
      <div className={styles.defaultBlockHeader}>
        <span className={styles.defaultBlockTitle}>Output</span>
        <button
          type="button"
          className={styles.defaultBlockCopy}
          onClick={handleCopy}
          title={t("tool.copy", { defaultValue: "Copy" })}
        >
          {copied ? <CheckOutlined /> : <CopyOutlined />}
        </button>
      </div>
      <div className={styles.grepResultBody}>
        {lines.map((entry, index) => (
          <GrepResultRow key={`${index}:${entry.raw}`} entry={entry} />
        ))}
      </div>
    </div>
  );
};

export default React.memo(GrepSearchOutput);
