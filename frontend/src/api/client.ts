// Typed fetch helpers for every endpoint in docs/api-contract.md, docs/api-contract-phase2.md,
// docs/api-contract-phase3.md, docs/api-contract-phase4.md (AI-01 to AI-07, GOV-03), docs/api-contract-phase5.md
// (EXP-08, EXP-09, EXP-10, EXP-11, D-03, D-13: channel transport, feed templates, delivery, Walmart feeds, Shopify sandbox)
// and docs/api-contract-phase6.md (DM-13 relationships, GOV-02 restore-to and change sets, DM-07 digest settings).
// All calls go through `request` so errors surface the server's `{detail}` message.

import type {
  ApprovalQueue,
  AttributeDefinition,
  AttributeGroup,
  AttributeUsageRow,
  Channel,
  Dashboard,
  ErpDefectsReport,
  Family,
  Health,
  HistoryResult,
  ImageQueue,
  ImageQueueKind,
  JobRun,
  Me,
  OptionList,
  Package,
  PackageCreate,
  PackageDetail,
  ProductDetail,
  ProductImages,
  ProductQuery,
  ProductQueryResult,
  ProductTree,
  ReferenceEntityList,
  ReferenceEntityRow,
  ReferenceImpact,
  ReferenceType,
  SavedView,
  Telemetry,
  UserRole,
  ValueEditResponse,
  BulkAction,
  BulkPreviewRequest,
  CarryoverInfo,
  Comment,
  CompareResult,
  ImportBatch,
  ImportBatchList,
  ImportConflictList,
  ImportRollbackResult,
  ImportRow,
  ImportRowList,
  ImportSource,
  Level,
  MappingSuggestion,
  MappingTemplate,
  MappingUpdate,
  FileEdit,
  MatchStatus,
  NotificationList,
  Rule,
  RuleInput,
  RulePreview,
  RuleRun,
  RowAction,
  ValueMappings,
  WorkflowDefinition,
  WorkflowInbox,
  WorkflowItem,
  WorkflowManager,
  WorkflowReject,
  WorkflowScope,
  Worksheet,
  WorksheetCreate,
  WorksheetCreated,
  ChannelDelta,
  ChannelHealth,
  ChannelMapping,
  ChannelMappingUpdate,
  Eligibility,
  EligibilityOverride,
  ExportSchedule,
  FeedbackResult,
  ImageLink,
  Publish,
  PublishDetail,
  PublishItemList,
  PublishList,
  PublishRequest,
  Rendition,
  RunNowResult,
  SchemaDiff,
  ShotType,
  TargetSchema,
  AiAskRequest,
  AiMetrics,
  AiOutput,
  AiOutputList,
  AiRun,
  AiRunCreate,
  AiRunDetail,
  AiRunList,
  BrandVoice,
  EvalCase,
  EvalRun,
  PromptTemplate,
  PromptTemplateDetail,
  PromptTemplateInput,
  QualityDashboardBy,
  QualityDashboardRow,
  QualityScore,
  QualitySettings,
  TemplatePreview,
  ChannelTransport,
  DeliveryResult,
  FeedTemplateUpload,
  SandboxReport,
  ChangeSet,
  ChangeSetList,
  MeSettings,
  Relationship,
  RelationshipAddRequest,
  RelationshipAddResult,
  RelationshipType,
  RestoreToResult,
  RollbackResult,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
      else if (body && body.detail) detail = JSON.stringify(body.detail);
    } catch {
      // keep status text
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) });
const del = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "DELETE", body: body === undefined ? undefined : JSON.stringify(body) });

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// ---- Core ----
export const api = {
  health: () => get<Health>("/api/health"),
  me: () => get<Me>("/api/me"),

  // ---- Metadata (P5: everything renders from these) ----
  metadata: {
    attributes: (params: { level?: string; group?: string } = {}) =>
      get<AttributeDefinition[]>(`/api/metadata/attributes${qs(params)}`),
    createAttribute: (body: AttributeDefinition) => post<AttributeDefinition>("/api/metadata/attributes", body),
    updateAttribute: (code: string, body: Partial<AttributeDefinition>) =>
      put<AttributeDefinition>(`/api/metadata/attributes/${encodeURIComponent(code)}`, body),
    groups: () => get<AttributeGroup[]>("/api/metadata/groups"),
    saveGroups: (body: AttributeGroup[]) => put<AttributeGroup[]>("/api/metadata/groups", body),
    optionLists: () => get<OptionList[]>("/api/metadata/option-lists"),
    saveOptionList: (code: string, body: OptionList) =>
      put<OptionList>(`/api/metadata/option-lists/${encodeURIComponent(code)}`, body),
    families: () => get<Family[]>("/api/metadata/families"),
    channels: () => get<Channel[]>("/api/metadata/channels"),
    saveChannel: (code: string, body: Channel) => put<Channel>(`/api/metadata/channels/${encodeURIComponent(code)}`, body),
    referenceTypes: () => get<ReferenceType[]>("/api/metadata/reference-types"),
    shotTypes: () => get<ShotType[]>("/api/metadata/shot-types"),
  },

  // ---- Reference entities (DM-11) ----
  reference: {
    list: (type: string, params: { q?: string; page?: number; page_size?: number } = {}) =>
      get<ReferenceEntityList>(`/api/reference-entities/${encodeURIComponent(type)}${qs(params)}`),
    detail: (type: string, id: string) =>
      get<ReferenceEntityRow>(`/api/reference-entities/${encodeURIComponent(type)}/${encodeURIComponent(id)}`),
    save: (type: string, id: string, values: Record<string, unknown>, confirm: boolean) =>
      put<ReferenceImpact>(
        `/api/reference-entities/${encodeURIComponent(type)}/${encodeURIComponent(id)}${confirm ? "?confirm=true" : ""}`,
        { values },
      ),
  },

  // ---- Products (DM-01, DM-02, DM-03, DM-05) ----
  products: {
    query: (body: ProductQuery) => post<ProductQueryResult>("/api/products/query", body),
    // `channel` is an assumption beyond the contract: when given, values resolve with that channel's
    // overrides so the detail page can compare global and channel values side by side (DM-06).
    detail: (entityId: string, channel?: string | null) =>
      get<ProductDetail>(`/api/products/${encodeURIComponent(entityId)}${qs({ channel })}`),
    setValues: (entityId: string, values: Record<string, unknown>, channelCode?: string | null) =>
      put<ValueEditResponse>(`/api/products/${encodeURIComponent(entityId)}/values`, {
        channel_code: channelCode ?? null,
        values,
      }),
    clearValues: (entityId: string, attributeCodes: string[], channelCode?: string | null) =>
      post<ValueEditResponse>(`/api/products/${encodeURIComponent(entityId)}/values/clear`, {
        attribute_codes: attributeCodes,
        channel_code: channelCode ?? null,
      }),
    history: (entityId: string, params: { attribute_code?: string; user_email?: string; page?: number } = {}) =>
      get<HistoryResult>(`/api/products/${encodeURIComponent(entityId)}/history${qs(params)}`),
    restore: (entityId: string, historyId: string) =>
      post<ValueEditResponse>(
        `/api/products/${encodeURIComponent(entityId)}/history/${encodeURIComponent(historyId)}/restore`,
      ),
    // Phase 6 (GOV-02): restore every attribute that changed after `at` to the value it held then.
    restoreTo: (entityId: string, body: { at?: string; history_id?: string; attribute_codes?: string[] }) =>
      post<RestoreToResult>(`/api/products/${encodeURIComponent(entityId)}/restore-to`, body),
    tree: (entityId: string) => get<ProductTree>(`/api/products/${encodeURIComponent(entityId)}/tree`),
    images: (entityId: string) => get<ProductImages>(`/api/products/${encodeURIComponent(entityId)}/images`),
  },

  // ---- Saved views (DM-02) ----
  views: {
    list: (level?: string) => get<SavedView[]>(`/api/views${qs({ level })}`),
    create: (body: Omit<SavedView, "id" | "owner_email">) => post<SavedView>("/api/views", body),
    update: (id: string, body: Partial<SavedView>) => put<SavedView>(`/api/views/${encodeURIComponent(id)}`, body),
    remove: (id: string) => del<void>(`/api/views/${encodeURIComponent(id)}`),
  },

  dashboard: () => get<Dashboard>("/api/dashboard"),

  // ---- Approvals (DM-08) ----
  approvals: {
    // Phase 4 (AI-04): `run_id` narrows the queue to one AI run; the response adds `runs`.
    queue: (group?: string, runId?: string) => get<ApprovalQueue>(`/api/approvals${qs({ group, run_id: runId })}`),
    decide: (draftIds: string[], decision: "approve" | "reject", comment?: string) =>
      post<{ decided?: number; [k: string]: unknown }>("/api/approvals/decide", {
        draft_ids: draftIds,
        decision,
        comment: comment || undefined,
      }),
  },

  // ---- Shopify update packages (EXP-13) ----
  packages: {
    list: (channel?: string) => get<Package[]>(`/api/packages${qs({ channel })}`),
    create: (body: PackageCreate) => post<Package>("/api/packages", body),
    detail: (id: string) => get<PackageDetail>(`/api/packages/${encodeURIComponent(id)}`),
    fileUrl: (id: string, name: string) =>
      `/api/packages/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`,
    snapshotUpload: (id: string, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<Package>(`/api/packages/${encodeURIComponent(id)}/snapshot-upload`, { method: "POST", body: fd });
    },
    reviewUpload: (id: string, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<PackageDetail>(`/api/packages/${encodeURIComponent(id)}/review-upload`, { method: "POST", body: fd });
    },
    reconcile: (id: string) => post<PackageDetail>(`/api/packages/${encodeURIComponent(id)}/reconcile`),
    // Phase 5 (D-03): targeted-mutation plan, or the run against the sandbox store. 409 when the sandbox store
    // is not configured (PIM_SHOPIFY_SANDBOX_DOMAIN and PIM_SHOPIFY_SANDBOX_TOKEN); callers check ApiError.status.
    sandboxRun: (id: string, planOnly: boolean) =>
      post<SandboxReport>(`/api/packages/${encodeURIComponent(id)}/sandbox-run`, { plan_only: planOnly }),
  },

  // ---- Images (IMG-03, IMG-05, IMG-06, IMG-07) ----
  images: {
    queue: (kind: ImageQueueKind, channel?: string) => get<ImageQueue>(`/api/images/queue${qs({ kind, channel })}`),
    // Phase 3: confirm also reports `written_back` (Air write-back, IMG-06).
    confirm: (linkId: string, shotType?: string) =>
      post<{ ok?: boolean; written_back?: boolean; [k: string]: unknown }>(`/api/images/links/${encodeURIComponent(linkId)}/confirm`, {
        shot_type: shotType,
      }),
    reject: (linkId: string) =>
      post<{ ok?: boolean; [k: string]: unknown }>(`/api/images/links/${encodeURIComponent(linkId)}/reject`, {}),
    setOrder: (entityId: string, linkIds: string[]) =>
      put<{ ok?: boolean; [k: string]: unknown }>(`/api/products/${encodeURIComponent(entityId)}/images/order`, { link_ids: linkIds }),
    updateAsset: (assetId: string, body: { ai_generated_image: boolean }) =>
      put<{ ok?: boolean; [k: string]: unknown }>(`/api/images/assets/${encodeURIComponent(assetId)}`, body),
    // 409 when PIM_FEATURE_IMAGE_AI_MATCH is off (callers check ApiError.status).
    aiCandidates: (assetId: string) =>
      post<{ candidates: ImageLink[] }>(`/api/images/assets/${encodeURIComponent(assetId)}/ai-candidates`),
    renditions: (assetId: string, channel?: string) =>
      get<Rendition[]>(`/api/images/assets/${encodeURIComponent(assetId)}/renditions${qs({ channel })}`),
    refreshRenditions: (channelCode: string, entityIds?: string[]) =>
      post<{ created: number; queued: number }>("/api/images/renditions/refresh", { channel_code: channelCode, entity_ids: entityIds }),
  },

  // ---- Admin ----
  admin: {
    erpDefects: (page = 1) => get<ErpDefectsReport>(`/api/admin/erp-defects${qs({ page })}`),
    attributeUsage: () => get<AttributeUsageRow[]>("/api/admin/attribute-usage"),
    userRoles: () => get<UserRole[]>("/api/admin/user-roles"),
    addUserRole: (body: UserRole) => post<UserRole>("/api/admin/user-roles", body),
    removeUserRole: (body: { id?: string; email: string; role: string }) => del<void>("/api/admin/user-roles", body),
    telemetry: () => get<Telemetry>("/api/admin/telemetry"),
  },

  jobs: {
    runs: (kind?: string) => get<JobRun[]>(`/api/jobs/runs${qs({ kind })}`),
    runIngest: () => post<JobRun>("/api/jobs/ingest/run"),
  },

  // =================================================================================
  // Phase 2
  // =================================================================================

  // ---- Imports (IMP-01 to IMP-08) ----
  imports: {
    sources: () => get<ImportSource[]>("/api/imports/sources"),
    createSource: (body: ImportSource) => post<ImportSource>("/api/imports/sources", body),
    updateSource: (code: string, body: ImportSource) =>
      put<ImportSource>(`/api/imports/sources/${encodeURIComponent(code)}`, body),
    templates: (source?: string) => get<MappingTemplate[]>(`/api/imports/templates${qs({ source })}`),
    // Saving from a batch: the contract says "save a template from a batch's mapping"; the body carries the
    // template fields plus `batch_id` so the server can take the structure signature from the batch.
    createTemplate: (body: Partial<MappingTemplate> & { batch_id?: string }) =>
      post<MappingTemplate>("/api/imports/templates", body),
    updateTemplate: (id: string, body: Partial<MappingTemplate>) =>
      put<MappingTemplate>(`/api/imports/templates/${encodeURIComponent(id)}`, body),
    deleteTemplate: (id: string) => del<void>(`/api/imports/templates/${encodeURIComponent(id)}`),
    batches: (params: { status?: string; source?: string; page?: number } = {}) =>
      get<ImportBatchList>(`/api/imports/batches${qs(params)}`),
    createBatch: (files: File[], sourceCode: string, level: Level) => {
      const fd = new FormData();
      for (const f of files) fd.append("file", f);
      fd.append("source_code", sourceCode);
      fd.append("level", level);
      return request<ImportBatch>("/api/imports/batches", { method: "POST", body: fd });
    },
    addFiles: (id: string, files: File[], sourceCode?: string) => {
      const fd = new FormData();
      for (const f of files) fd.append("file", f);
      if (sourceCode) fd.append("source_code", sourceCode);
      return request<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}/files`, { method: "POST", body: fd });
    },
    shopifyPull: (id: string, file?: File | null) => {
      const fd = new FormData();
      if (file) fd.append("file", file);
      return request<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}/shopify-pull`, { method: "POST", body: fd });
    },
    batch: (id: string) => get<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}`),
    suggestMapping: (id: string) => get<MappingSuggestion[]>(`/api/imports/batches/${encodeURIComponent(id)}/suggest-mapping`),
    saveMapping: (id: string, body: MappingUpdate) => put<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}/mapping`, body),
    editFiles: (id: string, files: FileEdit[]) => put<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}/files`, { files }),
    valueMappings: (id: string) => get<ValueMappings>(`/api/imports/batches/${encodeURIComponent(id)}/value-mappings`),
    saveValueMappings: (id: string, items: { list_code: string; raw: string; option_code: string | null }[]) =>
      put<ValueMappings | void>(`/api/imports/batches/${encodeURIComponent(id)}/value-mappings`, { items }),
    validate: (id: string) => post<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}/validate`),
    rows: (id: string, params: { status?: string; match?: MatchStatus | ""; page?: number; page_size?: number } = {}) =>
      get<ImportRowList>(`/api/imports/batches/${encodeURIComponent(id)}/rows${qs(params)}`),
    errorFileUrl: (id: string) => `/api/imports/batches/${encodeURIComponent(id)}/error-file`,
    match: (id: string) => post<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}/match`),
    updateRow: (id: string, rowId: string, body: { entity_id?: string | null; action?: RowAction }) =>
      put<ImportRow>(`/api/imports/batches/${encodeURIComponent(id)}/rows/${encodeURIComponent(rowId)}`, body),
    review: (id: string) => post<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}/review`),
    conflicts: (id: string, status?: string) =>
      get<ImportConflictList>(`/api/imports/batches/${encodeURIComponent(id)}/conflicts${qs({ status })}`),
    decideConflicts: (conflictIds: string[], decision: "accept" | "reject" | "edit", value?: unknown) =>
      post<{ decided?: number; [k: string]: unknown }>("/api/imports/conflicts/decide", {
        conflict_ids: conflictIds,
        decision,
        ...(decision === "edit" ? { value } : {}),
      }),
    commit: (id: string) => post<ImportBatch>(`/api/imports/batches/${encodeURIComponent(id)}/commit`),
    rollback: (id: string) => post<ImportRollbackResult>(`/api/imports/batches/${encodeURIComponent(id)}/rollback`),
    report: (id: string) => get<Record<string, unknown>>(`/api/imports/batches/${encodeURIComponent(id)}/report`),
  },

  // ---- Keyed worksheets (IMP-12) ----
  worksheets: {
    create: (body: WorksheetCreate) => post<WorksheetCreated>("/api/worksheets", body),
    list: () => get<Worksheet[]>("/api/worksheets"),
    fileUrl: (id: string) => `/api/worksheets/${encodeURIComponent(id)}/file`,
  },

  // ---- Bulk actions (DM-04) ----
  bulk: {
    preview: (body: BulkPreviewRequest) => post<BulkAction>("/api/bulk/preview", body),
    run: (id: string) => post<BulkAction>(`/api/bulk/${encodeURIComponent(id)}/run`),
    // "history": accepts either a bare array or {rows, total}.
    list: (page = 1) => get<BulkAction[] | { rows: BulkAction[]; total: number }>(`/api/bulk${qs({ page })}`),
    detail: (id: string) => get<BulkAction>(`/api/bulk/${encodeURIComponent(id)}`),
    rollback: (id: string) => post<BulkAction | { restored?: number; [k: string]: unknown }>(`/api/bulk/${encodeURIComponent(id)}/rollback`),
  },

  // ---- Workflows (DM-07, DM-12) ----
  workflows: {
    list: () => get<WorkflowDefinition[]>("/api/workflows"),
    save: (code: string, body: Omit<WorkflowDefinition, "code">) =>
      put<WorkflowDefinition>(`/api/workflows/${encodeURIComponent(code)}`, body),
    inbox: (scope: WorkflowScope, overdue?: boolean) =>
      get<WorkflowInbox>(`/api/workflows/inbox${qs({ scope, overdue: overdue ? true : undefined })}`),
    manager: () => get<WorkflowManager>("/api/workflows/manager"),
    advance: (itemId: string, comment?: string) =>
      post<WorkflowItem>(`/api/workflows/items/${encodeURIComponent(itemId)}/advance`, { comment: comment || undefined }),
    reject: (itemId: string, body: WorkflowReject) =>
      post<WorkflowItem>(`/api/workflows/items/${encodeURIComponent(itemId)}/reject`, body),
    assign: (itemId: string, email: string) =>
      post<WorkflowItem>(`/api/workflows/items/${encodeURIComponent(itemId)}/assign`, { email }),
    cancel: (itemId: string) => post<WorkflowItem>(`/api/workflows/items/${encodeURIComponent(itemId)}/cancel`),
    start: (workflowCode: string, entityIds: string[]) =>
      post<{ started?: number; items?: WorkflowItem[]; [k: string]: unknown }>("/api/workflows/start", {
        workflow_code: workflowCode,
        entity_ids: entityIds,
      }),
    // "open items for a product": accepts a bare array or {rows}.
    forProduct: (entityId: string) =>
      get<WorkflowItem[] | { rows: WorkflowItem[] }>(`/api/products/${encodeURIComponent(entityId)}/workflow`),
  },

  carryover: {
    info: (entityId: string) => get<CarryoverInfo>(`/api/products/${encodeURIComponent(entityId)}/carryover`),
    run: (entityId: string, fromEntityId: string, attributeCodes?: string[]) =>
      post<{ drafts: number }>(`/api/products/${encodeURIComponent(entityId)}/carryover`, {
        from_entity_id: fromEntityId,
        attribute_codes: attributeCodes,
      }),
  },

  // ---- Comments and notifications (DM-09) ----
  comments: {
    list: (entityId: string) => get<Comment[]>(`/api/products/${encodeURIComponent(entityId)}/comments`),
    create: (entityId: string, body: string, attributeCode?: string | null) =>
      post<Comment>(`/api/products/${encodeURIComponent(entityId)}/comments`, {
        body,
        attribute_code: attributeCode || undefined,
      }),
    resolve: (commentId: string) => post<Comment | void>(`/api/comments/${encodeURIComponent(commentId)}/resolve`),
  },

  notifications: {
    list: (unread?: boolean) => get<NotificationList>(`/api/notifications${qs({ unread: unread ? true : undefined })}`),
    markRead: (ids?: string[]) => post<{ read?: number; [k: string]: unknown }>("/api/notifications/read", ids ? { ids } : {}),
  },

  // ---- Compare (DM-06) ----
  compare: {
    get: (a: string, b: string, channel?: string) => get<CompareResult>(`/api/products/compare${qs({ a, b, channel })}`),
    copyFrom: (toEntityId: string, fromEntityId: string, attributeCodes: string[], channelCode?: string | null) =>
      post<ValueEditResponse>(`/api/products/${encodeURIComponent(toEntityId)}/copy-from`, {
        from_entity_id: fromEntityId,
        attribute_codes: attributeCodes,
        channel_code: channelCode || undefined,
      }),
  },

  // ---- Rules (GOV-01, GOV-06) ----
  rules: {
    list: () => get<Rule[]>("/api/rules"),
    create: (body: RuleInput) => post<Rule>("/api/rules", body),
    update: (id: string, body: Partial<Rule>) => put<Rule>(`/api/rules/${encodeURIComponent(id)}`, body),
    remove: (id: string) => del<void>(`/api/rules/${encodeURIComponent(id)}`),
    preview: (id: string) => post<RulePreview>(`/api/rules/${encodeURIComponent(id)}/preview`),
    activate: (id: string, force?: { force: true; reason: string }) =>
      post<Rule>(`/api/rules/${encodeURIComponent(id)}/activate`, force ?? {}),
    run: (id: string) => post<{ affected: number; report: Record<string, unknown> }>(`/api/rules/${encodeURIComponent(id)}/run`),
    runs: (ruleId?: string) => get<RuleRun[] | { rows: RuleRun[]; total?: number }>(`/api/rules/runs${qs({ rule_id: ruleId })}`),
  },
};

