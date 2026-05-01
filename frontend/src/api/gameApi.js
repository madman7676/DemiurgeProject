export async function fetchSession() {
  const response = await fetch("/api/session");
  return parseJsonResponse(response);
}

export async function sendPlayerMessage(message) {
  const response = await fetch("/api/message", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });
  return parseJsonResponse(response);
}

export async function sendPlayerMessageStream(
  message,
  { onNarrationDelta, onStatus } = {},
) {
  const response = await fetch("/api/message/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });

  if (!response.ok || !response.body) {
    return parseJsonResponse(response);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalData = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      const event = JSON.parse(line);
      if (event.type === "status") {
        onStatus?.(event.step || "");
      } else if (event.type === "narration_delta") {
        onNarrationDelta?.(event.text || "");
      } else if (event.type === "text") {
        onNarrationDelta?.(event.content || "");
      } else if (event.type === "final") {
        finalData = event.data;
      } else if (event.type === "error") {
        throw new Error(event.error || "Streaming request failed.");
      }
    }
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    if (event.type === "status") {
      onStatus?.(event.step || "");
    } else if (event.type === "narration_delta") {
      onNarrationDelta?.(event.text || "");
    } else if (event.type === "text") {
      onNarrationDelta?.(event.content || "");
    } else if (event.type === "final") {
      finalData = event.data;
    } else if (event.type === "error") {
      throw new Error(event.error || "Streaming request failed.");
    }
  }

  if (!finalData) {
    throw new Error("Streaming response ended before final state arrived.");
  }
  return finalData;
}

async function parseJsonResponse(response) {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}
