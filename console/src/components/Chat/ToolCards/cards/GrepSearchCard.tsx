import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { SearchOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { countLines, stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";
import GrepSearchOutput from "./GrepSearchOutput";
import {
  hasOpenableGrepPaths,
  parseGrepResultLines,
} from "./grepSearchResult";

export interface GrepSearchCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const GrepSearchCard: React.FC<GrepSearchCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const pattern = (params.pattern || "") as string;
  const title = pattern
    ? t("tool.grepSearch", { pattern })
    : t("tool.grepSearchDefault");

  const resultText =
    content.status === "error" ? "" : stringifyResult(content.result);
  const lineCount = countLines(resultText);
  const parsedLines = useMemo(
    () => (resultText ? parseGrepResultLines(resultText) : []),
    [resultText],
  );
  const linkable = hasOpenableGrepPaths(parsedLines);

  if (content.status === "error") {
    return (
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={<SearchOutlined />}
        title={title}
      />
    );
  }

  const badge =
    content.status === "done" && lineCount > 0 ? (
      <span className={styles.lineSearchBadge}>
        {t("tool.lineBadge.matches", { count: lineCount })}
      </span>
    ) : null;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<SearchOutlined />}
      title={title}
      badges={badge}
    >
      {resultText &&
        (linkable ? (
          <GrepSearchOutput content={resultText} lines={parsedLines} />
        ) : (
          <DefaultBlock title="Output" content={resultText} />
        ))}
    </ToolCardShell>
  );
};

export default GrepSearchCard;
