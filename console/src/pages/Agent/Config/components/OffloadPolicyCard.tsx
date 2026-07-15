import { useEffect, useState } from "react";
import { Card, Radio, Space, Typography, Alert, Spin } from "antd";
import { Clock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toolCallsApi } from "../../../../api/modules/toolCalls";
import styles from "../index.module.less";

const { Text, Paragraph } = Typography;

export type OffloadPolicy = "keep_foreground" | "offload";

export function OffloadPolicyCard() {
  const { t } = useTranslation();
  const [policy, setPolicy] = useState<OffloadPolicy>("keep_foreground");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    toolCallsApi
      .getOffloadPolicy()
      .then((res) => {
        setPolicy(
          (res.default_action as OffloadPolicy) || "keep_foreground",
        );
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleChange = async (value: OffloadPolicy) => {
    setSaving(true);
    try {
      await toolCallsApi.setOffloadPolicy(value);
      setPolicy(value);
    } catch {
      // Silently fail — user can retry
    } finally {
      setSaving(false);
    }
  };

  const options = [
    {
      value: "keep_foreground" as OffloadPolicy,
      label: t(
        "agentConfig.offloadPolicy.keepForeground",
        "保持前台执行",
      ),
      description: t(
        "agentConfig.offloadPolicy.keepForegroundDesc",
        "倒计时结束后工具继续在前台运行，不自动转入后台。适合需要实时查看输出的场景。",
      ),
      color: "#faad14",
    },
    {
      value: "offload" as OffloadPolicy,
      label: t(
        "agentConfig.offloadPolicy.offload",
        "自动转入后台",
      ),
      description: t(
        "agentConfig.offloadPolicy.offloadDesc",
        "倒计时结束后工具自动转入后台执行，Agent 可继续处理其他任务。适合长时间运行的工具。",
      ),
      color: "#1890ff",
    },
  ];

  return (
    <Card
      className={styles.formCard}
      title={
        <Space>
          <Clock size={18} />
          {t("agentConfig.offloadPolicy.title", "工具后台执行策略")}
        </Space>
      }
    >
      <Alert
        type="info"
        message={t(
          "agentConfig.offloadPolicy.alertMessage",
          "配置工具执行达到转入后台时限后的默认行为。用户可在工具执行时通过控制面板实时覆盖此设置。",
        )}
        style={{ marginBottom: 24 }}
        showIcon
      />

      {loading ? (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      ) : (
        <Radio.Group
          value={policy}
          onChange={(e) => handleChange(e.target.value as OffloadPolicy)}
          disabled={saving}
          style={{ width: "100%" }}
        >
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            {options.map((option) => (
              <Card
                key={option.value}
                className={styles.levelOptionCard}
                style={{
                  borderColor:
                    policy === option.value ? option.color : undefined,
                  borderWidth: policy === option.value ? 2 : 1,
                  cursor: "pointer",
                  transition: "all 0.3s",
                }}
                onClick={() => !saving && handleChange(option.value)}
                hoverable
              >
                <Radio value={option.value} style={{ width: "100%" }}>
                  <div style={{ marginLeft: 12 }}>
                    <Space align="start" size={12}>
                      <div style={{ color: option.color, marginTop: 2 }}>
                        <Clock size={18} />
                      </div>
                      <div style={{ flex: 1 }}>
                        <Text strong style={{ fontSize: 15 }}>
                          {option.label}
                        </Text>
                        <Paragraph
                          type="secondary"
                          style={{ margin: "4px 0 0 0", fontSize: 13 }}
                        >
                          {option.description}
                        </Paragraph>
                      </div>
                    </Space>
                  </div>
                </Radio>
              </Card>
            ))}
          </Space>
        </Radio.Group>
      )}
    </Card>
  );
}
