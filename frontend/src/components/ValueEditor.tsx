// Editors by attribute data_type (DM-03, DM-05). Used by both the grid and the detail form.
// Metadata-driven: nothing here knows any specific attribute code.

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { AttributeDefinition, OptionList } from "../api/types";
import { parseInput, validateTyped } from "../lib/validation";
import { clipboardValue } from "../lib/format";

export interface EditorProps {
  attr: AttributeDefinition;
  optionList?: OptionList;
  value: unknown;
  /** Called with the typed value when the user commits (Enter, blur, select change). */
  onCommit: (value: unknown) => void;
  onCancel?: () => void;
  /** Grid mode: Tab/Enter/arrows commit and move; the parent handles navigation. */
  onNavigate?: (key: "Tab" | "ShiftTab" | "Enter" | "ShiftEnter" | "ArrowUp" | "ArrowDown") => void;
  autoFocus?: boolean;
  compact?: boolean;
  disabled?: boolean;
  onError?: (msg: string | null) => void;
  /** Grid mode: text the user typed to start the edit replaces the current value. */
  initialText?: string;
}

export function ValueEditor(props: EditorProps) {
  const { attr, optionList, value, onCommit, onCancel, onNavigate, autoFocus, compact, disabled, onError } = props;

  if (attr.data_type === "boolean") {
    return (
      <input
        type="checkbox"
        autoFocus={autoFocus}
        disabled={disabled}
        checked={value === true}
        onChange={(e) => onCommit(e.target.checked)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel?.();
          if (e.key === "Tab" && onNavigate) {
            e.preventDefault();
            onNavigate(e.shiftKey ? "ShiftTab" : "Tab");
          }
          if (e.key === "Enter" && onNavigate) {
            e.preventDefault();
            onNavigate(e.shiftKey ? "ShiftEnter" : "Enter");
          }
        }}
      />
    );
  }

  if (attr.data_type === "single_select") {
    return (
      <select
        autoFocus={autoFocus}
        disabled={disabled}
        value={value === null || value === undefined ? "" : String(value)}
        onChange={(e) => onCommit(e.target.value === "" ? null : e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel?.();
          if (e.key === "Tab" && onNavigate) {
            e.preventDefault();
            onNavigate(e.shiftKey ? "ShiftTab" : "Tab");
          }
          if (e.key === "Enter" && onNavigate) {
            e.preventDefault();
            onNavigate(e.shiftKey ? "ShiftEnter" : "Enter");
          }
        }}
      >
        <option value="">{attr.allows_not_applicable ? "(empty or N/A)" : "(empty)"}</option>
        {(optionList?.values ?? [])
          .slice()
          .sort((a, b) => a.sort_order - b.sort_order)
          .map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        {!optionList && <option value={String(value ?? "")}>{String(value ?? "")}</option>}
      </select>
    );
  }

  if (attr.data_type === "multi_select") {
    return (
      <MultiSelectEditor
        attr={attr}
        optionList={optionList}
        value={Array.isArray(value) ? (value as string[]) : []}
        onCommit={onCommit}
        onCancel={onCancel}
        compact={compact}
        disabled={disabled}
      />
    );
  }

  return (
    <TextEditor
      attr={attr}
      optionList={optionList}
      value={value}
      onCommit={onCommit}
      onCancel={onCancel}
      onNavigate={onNavigate}
      autoFocus={autoFocus}
      compact={compact}
      disabled={disabled}
      onError={onError}
    />
  );
}

