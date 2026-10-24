// Shared react-query hooks for metadata and identity. Metadata is cached for the session
// because every screen renders from it (P5).

import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { AttributeDefinition, DataRight, Me } from "./types";

const METADATA_STALE = 5 * 60 * 1000;

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: METADATA_STALE });
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000 });
}

export function useAttributes(params: { level?: string; group?: string } = {}) {
  return useQuery({
    queryKey: ["metadata", "attributes", params],
    queryFn: () => api.metadata.attributes(params),
    staleTime: METADATA_STALE,
  });
}

export function useGroups() {
  return useQuery({ queryKey: ["metadata", "groups"], queryFn: api.metadata.groups, staleTime: METADATA_STALE });
}

export function useOptionLists() {
  return useQuery({
    queryKey: ["metadata", "option-lists"],
    queryFn: api.metadata.optionLists,
    staleTime: METADATA_STALE,
  });
}

export function useFamilies() {
  return useQuery({ queryKey: ["metadata", "families"], queryFn: api.metadata.families, staleTime: METADATA_STALE });
}

export function useChannels() {
  return useQuery({ queryKey: ["metadata", "channels"], queryFn: api.metadata.channels, staleTime: METADATA_STALE });
}

export function useReferenceTypes() {
  return useQuery({
    queryKey: ["metadata", "reference-types"],
    queryFn: api.metadata.referenceTypes,
    staleTime: METADATA_STALE,
  });
}

/** Data right for an attribute's group, from /api/me (RBAC-01). */
export function rightFor(me: Me | undefined, attr: AttributeDefinition | undefined): DataRight {
  if (!me || !attr) return "none";
  // RBAC-01: "*" is the wildcard right for groups not listed explicitly.
  return me.data_rights[attr.group_code] ?? me.data_rights["*"] ?? "none";
}

export function canEdit(me: Me | undefined, attr: AttributeDefinition | undefined): boolean {
  const r = rightFor(me, attr);
  return r === "edit" || r === "approve";
}

export function isAdmin(me: Me | undefined): boolean {
  if (!me) return false;
  return me.roles.some((r) => /admin/i.test(r)) || me.permissions.includes("admin") || me.permissions.includes("admin_metadata");
}

// ---- Phase 2 shared hooks ----
export function useImportSources() {
  return useQuery({ queryKey: ["imports", "sources"], queryFn: api.imports.sources, staleTime: METADATA_STALE });
}

export function useWorkflows() {
  return useQuery({ queryKey: ["workflows", "definitions"], queryFn: api.workflows.list, staleTime: METADATA_STALE });
}

/** Unwraps list endpoints that may return a bare array or {rows}. */
export function rowsOf<T>(data: T[] | { rows: T[] } | undefined | null): T[] {
  if (!data) return [];
  return Array.isArray(data) ? data : (data.rows ?? []);
}

// ---- Phase 3 shared hooks ----
export function useShotTypes() {
  return useQuery({ queryKey: ["metadata", "shot-types"], queryFn: api.metadata.shotTypes, staleTime: METADATA_STALE });
}

/** Channel right from /api/me (RBAC-03). "*" is the wildcard entry for channels not listed explicitly. */
export function channelRight(me: Me | undefined, channelCode: string, right: "run" | "edit_profile"): boolean {
  if (!me) return false;
  if (isAdmin(me)) return true;
  const r = me.channel_rights?.[channelCode] ?? me.channel_rights?.["*"];
  return !!r?.[right];
}
