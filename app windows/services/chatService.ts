import { ChatAttachment, ChatMessage } from "../types";
import { apiGet, apiPost, apiPostForm, getApiBase } from "./apiClient";

export const getChatHistory = async (): Promise<ChatMessage[]> => {
  const data = await apiGet("/api/chat/history?limit=100", true);
  return data.map((item: any) => ({
    id: String(item.id),
    sender: String(item.sender || "").toLowerCase() === "user" ? "user" : "bot",
    text: item.text,
    contentType: String(item.content_type || "text") as ChatMessage["contentType"],
    attachments: Array.isArray(item.attachments) ? item.attachments : [],
    timestamp: new Date(item.timestamp_ms),
  }));
};

export const addChatMessage = async (message: ChatMessage): Promise<void> => {
  await apiPost(
    "/api/chat/history",
    {
      sender: message.sender,
      text: message.text,
      content_type: message.contentType || "text",
      attachments: Array.isArray(message.attachments) ? message.attachments : [],
      timestamp_ms: message.timestamp.getTime(),
    },
    true
  );
};

export const uploadChatAttachment = async (file: File): Promise<ChatAttachment> => {
  const form = new FormData();
  form.append("file", file);
  const data = await apiPostForm("/api/chat/upload", form, true);
  const raw = data?.attachment || {};
  const relUrl = String(raw.url || "").trim();
  const absoluteUrl =
    relUrl.startsWith("http://") || relUrl.startsWith("https://") ? relUrl : `${getApiBase()}${relUrl}`;
  return {
    kind: raw.kind === "video" ? "video" : "image",
    url: absoluteUrl,
    mime: String(raw.mime || file.type || ""),
    name: String(raw.name || file.name || ""),
    size: Number(raw.size || file.size || 0),
  };
};
