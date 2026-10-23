// Client-side validation against the attribute definition (DM-03). The server validates again.

import type { AttributeDefinition, OptionList } from "../api/types";

export interface ParseResult {
  ok: boolean;
  value: unknown;
  error?: string;
}

const TRUE_WORDS = new Set(["true", "yes", "y", "1", "x"]);
const FALSE_WORDS = new Set(["false", "no", "n", "0", ""]);

/**
 * Convert text typed or pasted by the user into the typed JSON value the API expects,
 * validating against the definition. Empty text means clear (null).
 */
export function parseInput(text: string, attr: AttributeDefinition, optionList?: OptionList): ParseResult {
  const raw = text.trim();
  const v = attr.validation ?? {};
  switch (attr.data_type) {
    case "boolean": {
      const l = raw.toLowerCase();
      if (l === "") return { ok: true, value: null };
      if (TRUE_WORDS.has(l)) return { ok: true, value: true };
      if (FALSE_WORDS.has(l)) return { ok: true, value: false };
      return { ok: false, value: null, error: "Enter Yes or No" };
    }
    case "number": {
      if (raw === "") return { ok: true, value: null };
      const n = Number(raw.replace(/,/g, ""));
      if (!Number.isFinite(n)) return { ok: false, value: null, error: "Enter a number" };
      if (v.min !== undefined && n < v.min) return { ok: false, value: n, error: `Minimum is ${v.min}` };
      if (v.max !== undefined && n > v.max) return { ok: false, value: n, error: `Maximum is ${v.max}` };
      return { ok: true, value: n };
    }
    case "date": {
      if (raw === "") return { ok: true, value: null };
      const d = new Date(raw);
      if (Number.isNaN(d.getTime())) return { ok: false, value: null, error: "Enter a date (YYYY-MM-DD)" };
      return { ok: true, value: d.toISOString().slice(0, 10) };
    }
    case "single_select": {
      if (raw === "") return { ok: true, value: null };
      const code = matchOption(raw, optionList);
      if (code === null) return { ok: false, value: raw, error: `"${raw}" is not in the option list` };
      return { ok: true, value: code };
    }
    case "multi_select": {
      if (raw === "") return { ok: true, value: null };
      const parts = raw.split(/[,;|]/).map((p) => p.trim()).filter(Boolean);
      const codes: string[] = [];
      for (const p of parts) {
        const code = matchOption(p, optionList);
        if (code === null) return { ok: false, value: parts, error: `"${p}" is not in the option list` };
        codes.push(code);
      }
      return { ok: true, value: codes };
    }
    case "text":
    case "rich_text": {
      if (raw === "") return { ok: true, value: null };
      if (v.min_length !== undefined && raw.length < v.min_length) {
        return { ok: false, value: raw, error: `At least ${v.min_length} characters` };
      }
      if (v.max_length !== undefined && raw.length > v.max_length) {
        return { ok: false, value: raw, error: `At most ${v.max_length} characters (now ${raw.length})` };
      }
      if (v.regex) {
        try {
          if (!new RegExp(v.regex).test(raw)) return { ok: false, value: raw, error: `Must match ${v.regex}` };
        } catch {
          // ignore a malformed regex in metadata; the server will validate
        }
      }
      return { ok: true, value: raw };
    }
    default:
      // asset_ref, product_ref, reference_entity: accept the identifier as typed.
      return { ok: true, value: raw === "" ? null : raw };
  }
}

function matchOption(text: string, list?: OptionList): string | null {
  if (!list) return text;
  const t = text.toLowerCase();
  const byCode = list.values.find((o) => o.code.toLowerCase() === t);
  if (byCode) return byCode.code;
  const byLabel = list.values.find((o) => o.label.toLowerCase() === t);
  if (byLabel) return byLabel.code;
  return null;
}

/** Validate an already typed value (used by editors that produce typed values directly). */
export function validateTyped(value: unknown, attr: AttributeDefinition): string | null {
  if (value === null || value === undefined || value === "") return null;
  const v = attr.validation ?? {};
  if (attr.data_type === "number" && typeof value === "number") {
    if (v.min !== undefined && value < v.min) return `Minimum is ${v.min}`;
    if (v.max !== undefined && value > v.max) return `Maximum is ${v.max}`;
  }
  if ((attr.data_type === "text" || attr.data_type === "rich_text") && typeof value === "string") {
    if (v.min_length !== undefined && value.length < v.min_length) return `At least ${v.min_length} characters`;
    if (v.max_length !== undefined && value.length > v.max_length) return `At most ${v.max_length} characters`;
    if (v.regex) {
      try {
        if (!new RegExp(v.regex).test(value)) return `Must match ${v.regex}`;
      } catch {
        return null;
      }
    }
  }
  return null;
}
