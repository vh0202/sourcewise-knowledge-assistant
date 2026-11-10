// Shapes of the JSON the API returns. They mirror sourcewise/schemas.py and sourcewise/insights.py.

export type Role = "admin" | "member";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
}

export interface EngineInfo {
  name: "offline" | "claude";
  label: string;
  model: string | null;
}

export interface DemoAccount {
  name: string;
  email: string;
  password: string;
  role: Role;
}

export interface Meta {
  name: string;
  version: string;
  notice: string;
  engine: EngineInfo;
  retriever: { name: string; label: string };
  demo_accounts: DemoAccount[];
}

export interface Collection {
  id: number;
  name: string;
  description: string;
  starter_questions: string[];
  document_count: number;
  chunk_count: number;
  created_at: string;
}

export type DocumentKind = "md" | "txt" | "pdf" | "html";
export type DocumentStatus = "queued" | "parsing" | "normalizing" | "chunking" | "indexing" | "ready" | "failed";

export interface Stage {
  name: string;
  label: string;
  status: "pending" | "running" | "done" | "failed";
  duration_ms: number | null;
  detail: string | null;
}

export interface KbDocument {
  id: number;
  collection_id: number;
  collection_name: string;
  title: string;
  filename: string;
  kind: DocumentKind;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  stages: Stage[];
  page_count: number | null;
  chunk_count: number;
  char_count: number;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
}

export interface Chunk {
  id: number;
  ordinal: number;
  text: string;
  heading_path: string[];
  page_start: number | null;
  page_end: number | null;
  start_char: number;
  end_char: number;
  overlap_chars: number;
  token_estimate: number;
}

export interface DocumentChunks {
  document: KbDocument;
  chunking: { max_chars: number; overlap_chars: number };
  chunks: Chunk[];
}

export interface Citation {
  number: number;
  chunk_id: number | null;
  document_id: number | null;
  document_title: string;
  document_kind: string;
  collection_name: string;
  heading_path: string[];
  page_start: number | null;
  page_end: number | null;
  passage: string;
  quote: string;
  start_char: number;
  end_char: number;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  engine: string | null;
  engine_label: string | null;
  model: string | null;
  abstained: boolean;
  abstain_reason: string | null;
  confidence: number | null;
  latency_ms: number | null;
  truncated: boolean;
  notice: string | null;
  feedback: number | null;
  citations: Citation[];
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface DayCount {
  date: string;
  answered: number;
  abstained: number;
}

export interface CitedDocument {
  document_id: number | null;
  title: string;
  collection: string;
  citations: number;
  answers: number;
  in_knowledge_base: boolean;
}

export interface KnowledgeGap {
  question: string;
  count: number;
  last_asked: string;
  reason: string;
}

export interface Insights {
  days: number;
  questions: number;
  answered: number;
  abstained: number;
  answer_rate: number | null;
  helpful: number;
  not_helpful: number;
  median_latency_ms: number | null;
  engines: Record<string, number>;
  daily: DayCount[];
  most_cited: CitedDocument[];
  gaps: KnowledgeGap[];
  knowledge_base: { collections: number; documents: number; chunks: number };
}

// Events of the answer stream (server-sent events).
export interface StreamStart {
  user_message: Message;
  conversation: { id: number; title: string };
  engine: EngineInfo;
}

export interface StreamRetrieval {
  passages: number;
  coverage: number;
  sufficient: boolean;
}

export interface StreamCitation {
  number: number;
  document_title: string;
  heading_path: string[];
  page_start: number | null;
}
