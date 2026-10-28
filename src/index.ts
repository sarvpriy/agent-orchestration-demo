import * as readline from "node:readline/promises";
import "dotenv/config";
import { stdin as input, stdout as output } from "node:process";
import { classify } from "./classifier/classifier.js";
import { formatResponse } from "./knowledge-delivery/knowledge-delivery.js";
import { findOrCreateTicket } from "./ticketing/ticketing.js";

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
  ticket: Annotation<any>(),
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

  const { category, domain, confidence } = state.classification;
  const res = await fetch(url, {
    method: "POST",
    headers: { Accept: "*/*", "Content-Type": "application/json" },
    body: JSON.stringify({
      category,
      domain,
      request: state.query,
      confidence,
      original_request: state.query,
    }),
  });
  if (!res.ok) {
    throw new Error(`Retrieval failed: ${res.status} ${await res.text()}`);
  }

  const result = await res.json();
  return { knowledge: result.knowledge_retrieval };
}

// 3. Ticket node: reuse a similar open ticket, or create one.
// A ticketing failure must not hide the knowledge answer, so it is reported in the reply.
async function ticketNode(state: typeof State.State) {
  try {
    const ticket = await findOrCreateTicket(state.query, state.classification);
    return { ticket };
  } catch (err) {
    const message = (err as Error).message;
    console.error("Ticketing failed:", message);
    return { ticket: { error: message } };
  }
}

// 4. Format response node
async function formatNode(state: typeof State.State) {
  const reply = await formatResponse(state.query, {
    knowledge_retrieval: state.knowledge,
    ticket: state.ticket,
  });
  return { reply };
}

// Build the graph
const graph = new StateGraph(State)
  .addNode("classify", classifyNode)
  .addNode("retrieve", retrievalNode)
  .addNode("manage_ticket", ticketNode)
  .addNode("format", formatNode)
  .addEdge(START, "classify")
  .addEdge("classify", "retrieve")
  .addEdge("retrieve", "manage_ticket")
  .addEdge("manage_ticket", "format")
  .addEdge("format", END)
  .compile();

async function run(query: string): Promise<boolean> {
  try {
    const finalState = await graph.invoke({ query });
    console.log(JSON.stringify(finalState.reply, null, 2));
    return true;
  } catch (err) {
    console.error("Error:", (err as Error).message);
    return false;
  }
}

async function main() {
  // One-shot mode: npm start -- "my query here"
  const argQuery = process.argv.slice(2).join(" ").trim();
  if (argQuery) {
    if (!(await run(argQuery))) process.exitCode = 1;
    return;
  }

  // Interactive mode
  const rl = readline.createInterface({ input, output });
  console.log('Enter a query (type "exit" to quit).');
  let closed = false;
  rl.on("close", () => (closed = true));
  const prompt = () => {
    if (!closed) rl.prompt();
  };
  rl.setPrompt("\n> ");
  prompt();
  // Async iteration buffers lines, so piped input and Ctrl+D end cleanly.
  for await (const line of rl) {
    const query = line.trim();
    if (query.toLowerCase() === "exit") break;
    if (query) await run(query);
    prompt();
  }
  rl.close();
}

main();