// =================================================================================
// Phase 3
// =================================================================================

// ---- Target schemas, mappings, dry runs, publishes, health, delta, schedule (EXP-01, EXP-02, EXP-04, EXP-05, EXP-06) ----
export const channelApi = {
  schema: (code: string) => get<TargetSchema>(`/api/channels/${encodeURIComponent(code)}/schema`),
  refreshSchema: (code: string, file?: File | null, productType?: string) => {
    const fd = new FormData();
    if (file) fd.append("file", file);
    return request<{ schema: TargetSchema; diff: SchemaDiff }>(
      `/api/channels/${encodeURIComponent(code)}/schema/refresh${qs({ product_type: productType })}`,
      { method: "POST", body: fd },
    );
  },
  schemaDiff: (code: string) => get<SchemaDiff>(`/api/channels/${encodeURIComponent(code)}/schema/diff`),
  mapping: (code: string) => get<ChannelMapping>(`/api/channels/${encodeURIComponent(code)}/mapping`),
  saveMapping: (code: string, body: ChannelMappingUpdate) =>
    put<ChannelMapping>(`/api/channels/${encodeURIComponent(code)}/mapping`, body),
  dryRun: (code: string, body: PublishRequest) => post<Publish>(`/api/channels/${encodeURIComponent(code)}/dry-run`, body),
  publish: (code: string, body: PublishRequest) => post<Publish>(`/api/channels/${encodeURIComponent(code)}/publish`, body),
  health: (code: string) => get<ChannelHealth>(`/api/channels/${encodeURIComponent(code)}/health`),
  delta: (code: string, viewId?: string) => get<ChannelDelta>(`/api/channels/${encodeURIComponent(code)}/delta${qs({ view_id: viewId })}`),
  schedule: (code: string) => get<ExportSchedule>(`/api/channels/${encodeURIComponent(code)}/schedule`),
  saveSchedule: (code: string, body: ExportSchedule) => put<ExportSchedule>(`/api/channels/${encodeURIComponent(code)}/schedule`, body),
  runNow: (code: string) => post<RunNowResult>(`/api/channels/${encodeURIComponent(code)}/schedule/run-now`),

  // ---- Phase 5: transport and feed templates (EXP-09, EXP-10, EXP-11) ----
  transport: (code: string) => get<ChannelTransport>(`/api/channels/${encodeURIComponent(code)}/transport`),
  // Needs edit_profile (RBAC-03); bumps the channel version.
  saveTransport: (code: string, body: ChannelTransport) =>
    put<ChannelTransport>(`/api/channels/${encodeURIComponent(code)}/transport`, body),
  uploadFeedTemplate: (code: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<FeedTemplateUpload>(`/api/channels/${encodeURIComponent(code)}/feed-template`, { method: "POST", body: fd });
  },
  feedTemplateUrl: (code: string) => `/api/channels/${encodeURIComponent(code)}/feed-template`,
};

