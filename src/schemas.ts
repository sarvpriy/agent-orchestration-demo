import { z } from "zod";

const IncidentPayload = z.object({
  title: z.string().min(1),
  description: z.string().min(1),
  severity: z.enum(["P1", "P2", "P3", "P4"]),
  impact: z.string(),
  affectedService: z.string().nullable(),
  symptoms: z.array(z.string()),
});

const ChangePayload = z.object({
  title: z.string().min(1),
  description: z.string().min(1),
  changeType: z.enum(["standard", "normal", "emergency"]),
  riskLevel: z.enum(["low", "medium", "high"]),
  justification: z.string(),
  affectedService: z.string().nullable(),
  requestedDate: z.string().nullable(),
});

const ProblemPayload = z.object({
  title: z.string().min(1),
  description: z.string().min(1),
  suspectedRootCause: z.string().nullable(),
  relatedIncidents: z.array(z.string()),
  workaround: z.string().nullable(),
  priority: z.enum(["low", "medium", "high", "critical"]),
});

const base = {
  confidence: z.number().min(0).max(1),
  reasoning: z.string(),
};

export const ClassificationSchema = z.discriminatedUnion("category", [
  z.object({
    category: z.literal("incident"),
    ...base,
    payload: IncidentPayload,
  }),
  z.object({ category: z.literal("change"), ...base, payload: ChangePayload }),
  z.object({
    category: z.literal("problem"),
    ...base,
    payload: ProblemPayload,
  }),
]);

export type Classification = z.infer<typeof ClassificationSchema>;
