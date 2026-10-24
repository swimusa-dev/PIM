// Typed fetch helpers for every endpoint in docs/api-contract.md.
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
    queue: (group?: string) => get<ApprovalQueue>(`/api/approvals${qs({ group })}`),
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
  },

  // ---- Images (IMG-05) ----
  images: {
    queue: (kind: ImageQueueKind, channel?: string) => get<ImageQueue>(`/api/images/queue${qs({ kind, channel })}`),
    confirm: (linkId: string, shotType?: string) =>
      post<{ ok?: boolean; [k: string]: unknown }>(`/api/images/links/${encodeURIComponent(linkId)}/confirm`, {
        shot_type: shotType,
      }),
    reject: (linkId: string) =>
      post<{ ok?: boolean; [k: string]: unknown }>(`/api/images/links/${encodeURIComponent(linkId)}/reject`, {}),
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
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}
