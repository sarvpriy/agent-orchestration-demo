// Minimal OpenAI-compatible mock LLM so the full workflow can be tested without API keys.
// Usage: node tests/mock_llm.mjs [port]   (default 4010)
import http from "node:http";

const port = Number(process.argv[2] ?? process.env.MOCK_LLM_PORT ?? 4010);

function classify(query) {
  const q = query.toLowerCase();
  const nonIT = /air ?condition|seat|badge|access card|layout|facilit|printer|desk/.test(q);
  const domain = nonIT ? "non-IT" : "IT";
  let category = "incident";
  if (/every week|recurring|root cause|several employees|failing repeatedly/.test(q)) category = "problem";
  else if (/install|upgrade|\bchange\b|request|migrate/.test(q)) category = "change";

  const title = query.slice(0, 80);
  const payloads = {
    incident: { title, description: query, severity: "P3", impact: "unknown", affectedService: null, symptoms: [] },
    change: { title, description: query, changeType: "normal", riskLevel: "medium", justification: "requested", affectedService: null, requestedDate: null },
    problem: { title, description: query, suspectedRootCause: null, relatedIncidents: [], workaround: null, priority: "medium" },
  };
  return { category, domain, confidence: 0.9, reasoning: "mock", payload: payloads[category] };
}

function reply(messages) {
  const system = messages.find((m) => m.role === "system")?.content ?? "";
  const human = messages.filter((m) => m.role === "user" || m.role === "human").at(-1)?.content ?? "";
  if (system.includes("ITSM classifier")) {
    return JSON.stringify(classify(String(human)));
  }
  // formatter: "User query: ...\n\nResult JSON:\n{...}"
  const m = String(human).match(/Result JSON:\n([\s\S]*)$/);
  try {
    const r = JSON.parse(m[1]);
    const k = r.knowledge_retrieval ?? r;
    const titles = (k.results ?? []).map((x) => `${x.article_id} ${x.title}`).join("; ");
    const t = r.ticket ?? {};
    const ticket = t.error ? `error=${t.error}` : `${t.ticket?.number} created=${t.created}`;
    return `[mock] status=${k.status} escalation=${k.escalation_required} articles: ${titles || "none"} | ticket=${ticket}`;
  } catch {
    return "[mock] could not parse result";
  }
}

http
  .createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      if (req.method !== "POST" || !req.url.endsWith("/chat/completions")) {
        res.writeHead(404).end();
        return;
      }
      const { messages = [], model = "mock" } = JSON.parse(body || "{}");
      const content = reply(messages);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          id: "mock-1",
          object: "chat.completion",
          created: Math.floor(Date.now() / 1000),
          model,
          choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
        })
      );
    });
  })
  .listen(port, "127.0.0.1", () => console.log(`mock LLM listening on http://127.0.0.1:${port}/v1`));
