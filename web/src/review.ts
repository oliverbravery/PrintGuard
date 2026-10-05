import type { ReviewSummary } from "./types";

export const LIMIT_REASON = "This runs on a free service with a fixed amount of room, so there's a daily limit.";

const DAILY_LIMITS: Record<string, string> = {
  hub_daily: "You've sent as many frames as one PrintGuard can in a day.",
  network_daily: "Your network has sent as many frames as it can today.",
  global_daily: "PrintGuard has had all the frames it can take today.",
};

export function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function isDailyLimit(code: string | null): boolean {
  return code !== null && code in DAILY_LIMITS;
}

export function waitingMessage(review: ReviewSummary): string {
  const after = review.retry_at ? ` after ${clock(review.retry_at)}` : "";
  if (review.code && review.code in DAILY_LIMITS) return `${DAILY_LIMITS[review.code]} The rest are saved and will send${after}.`;
  if (review.code === "storage_full") return "The inbox for training frames is full. Yours are saved and will send when there's room.";
  if (review.code === "closed") return "PrintGuard isn't collecting frames at the moment. Yours are saved.";
  return "Couldn't reach the feedback server. Your frames are saved, so you can try again.";
}

export function sending(review: ReviewSummary): boolean {
  return review.status === "queued" && review.code === null;
}

export function statusText(review: ReviewSummary): string {
  if (review.status === "sent") return `sent ${review.sent} frames`;
  if (sending(review)) return `sending ${review.sent} of ${review.chosen}`;
  if (review.status === "queued") return review.retry_at ? `queued, sends after ${clock(review.retry_at)}` : "queued";
  if (review.status === "running") return "printing";
  return review.status === "ready" ? "waiting for review" : "not reviewed";
}

export function awaitingReview(reviews: ReviewSummary[], monitorId: string): ReviewSummary | undefined {
  return reviews.filter((review) => review.monitor_id === monitorId && review.status === "ready").at(-1);
}
