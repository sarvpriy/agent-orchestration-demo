import { ChatPromptTemplate } from "@langchain/core/prompts";

/** Add or edit categories here; the system prompt is built from this list. */
export const CATEGORIES = [
  {
    name: "incident",
    definition: "an unplanned interruption or degradation of a service happening now.",
    shape: `{{"category":"incident","confidence":0-1,"reasoning":"...","payload":{{"title":"","description":"","severity":"P1|P2|P3|P4","impact":"","affectedService":string|null,"symptoms":[""]}}}}`,
  },
  {
    name: "change",
    definition: "a request to add, modify, or remove something in the environment (planned work).",
    shape: `{{"category":"change","confidence":0-1,"reasoning":"...","payload":{{"title":"","description":"","changeType":"standard|normal|emergency","riskLevel":"low|medium|high","justification":"","affectedService":string|null,"requestedDate":"ISO-8601 string"|null}}}}`,
  },
  {
    name: "problem",
    definition: "investigation of the underlying/root cause of recurring or major incidents.",
    shape: `{{"category":"problem","confidence":0-1,"reasoning":"...","payload":{{"title":"","description":"","suspectedRootCause":string|null,"relatedIncidents":[""],"workaround":string|null,"priority":"low|medium|high|critical"}}}}`,
  },
] as const;

const RULES = `Respond with ONLY a JSON object (no markdown, no prose).
Use null for unknown values and [] for empty lists.
Never invent facts that are not in the query.`;

function buildSystemPrompt(): string {
  const defs = CATEGORIES.map((c) => `- ${c.name}: ${c.definition}`).join("\n");
  const shapes = CATEGORIES.map((c) => `${c.name}:\n${c.shape}`).join("\n\n");
  return [
    "You are an ITSM classifier. Classify the user query into exactly one category:",
    defs,
    "Return JSON matching one of these shapes:",
    shapes,
    RULES,
  ].join("\n\n");
}

export const classifierPrompt = ChatPromptTemplate.fromMessages([
  ["system", buildSystemPrompt()],
  ["human", "{query}"],
  ["placeholder", "{feedback}"],
]);
