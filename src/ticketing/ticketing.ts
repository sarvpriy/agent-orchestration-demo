import type { Classification } from "../schemas.js";

export interface TicketResult {
  created: boolean;
  duplicate_of: string | null;
  similarity: number;
  ticket: {
    number: string;
    status: string;
    category: string;
    domain: string;
    title: string;
    priority: string | null;
    occurrences: number;
  };
}

/** Ticket service URL: TICKET_AGENT_URL, else derived from the retrieval URL. */
function ticketUrl(): string {
  const explicit = process.env.TICKET_AGENT_URL;
  if (explicit) return explicit;

  const retrieval = process.env.KNOWLEDGE_RETRIEVAL_AGENT_URL;
  if (!retrieval) {
    throw new Error(
      "Set TICKET_AGENT_URL or KNOWLEDGE_RETRIEVAL_AGENT_URL in the environment."
    );
  }
  return retrieval.replace(/\/retrieve\/?$/, "/tickets/find-or-create");
}

/** Severity / risk / priority, whichever the category carries. */
function priorityOf(c: Classification): string | null {
  switch (c.category) {
    case "incident":
      return c.payload.severity;
    case "change":
      return c.payload.riskLevel;
    case "problem":
      return c.payload.priority;
  }
}

/**
 * Attach the request to a similar open ticket, or create a new one.
 * The duplicate check happens in the ticket service.
 */
export async function findOrCreateTicket(
  query: string,
  classification: Classification
): Promise<TicketResult> {
  const res = await fetch(ticketUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      category: classification.category,
      domain: classification.domain,
      title: classification.payload.title,
      description: classification.payload.description,
      request: query,
      priority: priorityOf(classification),
      payload: classification.payload,
    }),
  });

  if (!res.ok) {
    throw new Error(`Ticket service failed: ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as TicketResult;
}
