import { ChatOpenAI } from "@langchain/openai";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";

const GROQ_OPENAI_BASE_URL = "https://api.groq.com/openai/v1";
const DEFAULT_MODEL = "openai/gpt-oss-120b";

/**
 * Groq via its OpenAI-compatible endpoint.
 * Env: GROQ_API_KEY (required), GROQ_MODEL, LLM_BASE_URL (override, e.g. a local mock).
 */
export async function getLLM(): Promise<BaseChatModel> {
  const { GROQ_API_KEY, GROQ_MODEL, LLM_BASE_URL } = process.env;

  if (!GROQ_API_KEY) {
    throw new Error("GROQ_API_KEY is missing. Add it to .env (see env.example).");
  }

  return new ChatOpenAI({
    model: GROQ_MODEL || DEFAULT_MODEL,
    apiKey: GROQ_API_KEY,
    temperature: 0,
    configuration: { baseURL: LLM_BASE_URL || GROQ_OPENAI_BASE_URL },
  });
}