function TextEditor({ attr, optionList, value, onCommit, onCancel, onNavigate, autoFocus, compact, disabled, onError, initialText }: EditorProps) {
  const initial =
    initialText !== undefined
      ? initialText
      : attr.data_type === "date" && typeof value === "string"
        ? value.slice(0, 10)
        : clipboardValue(value);
  const [text, setText] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const committed = useRef(false);

  useEffect(() => {
    if (autoFocus && ref.current) {
      ref.current.focus();
      if (ref.current instanceof HTMLInputElement && ref.current.type === "text" && initialText === undefined) {
        ref.current.select();
      }
    }
  }, [autoFocus, initialText]);

  const tryCommit = (): boolean => {
    const r = parseInput(text, attr, optionList);
    if (!r.ok) {
      setError(r.error ?? "Invalid value");
      onError?.(r.error ?? "Invalid value");
      return false;
    }
    const typedErr = validateTyped(r.value, attr);
    if (typedErr) {
      setError(typedErr);
      onError?.(typedErr);
      return false;
    }
    setError(null);
    onError?.(null);
    committed.current = true;
    onCommit(r.value);
    return true;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      committed.current = true;
      onCancel?.();
      return;
    }
    const multiline = attr.data_type === "rich_text" && !compact;
    if (e.key === "Enter" && !(multiline && !e.ctrlKey && !e.metaKey)) {
      e.preventDefault();
      if (tryCommit()) onNavigate?.(e.shiftKey ? "ShiftEnter" : "Enter");
      return;
    }
    if (e.key === "Tab" && onNavigate) {
      e.preventDefault();
      if (tryCommit()) onNavigate(e.shiftKey ? "ShiftTab" : "Tab");
      return;
    }
    if ((e.key === "ArrowUp" || e.key === "ArrowDown") && onNavigate && !multiline) {
      e.preventDefault();
      if (tryCommit()) onNavigate(e.key);
    }
  };

  const onBlur = () => {
    if (committed.current) return;
    tryCommit();
  };

  const inputType = attr.data_type === "date" ? "date" : attr.data_type === "number" ? "text" : "text";
  const placeholder = attr.example_value ? `e.g. ${attr.example_value}` : attr.unit ? `in ${attr.unit}` : undefined;

  if (attr.data_type === "rich_text" && !compact) {
    return (
      <>
        <textarea
          ref={ref as React.RefObject<HTMLTextAreaElement>}
          className={error ? "invalid" : ""}
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={onBlur}
          placeholder={placeholder}
          maxLength={attr.validation?.max_length}
        />
        {error && <div className="field-error">{error}</div>}
        {attr.validation?.max_length && (
          <div className="help">
            {text.length} / {attr.validation.max_length} characters. Ctrl+Enter to save.
          </div>
        )}
      </>
    );
  }

  return (
    <>
      <input
        ref={ref as React.RefObject<HTMLInputElement>}
        type={inputType}
        inputMode={attr.data_type === "number" ? "decimal" : undefined}
        className={error ? "invalid" : ""}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={onBlur}
        placeholder={placeholder}
      />
      {error && (compact ? <div className="cell-error">{error}</div> : <div className="field-error">{error}</div>)}
    </>
  );
}

function MultiSelectEditor({
  attr,
  optionList,
  value,
  onCommit,
  onCancel,
  compact,
  disabled,
}: {
  attr: AttributeDefinition;
  optionList?: OptionList;
  value: string[];
  onCommit: (v: unknown) => void;
  onCancel?: () => void;
  compact?: boolean;
  disabled?: boolean;
}) {
  const [selected, setSelected] = useState<string[]>(value);
  const options = (optionList?.values ?? []).slice().sort((a, b) => a.sort_order - b.sort_order);
  if (!optionList) {
    // Fall back to a text editor accepting comma-separated codes.
    return (
      <TextEditor attr={attr} value={value.join(", ")} onCommit={onCommit} onCancel={onCancel} compact={compact} disabled={disabled} />
    );
  }
  const toggle = (code: string) =>
    setSelected((s) => (s.includes(code) ? s.filter((c) => c !== code) : [...s, code]));
  return (
    <div
      className="stack"
      style={compact ? { position: "absolute", zIndex: 20, background: "#fff", border: "1px solid var(--border)", padding: 8, minWidth: 220, boxShadow: "var(--shadow)" } : undefined}
      onKeyDown={(e) => {
        if (e.key === "Escape") onCancel?.();
      }}
    >
      <div style={{ maxHeight: 200, overflow: "auto" }}>
        {options.map((o) => (
          <label key={o.code} className="inline" style={{ display: "flex" }}>
            <input type="checkbox" checked={selected.includes(o.code)} onChange={() => toggle(o.code)} disabled={disabled} />
            {o.label}
          </label>
        ))}
        {options.length === 0 && <div className="help">Option list {optionList.code} has no values yet.</div>}
      </div>
      <div className="row">
        <button className="primary small" onClick={() => onCommit(selected.length ? selected : null)} disabled={disabled}>
          Apply
        </button>
        {onCancel && (
          <button className="small" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
