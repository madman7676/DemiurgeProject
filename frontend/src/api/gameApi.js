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

async function parseJsonResponse(response) {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