export const publishApi = {
  list: (params: { channel?: string; kind?: string; page?: number } = {}) => get<PublishList>(`/api/publishes${qs(params)}`),
  detail: (id: string) => get<PublishDetail>(`/api/publishes/${encodeURIComponent(id)}`),
  items: (id: string, params: { status?: string; page?: number } = {}) =>
    get<PublishItemList>(`/api/publishes/${encodeURIComponent(id)}/items${qs(params)}`),
  fileUrl: (id: string, name: string) => `/api/publishes/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`,
  feedback: (id: string, file?: File | null) => {
    const fd = new FormData();
    if (file) fd.append("file", file);
    return request<FeedbackResult>(`/api/publishes/${encodeURIComponent(id)}/feedback`, { method: "POST", body: fd });
  },
  // Phase 5 (EXP-09): (re)sends the publish's files through the channel transport (SFTP or email).
  // 409 when the transport is download or not configured; callers check ApiError.status.
  deliver: (id: string) => post<DeliveryResult>(`/api/publishes/${encodeURIComponent(id)}/deliver`),
};

// ---- Eligibility (EXP-12) ----
export const eligibilityApi = {
  get: (entityId: string) => get<Eligibility>(`/api/products/${encodeURIComponent(entityId)}/eligibility`),
  override: (entityId: string, body: { channel_code: string; reason: string; expires_at?: string }) =>
    post<EligibilityOverride>(`/api/products/${encodeURIComponent(entityId)}/eligibility-override`, body),
  removeOverride: (id: string) => del<void>(`/api/eligibility-overrides/${encodeURIComponent(id)}`),
};

