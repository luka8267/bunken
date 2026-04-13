type SessionResponse = {
  userId: string;
  email: string;
  username: string;
};

const API_BASE_URL =
  (globalThis as typeof globalThis & { BUNKEN_API_BASE_URL?: string }).BUNKEN_API_BASE_URL ??
  "http://127.0.0.1:8765";

export async function getSession(): Promise<SessionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/addin/auth/session`, {
    method: "POST",
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error("session check failed");
  }

  return (await response.json()) as SessionResponse;
}
