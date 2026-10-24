// DM-02: Saved views. List, save current, update, set default, share, duplicate, delete.
// Only the creator edits a shared view; others may duplicate it.

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useMe } from "../api/hooks";
import { Dialog, ErrorBox, useToast } from "../components/Common";
import type { Level, SavedView, ViewDefinition } from "../api/types";

export function ViewsMenu({
  level,
  current,
  activeView,
  onApply,
  onClear,
}: {
  level: Level;
  current: ViewDefinition;
  activeView: SavedView | null;
  onApply: (v: SavedView) => void;
  onClear: () => void;
}) {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [saveDlg, setSaveDlg] = useState<null | { mode: "new" | "duplicate"; from?: SavedView }>(null);
  const host = useRef<HTMLDivElement>(null);
  const views = useQuery({ queryKey: ["views", level], queryFn: () => api.views.list(level) });

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (host.current && !host.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["views"] });
  const isOwner = (v: SavedView) => !!me.data && v.owner_email === me.data.email;

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<SavedView> }) => api.views.update(id, body),
    onSuccess: () => {
      invalidate();
      toast("View saved", "ok");
    },
    onError: (e) => toast(`Could not update view: ${(e as Error).message}`, "error"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.views.remove(id),
    onSuccess: (_, id) => {
      invalidate();
      if (activeView?.id === id) onClear();
      toast("View deleted", "ok");
    },
    onError: (e) => toast(`Could not delete view: ${(e as Error).message}`, "error"),
  });

  const mine = (views.data ?? []).filter(isOwner);
  const shared = (views.data ?? []).filter((v) => !isOwner(v));

  return (
    <div className="popover-host" ref={host}>
      <button onClick={() => setOpen((o) => !o)}>
        {activeView ? `View: ${activeView.name}` : "Views"} &#9662;
      </button>
      {open && (
        <div className="popover" style={{ minWidth: 360 }}>
          <div className="row" style={{ padding: "4px 4px 8px" }}>
            <button className="small primary" onClick={() => setSaveDlg({ mode: "new" })}>
              Save current as new view
            </button>
            {activeView && isOwner(activeView) && (
              <button
                className="small"
                onClick={() => update.mutate({ id: activeView.id, body: { definition: current, level } })}
              >
                Update "{activeView.name}"
              </button>
            )}
            {activeView && (
              <button className="small link" onClick={onClear}>
                Clear view
              </button>
            )}
          </div>
          {views.isError && <ErrorBox error={views.error} title="Could not load views" />}
          <h4>My views</h4>
          {mine.length === 0 && <div className="muted small" style={{ padding: 4 }}>No saved views yet. Set filters and columns, then save.</div>}
          {mine.map((v) => (
            <ViewRow
              key={v.id}
              v={v}
              owner
              active={activeView?.id === v.id}
              onApply={() => {
                onApply(v);
                setOpen(false);
              }}
              onDefault={() => update.mutate({ id: v.id, body: { is_default: !v.is_default } })}
              onShare={(s) => update.mutate({ id: v.id, body: { shared_with: s } })}
              onDuplicate={() => setSaveDlg({ mode: "duplicate", from: v })}
              onDelete={() => {
                if (window.confirm(`Delete view "${v.name}"?`)) remove.mutate(v.id);
              }}
              roles={me.data?.roles ?? []}
            />
          ))}
          <h4>Shared with me</h4>
          {shared.length === 0 && <div className="muted small" style={{ padding: 4 }}>No one has shared a view with you.</div>}
          {shared.map((v) => (
            <ViewRow
              key={v.id}
              v={v}
              owner={false}
              active={activeView?.id === v.id}
              onApply={() => {
                onApply(v);
                setOpen(false);
              }}
              onDefault={() => update.mutate({ id: v.id, body: { is_default: !v.is_default } })}
              onDuplicate={() => setSaveDlg({ mode: "duplicate", from: v })}
              roles={me.data?.roles ?? []}
            />
          ))}
        </div>
      )}
      {saveDlg && (
        <SaveViewDialog
          level={level}
          definition={saveDlg.from ? saveDlg.from.definition : current}
          initialName={saveDlg.from ? `${saveDlg.from.name} (copy)` : ""}
          onClose={() => setSaveDlg(null)}
          onSaved={(v) => {
            setSaveDlg(null);
            invalidate();
            onApply(v);
          }}
        />
      )}
    </div>
  );
}

