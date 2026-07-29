import { Alert, Button, Card, Space } from "antd";
import { Clock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import styles from "../index.module.less";

/** Agent Config no longer owns this global setting — link to Settings. */
export function OffloadPolicyRedirectCard() {
  const { t } = useTranslation();

  return (
    <Card
      className={styles.formCard}
      title={
        <Space>
          <Clock size={18} />
          {t("agentConfig.offloadPolicy.title", "Tool Background Execution")}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        message={t(
          "agentConfig.offloadPolicy.movedMessage",
          "Tool offload policy is a global setting. Manage it under Settings → Tool Offload.",
        )}
        action={
          <Link to="/offload-policy">
            <Button type="primary" size="small">
              {t("agentConfig.offloadPolicy.openSettings", "Open in Settings")}
            </Button>
          </Link>
        }
      />
    </Card>
  );
}
