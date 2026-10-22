import { ChatPromptTemplate } from "@langchain/core/prompts";
import { StringOutputParser } from "@langchain/core/output_parsers";
import { getLLM } from "../llm.js";

const MAX_JSON_CHARS = 12_000; // guard against huge payloads

const formatterPrompt = ChatPromptTemplate.fromMessages([
  [
    "system",
    `You are a friendly ServiceNow assistant. Turn the JSON result into a short, casual, human-readable reply to the user's query.

Rules:
- Answer the user's question directly, using only facts from the JSON. Never invent data.
- Be conversational and concise (2-5 sentences, or a short list for multiple records).
- Translate codes into plain words (e.g. state "2" -> "In Progress", priority "1" -> "Critical") when the meaning is clear.
- Skip internal fields like sys_id unless the user asked for them. Keep record numbers (e.g. INC0010001).
- If the result is empty or has an error, say so kindly and suggest a next step.
- Plain text only, no JSON, no code fences.`,
  ],
  ["human", "User query: {query}\n\nResult JSON:\n{result}"],
]);

let chainPromise: ReturnType<typeof buildChain> | undefined;

async function buildChain() {
  const llm = await getLLM();
  return formatterPrompt.pipe(llm).pipe(new StringOutputParser());
}

export async function formatResponse(
  query: string,
  result: unknown
): Promise<string> {
  chainPromise ??= buildChain();
  const chain = await chainPromise;

  let json =
    typeof result === "string" ? result : JSON.stringify(result, null, 2);
  if (json.length > MAX_JSON_CHARS) {
    json = json.slice(0, MAX_JSON_CHARS) + "\n...[truncated]";
  }

  try {
    return (await chain.invoke({ query, result: json })).trim();
  } catch (err) {
    console.error("Knowledge Delivery failed:", err);
    return "Sorry, I got your results but had trouble summarizing them. Please try again.";
  }
}
