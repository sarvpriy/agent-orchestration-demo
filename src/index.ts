import * as readline from "node:readline/promises";
import "dotenv/config";
import { stdin as input, stdout as output } from "node:process";
import { classify } from "./classifier/classifier.js";
import { formatResponse } from "./knowledge-delivery/knowledge-delivery.js";

// async function run(query: string) {
//   try {
//     const result = await classify(query);
//     console.log(JSON.stringify(result, null, 2));
//   } catch (err) {
//     console.error("Error:", (err as Error).message);
//   }
// }

// async function run(query: string) {
//   try {
//     // 1. Classify the query
//     const classificationResult = await classify(query);
//     // console.log(JSON.stringify(classificationResult, null, 2));
//     // forward this validatedResult to the database agent and get the output
//     // get the response from the database agent
//     // 2. Retrieve (Python service)
//     if (!process.env.KNOWLEDGE_RETRIEVAL_AGENT_URL) {
//       throw new Error(
//         "KNOWLEDGE_RETRIEVAL_AGENT_URL is not set in the environment variables."
//       );
//     }

//     // knowledge retrieval: call the knowledge retrieval agent with the query and classification result
//     let headersList = {
//       Accept: "*/*",
//       "Content-Type": "application/json",
//     };

//     let bodyContent = JSON.stringify({
//       category: classificationResult.category,
//       domain: classificationResult.category === "incident" ? "IT" : "non-IT",
//       request: query,
//       confidence: 0.9,
//       original_request: query,
//     });

//     let response = await fetch(process.env.KNOWLEDGE_RETRIEVAL_AGENT_URL, {
//       method: "POST",
//       body: bodyContent,
//       headers: headersList,
//     });

//     let result = await response.json();
//     // console.log("Knowledge retrieval result:", JSON.stringify(result, null, 2));

//     // knowledge delivery: format the response for the user
//     const reply = await formatResponse(query, result.knowledge_retrieval);
//     // return reply;
//     console.log(JSON.stringify(reply, null, 2));
//   } catch (err) {
//     console.error("Error:", (err as Error).message);
//   }
// }

import { StateGraph, Annotation, START, END } from "@langchain/langgraph";

// Shared state passed between agents
const State = Annotation.Root({
  query: Annotation<string>(),
  classification: Annotation<any>(),
  knowledge: Annotation<any>(),
  reply: Annotation<any>(),
});

// 1. Classify node
async function classifyNode(state: typeof State.State) {
  const classification = await classify(state.query);
  return { classification };
}

// 2. Knowledge retrieval node (Python service)
async function retrievalNode(state: typeof State.State) {
  const url = process.env.KNOWLEDGE_RETRIEVAL_AGENT_URL;
  if (!url) throw new Error("KNOWLEDGE_RETRIEVAL_AGENT_URL is not set.");

  const { category } = state.classification;
  const res = await fetch(url, {
    method: "POST",
    headers: { Accept: "*/*", "Content-Type": "application/json" },
    body: JSON.stringify({
      category,
      domain: category === "incident" ? "IT" : "non-IT",
      request: state.query,
      confidence: 0.9,
      original_request: state.query,
    }),
  });
  if (!res.ok) throw new Error(`Retrieval failed: ${res.status}`);

  const result = await res.json();
  return { knowledge: result.knowledge_retrieval };
}

// 3. Format response node
async function formatNode(state: typeof State.State) {
  const reply = await formatResponse(state.query, state.knowledge);
  return { reply };
}

// Build the graph
const graph = new StateGraph(State)
  .addNode("classify", classifyNode)
  .addNode("retrieve", retrievalNode)
  .addNode("format", formatNode)
  .addEdge(START, "classify")
  .addEdge("classify", "retrieve")
  .addEdge("retrieve", "format")
  .addEdge("format", END)
  .compile();

async function run(query: string) {
  try {
    const finalState = await graph.invoke({ query });
    console.log(JSON.stringify(finalState.reply, null, 2));
  } catch (err) {
    console.error("Error:", (err as Error).message);
  }
}

async function main() {
  // One-shot mode: npm start -- "my query here"
  const argQuery = process.argv.slice(2).join(" ").trim();
  if (argQuery) {
    await run(argQuery);
    return;
  }

  // Interactive mode
  const rl = readline.createInterface({ input, output });
  console.log('Enter a query (type "exit" to quit).');
  while (true) {
    const query = (await rl.question("\n> ")).trim();
    if (!query) continue;
    if (query.toLowerCase() === "exit") break;
    await run(query);
  }
  rl.close();
}

main();
