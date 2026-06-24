import { API_BASE } from "./api";

export interface FeatureOption {
  id: string;
  label: string;
  description?: string | null;
  votes: number;
}

export interface FeedbackBoard {
  round: string;
  options: FeatureOption[];
  my_vote: string | null;
  total_votes: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/** Options sorted by votes (desc) for the current round, plus my current pick. */
export function getFeedbackBoard(userId?: string | null): Promise<FeedbackBoard> {
  const q = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return req<FeedbackBoard>(`/feedback/board${q}`);
}

/** Cast / change my single vote for this release. */
export function voteFeature(optionId: string, userId: string): Promise<FeedbackBoard> {
  return req<FeedbackBoard>(`/feedback/vote`, {
    method: "POST",
    body: JSON.stringify({ option_id: optionId, user_id: userId }),
  });
}

/** Free-text "¿Qué echas de menos en Edgecute?". */
export function sendSuggestion(text: string, userId?: string | null): Promise<{ ok: boolean }> {
  return req<{ ok: boolean }>(`/feedback/suggestion`, {
    method: "POST",
    body: JSON.stringify({ text, user_id: userId ?? null }),
  });
}