function ViewRow({
  v,
  owner,
  active,
  onApply,
  onDefault,
  onShare,
  onDuplicate,
  onDelete,
  roles,
}: {
  v: SavedView;
  owner: boolean;
  active: boolean;
  onApply: () => void;
  onDefault: () => void;
  onShare?: (s: string) => void;
  onDuplicate: () => void;
  onDelete?: () => void;
  roles: string[];
}) {
  return (
    <div className="menu-item" style={active ? { background: "var(--teal-light)" } : undefined}>
      <button className="link" onClick={onApply} style={{ textAlign: "left" }}>
        {v.name}
        {v.is_default && <span className="badge teal" style={{ marginLeft: 6 }}>default</span>}
        {v.shared_with !== "private" && (
          <span className="badge" style={{ marginLeft: 6 }} title={`Shared with ${v.shared_with}`}>
            {v.shared_with === "everyone" ? "everyone" : v.shared_with.replace("role:", "")}
          </span>
        )}
        {!owner && <span className="faint small" style={{ marginLeft: 6 }}>{v.owner_email}</span>}
      </button>
      <div className="actions">
        <button className="small" onClick={onDefault} title={v.is_default ? "Unset as my default" : "Set as my default view"}>
          {v.is_default ? "Unset default" : "Default"}
        </button>
        {owner && onShare && (
          <select
            className="small"
            value={v.shared_with}
            onChange={(e) => onShare(e.target.value)}
            title="Share"
            style={{ padding: "2px 4px", fontSize: 12 }}
          >
            <option value="private">Private</option>
            {roles.map((r) => (
              <option key={r} value={`role:${r}`}>
                Role: {r}
              </option>
            ))}
            <option value="everyone">Everyone</option>
          </select>
        )}
        <button className="small" onClick={onDuplicate}>
          Duplicate
        </button>
        {owner && onDelete && (
          <button className="small danger" onClick={onDelete}>
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

function SaveViewDialog({
  level,
  definition,
  initialName,
  onClose,
  onSaved,
}: {
  level: Level;
  definition: ViewDefinition;
  initialName: string;
  onClose: () => void;
  onSaved: (v: SavedView) => void;
}) {
  const me = useMe();
  const [name, setName] = useState(initialName);
  const [share, setShare] = useState("private");
  const [isDefault, setIsDefault] = useState(false);
  const create = useMutation({
    mutationFn: () => api.views.create({ name: name.trim(), level, shared_with: share, is_default: isDefault, definition }),
    onSuccess: onSaved,
  });
  return (
    <Dialog
      title="Save view"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Saving" : "Save"}
          </button>
        </>
      }
    >
      <div className="stack">
        <label className="field">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="For example: Spring launch, missing copy" />
        </label>
        <label className="field">
          Share with
          <select value={share} onChange={(e) => setShare(e.target.value)}>
            <option value="private">Only me (private)</option>
            {(me.data?.roles ?? []).map((r) => (
              <option key={r} value={`role:${r}`}>
                Role: {r}
              </option>
            ))}
            <option value="everyone">Everyone</option>
          </select>
        </label>
        <label className="inline">
          <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} /> Make this my default view for {level}
        </label>
        <div className="help">
          Saves {definition.filters.length} filter{definition.filters.length === 1 ? "" : "s"}, {definition.columns.length} columns,{" "}
          {definition.sort.length} sort key{definition.sort.length === 1 ? "" : "s"}
          {definition.search ? ` and the search "${definition.search}"` : ""}.
        </div>
        {create.isError && <ErrorBox error={create.error} title="Could not save the view" />}
      </div>
    </Dialog>
  );
}
