// Domain types shared across the UI. These mirror the backend API contract
// (/api/v1). The UI never computes permissions or business logic — it renders
// exactly what the API returns, already permission-filtered server-side.

export type Id = string;

export interface UserSummary {
  id: Id;
  username: string;
  name: string;
  role: string;
  department: string | null;
  status: "active" | "inactive" | "archived";
}

/** Navigation entitlements returned by the API for the current session.
 *  The UI hides surfaces the user is not entitled to — but the server is
 *  always the enforcer; this only controls what is *rendered*. */
export interface SessionEntitlements {
  user: UserSummary;
  edition: "starter" | "professional" | "enterprise";
  nav: {
    chat: boolean;
    search: boolean;
    documents: boolean;
    admin: boolean;
    evaluation: boolean;
    audit: boolean;
    system: boolean;
  };
}

export type ProcessingState =
  | "queued"
  | "converting"
  | "chunking"
  | "embedding"
  | "indexing"
  | "indexed"
  | "active"
  | "failed"
  | "quarantined";

export interface DocumentVersion {
  versionId: Id;
  versionNo: number;
  isActive: boolean;
  processingState: ProcessingState;
  uploadedAt: string;
  pageCount: number | null;
  fileType: string;
}

/** A logical document — the stable identity across versions. */
export interface LogicalDocument {
  id: Id;
  title: string;
  department: string | null;
  accessLevel: string | null;
  documentType: string | null;
  project: string | null;
  phase: string | null;
  uploadDate: string;
  lastModified: string | null;
  activeVersionNo: number;
  versionCount: number;
  fileType: string;
  state?: string;
}

export interface SearchHit {
  document: LogicalDocument;
  snippet: string;      // may contain <mark>…</mark> for highlight
  relevance: number;    // 0–1
  jumpTo?: { page: number; region?: [number, number, number, number] };
}

export interface Facet {
  field: string;
  label: string;
  values: { value: string; count: number }[]; // permission-scoped by the API
}

export interface Citation {
  documentId: Id;
  documentTitle: string;
  versionNo: number;
  page: number;
  region?: [number, number, number, number]; // bbox, 0–1 normalized
}

export type AnswerVerdict =
  | "answerable"
  | "assumption"
  | "clarification"
  | "unanswerable"
  | "partial";

// Client-side only -- never returned by the backend. Distinguishes a genuine
// "not in the documents" refusal from a request failure (network error, 500,
// timeout) so the two don't render as the same "can't answer" message.
export type ClientAnswerVerdict = AnswerVerdict | "error";

export interface ChatAnswer {
  verdict: ClientAnswerVerdict;
  text: string;
  assumptions?: string[];
  clarificationQuestion?: string;
  unanswerableReason?: string;
  citations: Citation[];
}

export interface ChatMessage {
  id: Id;
  role: "user" | "assistant";
  content: string;
  answer?: ChatAnswer; // present on assistant messages
}

export interface LatencyPoint {
  span: string;      // e.g. "search.dense.query"
  p50: number;
  p95: number;
  p99: number;
}

export interface QualityRun {
  runId: Id;
  ts: string;
  faithfulness: number;
  precision: number;
  recall: number;
  hitAtK: number;
}

export interface TraceSpan {
  spanName: string;
  durationMs: number;
  attributes: Record<string, string | number | boolean>;
}

export interface AuditEntry {
  id: Id;
  ts: string;
  actor: string;
  action: string;
  resource: string;
  outcome: "allowed" | "denied";
  detail?: string;
}

export interface ServiceHealth {
  name: string;
  status: "online" | "degraded" | "offline";
  detail: string;
}

export interface LicenseStatus {
  edition: SessionEntitlements["edition"];
  customer: string;
  validUntil: string;
  seats: { used: number; max: number };
  documents: { used: number; max: number | null };
  features: string[];
}

// ---- conversations (5.5) ----
export interface ConversationSummary {
  id: Id;
  title: string;
  updatedAt: string;
  messageCount: number;
  locked: boolean;
}

// ---- version management (02.1) ----
export interface ManagedVersion extends DocumentVersion {
  note?: string;
}

export interface VersionManagementView {
  document: LogicalDocument;
  versions: ManagedVersion[];
  canManage: boolean; // reflects the `manage_versions` permission (server-decided)
}

// ---- onboarding / editions (09) ----
export interface EditionSpec {
  id: "starter" | "professional" | "enterprise";
  name: string;
  blurb: string;
  limits: { users: string; documents: string };
  features: string[];
  minSpecs: { cpu: string; ram: string; gpu: string; disk: string };
  requiresLicense: boolean;
}
export interface PreflightResult {
  detected: { cpu: string; ram: string; gpu: string; disk: string };
  checks: { label: string; ok: boolean; detail: string }[];
  ready: boolean;
}

// ---- licensing (09) ----
export interface LicenseRequest { fingerprint: string; requestBlob: string; }

// ---- permissions / ACL (5.1) ----
export interface Department { id: Id; name: string; }
export interface DocumentType { id: Id; label: string; }
export interface AccessLevel { id: Id; departmentId: Id; label: string; rank: number; }
export interface RoleGrant { roleId: Id; roleLabel: string; accessLevelIds: Id[]; }
export interface PermissionMatrix { roles: { id: Id; label: string }[]; accessLevels: AccessLevel[]; grants: RoleGrant[]; }

// ---- sources / connectors (02.1) ----
export type ConnectorKind = "filesystem" | "s3" | "sql" | "sqlite" | "api" | "sharepoint";
export interface DocumentSourceConfig {
  id: Id; name: string; kind: ConnectorKind; enabled: boolean;
  location: string; pathMapping: string | null; lastScan: string | null; status: "connected" | "error" | "disabled";
}
export interface IngestionJob {
  id: Id; documentTitle: string; state: ProcessingState; progress: number; sourceName: string;
  startedAt: string; error: string | null;
}
export interface QuarantineItem {
  id: Id; documentTitle: string; reason: string; stage: string; quarantinedAt: string;
}

// ---- metadata obligation policy (02.1 §4.3) ----
export interface MetadataPolicyRow {
  field: "department" | "access_level" | "document_type" | "project" | "phase";
  label: string;
  scope: "global" | "per_department";
  required: boolean;
  exceptions: string[]; // department ids exempted
}

// ---- retention / erasure (5.2) ----
export interface RetentionPolicy {
  conversationDays: number | null; // null = keep indefinitely
  auditDays: number | null;
  legalHold: boolean;
}
export interface ErasureRequest {
  id: Id; subject: string; requestedAt: string; status: "pending" | "completed" | "blocked_legal_hold";
}