// =================================================================================
// Phase 4
// =================================================================================

// ---- Brand voice, prompt templates, Ask AI, review, bulk runs, metrics, evaluation (AI-01 to AI-07) ----
export const aiApi = {
  brandVoices: () => get<BrandVoice[]>("/api/ai/brand-voices"),
  brandVoice: (brandCode: string) => get<BrandVoice>(`/api/ai/brand-voices/${encodeURIComponent(brandCode)}`),
  saveBrandVoice: (brandCode: string, body: Omit<BrandVoice, "version" | "updated_at" | "updated_by">) =>
    put<BrandVoice>(`/api/ai/brand-voices/${encodeURIComponent(brandCode)}`, body),

  templates: (params: { task_type?: string; target?: string; status?: string } = {}) =>
    get<PromptTemplate[]>(`/api/ai/templates${qs(params)}`),
  createTemplate: (body: PromptTemplateInput) => post<PromptTemplate>("/api/ai/templates", body),
  template: (code: string) => get<PromptTemplateDetail>(`/api/ai/templates/${encodeURIComponent(code)}`),
  updateTemplate: (code: string, body: Partial<PromptTemplateInput>) =>
    put<PromptTemplate>(`/api/ai/templates/${encodeURIComponent(code)}`, body),
  // 409 when the eval gate blocks the activation (callers check ApiError.status).
  activateTemplate: (code: string) => post<PromptTemplate>(`/api/ai/templates/${encodeURIComponent(code)}/activate`),
  previewTemplate: (code: string, body: { entity_id: string; channel_code?: string; text?: string }) =>
    post<TemplatePreview>(`/api/ai/templates/${encodeURIComponent(code)}/preview`, body),

  // Templates applicable to one product. The contract says "grouped by task type"; the client accepts a flat
  // array, a {task_type: PromptTemplate[]} map or {templates: PromptTemplate[]} and flattens (see hooks.ts).
  productTemplates: (entityId: string, attribute?: string) =>
    get<PromptTemplate[] | Record<string, PromptTemplate[]> | { templates: PromptTemplate[] }>(
      `/api/products/${encodeURIComponent(entityId)}/ai/templates${qs({ attribute })}`,
    ),
  // 409 when the AI endpoint is not configured (AI-01).
  ask: (body: AiAskRequest) => post<{ outputs: AiOutput[] }>("/api/ai/ask", body),
  outputs: (params: { entity_id?: string; run_id?: string; status?: string; template_code?: string; page?: number } = {}) =>
    get<AiOutputList>(`/api/ai/outputs${qs(params)}`),
  accept: (id: string, value?: unknown) =>
    post<AiOutput>(`/api/ai/outputs/${encodeURIComponent(id)}/accept`, value === undefined ? {} : { value }),
  reject: (id: string, reason: string) => post<AiOutput>(`/api/ai/outputs/${encodeURIComponent(id)}/reject`, { reason }),
  regenerate: (id: string, note?: string) =>
    post<AiOutput>(`/api/ai/outputs/${encodeURIComponent(id)}/regenerate`, { note: note || undefined }),

  createRun: (body: AiRunCreate) => post<AiRunDetail>("/api/ai/runs", body),
  runs: (params: { status?: string; page?: number } = {}) => get<AiRunList>(`/api/ai/runs${qs(params)}`),
  run: (id: string) => get<AiRunDetail>(`/api/ai/runs/${encodeURIComponent(id)}`),
  approveSamples: (id: string) => post<AiRun>(`/api/ai/runs/${encodeURIComponent(id)}/approve-samples`),
  cancelRun: (id: string) => post<AiRun>(`/api/ai/runs/${encodeURIComponent(id)}/cancel`),
  acceptAll: (id: string) => post<{ accepted: number; skipped: number }>(`/api/ai/runs/${encodeURIComponent(id)}/accept-all`),

  metrics: (templateCode?: string) => get<AiMetrics[]>(`/api/ai/metrics${qs({ template_code: templateCode })}`),
  evalCases: (attribute?: string) => get<EvalCase[]>(`/api/ai/eval/cases${qs({ attribute })}`),
  buildEvalCases: (attributeCode: string, limit = 50) =>
    post<{ created: number; total: number }>("/api/ai/eval/cases/build", { attribute_code: attributeCode, limit }),
  deleteEvalCase: (id: string) => del<void>(`/api/ai/eval/cases/${encodeURIComponent(id)}`),
  evalRuns: (templateCode?: string) => get<EvalRun[]>(`/api/ai/eval/runs${qs({ template_code: templateCode })}`),
  runEval: (templateCode: string) => post<EvalRun>("/api/ai/eval/runs", { template_code: templateCode }),
};

