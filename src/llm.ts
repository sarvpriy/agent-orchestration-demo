// import { initChatModel } from "langchain/chat_models/universal";
// import type { BaseChatModel } from "@langchain/core/language_models/chat_models";

// /**
//  * Provider-agnostic chat model.
//  * Configure with env vars: LLM_PROVIDER (openai | anthropic | google-genai | ...)
//  * and LLM_MODEL. Any provider supported by LangChain's initChatModel works,
//  * as long as its @langchain/* package is installed.
//  */
// export async function getLLM(): Promise<BaseChatModel> {
//   const provider = process.env.LLM_PROVIDER;
//   const model = process.env.LLM_MODEL;

//   if (!provider || !model) {
//     throw new Error("Set LLM_PROVIDER and LLM_MODEL in your .env file (see .env.example).");
//   }

//   const llm = await initChatModel(model, {
//     modelProvider: provider,
//     temperature: 0,
//   });
//   return llm as unknown as BaseChatModel;
// }

import { ChatOpenAI } from "@langchain/openai";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";

export async function getLLM(): Promise<BaseChatModel> {
  const { LLM_BASE_URL, LLM_API_KEY, LLM_MODEL } = process.env;

  if (!LLM_API_KEY || !LLM_MODEL) {
    throw new Error("Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in .env");
  }

  // return new ChatOpenAI({
  //   model: LLM_MODEL,
  //   apiKey: LLM_API_KEY,
  //   temperature: 0,
  //   configuration: { baseURL: LLM_BASE_URL },
  // });

  return new ChatOpenAI({
    model: process.env.GROQ_MODEL,
    apiKey: process.env.GROQ_API_KEY,
    temperature: 0,
    configuration: { baseURL: LLM_BASE_URL },
  });

  // return new ChatGoogleGenerativeAI({
  //   model: LLM_MODEL || "gemini-flash-latest", // e.g. "gemini-flash-latest"
  //   apiKey: LLM_API_KEY, // <key>
  //   temperature: 0,
  //   maxRetries: 3,
  // });

  // return new ChatGoogleGenerativeAI({
  //   model: LLM_MODEL || "gemini-flash-latest", // e.g. "gemini-flash-latest", "gemini-2.5-flash-lite"
  //   apiKey: LLM_API_KEY, // <key>
  //   temperature: 0,
  //   maxRetries: 3,
  //   // ...(LLM_BASE_URL ? { baseUrl: LLM_BASE_URL } : {}), // only for a custom gateway
  // });
}
