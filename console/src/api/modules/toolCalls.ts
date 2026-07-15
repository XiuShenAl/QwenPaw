import { request } from "../request";

export interface ToolCallInfo {
  tool_call_id: string;
  tool_name: string;
  status: string;
  elapsed: number;
  offload_remaining: number | null;
  kill_remaining: number | null;
}

export interface ExtendResult {
  status: string;
  tool_call_id: string;
  offload_remaining: number | null;
  kill_remaining: number | null;
}

const BASE = "/tool-calls";

export const toolCallsApi = {
  getInfo: (sid: string, tcid: string) =>
    request<ToolCallInfo>(`${BASE}/${sid}/${tcid}`),

  offload: (sid: string, tcid: string) =>
    request(`${BASE}/${sid}/${tcid}/offload`, { method: "POST" }),

  cancel: (sid: string, tcid: string) =>
    request(`${BASE}/${sid}/${tcid}/cancel`, { method: "POST" }),

  preventOffload: (sid: string, tcid: string) =>
    request<ExtendResult>(`${BASE}/${sid}/${tcid}/extend-deadline`, {
      method: "POST",
      body: JSON.stringify({ target: "offload", no_deadline: true }),
    }),

  extendOffload: (sid: string, tcid: string, seconds = 30) =>
    request<ExtendResult>(`${BASE}/${sid}/${tcid}/extend-deadline`, {
      method: "POST",
      body: JSON.stringify({ target: "offload", seconds }),
    }),

  extendKill: (sid: string, tcid: string, seconds = 30) =>
    request<ExtendResult>(`${BASE}/${sid}/${tcid}/extend-deadline`, {
      method: "POST",
      body: JSON.stringify({ target: "kill", seconds }),
    }),

  getOffloadPolicy: () =>
    request<{ default_action: string }>("/settings/offload-policy"),

  setOffloadPolicy: (action: "keep_foreground" | "offload") =>
    request("/settings/offload-policy", {
      method: "PUT",
      body: JSON.stringify({ default_action: action }),
    }),
};
