import React from "react";
import { Button, Popover, Space, Tag } from "antd";
import {
  CloudUploadOutlined,
  StopOutlined,
  ClockCircleOutlined,
  FieldTimeOutlined,
  CloseCircleOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { toolCallsApi } from "../../../../api/modules/toolCalls";

interface Props {
  sessionId: string;
  toolCallId: string;
  offloadRemaining: number | null;
  killRemaining: number | null;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  onUpdateRemaining: (
    offload: number | null,
    kill: number | null,
  ) => void;
}

function formatTime(secs: number | null): string {
  if (secs === null) return "\u221E";
  return `${Math.ceil(secs)}s`;
}

export const ToolCallControlPopover: React.FC<Props> = ({
  sessionId,
  toolCallId,
  offloadRemaining,
  killRemaining,
  open,
  onToggle,
  onClose,
  onUpdateRemaining,
}) => {
  const handleOffload = async () => {
    await toolCallsApi.offload(sessionId, toolCallId);
    onClose();
  };

  const handlePrevent = async () => {
    const res = await toolCallsApi.preventOffload(sessionId, toolCallId);
    onUpdateRemaining(res.offload_remaining, res.kill_remaining);
    onClose();
  };

  const handleExtendOffload = async () => {
    const res = await toolCallsApi.extendOffload(sessionId, toolCallId, 30);
    onUpdateRemaining(res.offload_remaining, res.kill_remaining);
  };

  const handleExtendKill = async () => {
    const res = await toolCallsApi.extendKill(sessionId, toolCallId, 30);
    onUpdateRemaining(res.offload_remaining, res.kill_remaining);
  };

  const handleCancel = async () => {
    await toolCallsApi.cancel(sessionId, toolCallId);
    onClose();
  };

  const content = (
    <Space direction="vertical" size="small" style={{ width: 240 }}>
      {offloadRemaining !== null && (
        <Tag color={offloadRemaining <= 10 ? "red" : "blue"}>
          Offload in: {formatTime(offloadRemaining)}
        </Tag>
      )}
      {killRemaining !== null && (
        <Tag>Timeout: {formatTime(killRemaining)}</Tag>
      )}
      <Button
        block
        size="small"
        icon={<CloudUploadOutlined />}
        onClick={handleOffload}
      >
        Move to background
      </Button>
      <Button
        block
        size="small"
        icon={<StopOutlined />}
        onClick={handlePrevent}
      >
        Prevent offload
      </Button>
      <Button
        block
        size="small"
        icon={<ClockCircleOutlined />}
        onClick={handleExtendOffload}
      >
        Extend offload (+30s)
      </Button>
      <Button
        block
        size="small"
        icon={<FieldTimeOutlined />}
        onClick={handleExtendKill}
      >
        Extend timeout (+30s)
      </Button>
      <Button
        block
        size="small"
        danger
        icon={<CloseCircleOutlined />}
        onClick={handleCancel}
      >
        Cancel execution
      </Button>
    </Space>
  );

  return (
    <Popover
      content={content}
      title="Tool call control"
      trigger="click"
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <SettingOutlined
        style={{ cursor: "pointer", marginLeft: 8, fontSize: 12 }}
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
      />
    </Popover>
  );
};
