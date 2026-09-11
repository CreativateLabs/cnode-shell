// c:node Assistant — shared contracts (Single Source of Truth, mirrors SCOPE.md §2).
// Frozen v1. Do not change without the integration agent.

export type Intent =
  | "decision" | "knowledge" | "leads" | "foerderung" | "ingest" | "graph" | "smalltalk";

export type NodeType =
  | "Company" | "Product" | "Decision" | "Document"
  | "Person" | "FundingProgram" | "Lead" | "Thought" | "Area" | "Compliance";

export interface GNode { id: string; label: string; type: NodeType | string; props?: Record<string, unknown>; }
export interface GEdge { source: string; target: string; rel: string; provenance?: string; }
export interface Graph { nodes: GNode[]; edges: GEdge[]; }

export interface Source { id: string; label: string; type?: string; props?: Record<string, unknown>; provenance?: string; }

export type ArtifactKind = "dialog_protocol" | "memo" | "proposal" | "one_pager";
export interface Artifact {
  id: string; kind: ArtifactKind; title: string; markdown: string;
  client_id: string; thread_id: string; created_at: string;
}

export interface TraceStep { step: string; method?: string; result?: string; service?: string; [k: string]: unknown; }

// BFF POST /ask
export interface AskRequest { text: string; client_id: string; thread_id?: string; provider?: "ollama" | "claude"; }
export interface AskResponse {
  intent: Intent;
  route: "engine" | "assets" | "graph";
  result_text: string;
  sources: Source[];
  artifact: Artifact | null;
  graph_delta: Graph;
  highlight: string[];
  trace: TraceStep[];
  provider: string;
  model: string;
}

export interface Client { id: string; label: string; }
export interface Lead { name: string; segment: string; score: number; reason: string; contact?: string; }
export interface FundingProgram { name: string; fit: number; max_foerderung?: string; reason: string; frist?: string; }

export const PORTS = { shell: 3010, bff: 8080, engine: 8020, assets: 8030 } as const;