// ---- Quality score (GOV-03) ----
export const qualityApi = {
  settings: () => get<QualitySettings>("/api/quality/settings"),
  saveSettings: (body: QualitySettings) => put<QualitySettings>("/api/quality/settings", body),
  recompute: (entityIds?: string[]) => post<{ computed: number }>("/api/quality/recompute", entityIds ? { entity_ids: entityIds } : {}),
  product: (entityId: string) => get<{ scores: QualityScore[] }>(`/api/products/${encodeURIComponent(entityId)}/quality`),
  dashboard: (by: QualityDashboardBy) => get<{ rows: QualityDashboardRow[] }>(`/api/quality/dashboard${qs({ by })}`),
};

// =================================================================================
// Phase 6 (docs/api-contract-phase6.md)
// =================================================================================

// ---- Relationships (DM-13) ----
export const relationshipApi = {
  types: (includeDisabled = false) =>
    get<RelationshipType[]>(`/api/relationship-types${qs({ include_disabled: includeDisabled ? true : undefined })}`),
  saveType: (code: string, body: Partial<Omit<RelationshipType, "code">>) =>
    put<RelationshipType>(`/api/relationship-types/${encodeURIComponent(code)}`, body),
  list: (entityId: string) => get<{ rows: Relationship[] }>(`/api/products/${encodeURIComponent(entityId)}/relationships`),
  add: (entityId: string, body: RelationshipAddRequest) =>
    post<RelationshipAddResult>(`/api/products/${encodeURIComponent(entityId)}/relationships`, body),
  remove: (relationshipId: string) => del<{ deleted: number }>(`/api/relationships/${encodeURIComponent(relationshipId)}`),
};

// ---- Change sets (GOV-02) ----
export const changeSetApi = {
  list: (params: { kind?: string; entity_id?: string; page?: number; page_size?: number } = {}) =>
    get<ChangeSetList>(`/api/change-sets${qs(params)}`),
  get: (id: string) => get<ChangeSet>(`/api/change-sets/${encodeURIComponent(id)}`),
  rollback: (id: string) => post<RollbackResult>(`/api/change-sets/${encodeURIComponent(id)}/rollback`),
};

// ---- Per-user settings: digest frequency (DM-07, DM-09) ----
export const settingsApi = {
  get: () => get<MeSettings>("/api/me/settings"),
  save: (body: { digest_frequency: MeSettings["digest_frequency"] }) => put<MeSettings>("/api/me/settings", body),
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}
