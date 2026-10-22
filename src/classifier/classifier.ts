import { StringOutputParser } from "@langchain/core/output_parsers";
import { z } from "zod";
import { getLLM } from "../llm.js";
import { classifierPrompt } from "./classifier.prompt.js";
import { ClassificationSchema, type Classification } from "../schemas.js";
import { formatResponse } from "../knowledge-delivery/knowledge-delivery.js";

/** Strip code fences / surrounding text and return the JSON substring. */
function extractJson(raw: string): string {
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const text = fenced ? fenced[1] : raw;
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end === -1)
    throw new Error("No JSON object found in response");
  return text.slice(start, end + 1);
}

function validate(raw: string): Classification {
  return ClassificationSchema.parse(JSON.parse(extractJson(raw)));
}

let chainPromise: Promise<Awaited<ReturnType<typeof buildChain>>> | undefined;

async function buildChain() {
  const llm = await getLLM();
  return classifierPrompt.pipe(llm).pipe(new StringOutputParser());
}

export async function classify(
  query: string,
  maxRetries = 2
): Promise<Classification> {
  chainPromise = buildChain();
  const chain = await chainPromise;

  let feedback: [string, string][] = [];

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const raw = await chain.invoke({ query, feedback });
    try {
      // const validatedResult = validate(raw);
      // console.log(validatedResult);
      // // forward this validatedResult to the database agent and get the output
      // // get the response from the database agent
      // // replace the validatedResult with the response of the database agent
      // const reply = await formatResponse(query, validatedResult);
      // return reply;

      return validate(raw);
    } catch (err) {
      const msg =
        err instanceof z.ZodError
          ? JSON.stringify(err.issues)
          : (err as Error).message;
      if (attempt === maxRetries) {
        throw new Error(
          `Invalid classifier JSON after ${attempt + 1} attempts: ${msg}`
        );
      }
      // Feed validation errors back so the model can self-correct
      feedback = [
        ["assistant", raw],
        [
          "human",
          `Your response failed validation: ${msg}. Return corrected JSON only.`,
        ],
      ];
    }
  }
  throw new Error("unreachable");
}
