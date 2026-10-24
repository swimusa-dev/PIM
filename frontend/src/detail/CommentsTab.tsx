// DM-09: Comments on a product with optional attribute chips, @mention hint in the composer
// (mentions are parsed server-side), resolve per comment and a "show resolved" toggle.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AttributeDefinition } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { formatDate } from "../lib/format";

const MENTION_RE = /(@[\w.+-]+(?:@[\w.-]+)?)/g;

function Body({ text }: { text: string }) {
  const parts = text.split(MENTION_RE);
  return (
    <div className="body">
      {parts.map((p, i) => (p.startsWith("@") ? <span key={i} className="mention">{p}</span> : <span key={i}>{p}</span>))}
    </div>
  );
}

export function CommentsTab({ entityId, attributes, initialAttribute }: { entityId: string; attributes: AttributeDefinition[]; initialAttribute?: string | null }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [showResolved, setShowResolved] = useState(false);
  const [body, setBody] = useState("");
  const [attrCode, setAttrCode] = useState(initialAttribute ?? "");
  const [filterAttr, setFilterAttr] = useState("");

  const q = useQuery({ queryKey: ["product", entityId, "comments"], queryFn: () => api.comments.list(entityId) });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["product", entityId, "comments"] });
  const create = useMutation({
    mutationFn: () => api.comments.create(entityId, body.trim(), attrCode || null),
    onSuccess: () => {
      setBody("");
      toast("Comment posted.", "ok");
      invalidate();
    },
  });
  const resolve = useMutation({
    mutationFn: (id: string) => api.comments.resolve(id),
    onSuccess: () => invalidate(),
    onError: (e) => toast(`Could not resolve: ${(e as Error).message}`, "error"),
  });

  const attrLabel = (code: string) => attributes.find((a) => a.code === code)?.label ?? code;
  const sortedAttrs = useMemo(() => attributes.slice().sort((a, b) => a.label.localeCompare(b.label)), [attributes]);
  const rows = useMemo(() => {
    let r = q.data ?? [];
    if (!showResolved) r = r.filter((c) => !c.resolved);
    if (filterAttr) r = r.filter((c) => c.attribute_code === filterAttr);
    return r.slice().sort((a, b) => b.created_at.localeCompare(a.created_at));
  }, [q.data, showResolved, filterAttr]);
  const typingMention = /(^|\s)@[\w.+-]*$/.test(body);
  const openCount = (q.data ?? []).filter((c) => !c.resolved).length;

  return (
    <div className="stack gap16">
      <div className="panel">
        <div className="panel-header">
          <h3>New comment</h3>
        </div>
        <div className="panel-body stack">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Write a comment. Type @first.last or @email to mention someone."
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && body.trim()) create.mutate();
            }}
          />
          {typingMention && <div className="composer-hint">Mention: finish the @first.last or @email address. The person is notified when you post.</div>}
          <div className="row" style={{ justifyContent: "space-between" }}>
            <label className="inline">
              About attribute
              <select value={attrCode} onChange={(e) => setAttrCode(e.target.value)}>
                <option value="">the whole product</option>
                {sortedAttrs.map((a) => (
                  <option key={a.code} value={a.code}>
                    {a.label}
                  </option>
                ))}
              </select>
            </label>
            <button className="primary" disabled={!body.trim() || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "Posting" : "Post comment"}
            </button>
          </div>
          {create.isError && <ErrorBox error={create.error} title="Could not post the comment" />}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>
            Comments <span className="muted small">{openCount} open</span>
          </h3>
          <div className="row">
            <select value={filterAttr} onChange={(e) => setFilterAttr(e.target.value)}>
              <option value="">All attributes</option>
              {sortedAttrs
                .filter((a) => (q.data ?? []).some((c) => c.attribute_code === a.code))
                .map((a) => (
                  <option key={a.code} value={a.code}>
                    {a.label}
                  </option>
                ))}
            </select>
            <label className="inline">
              <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />
              Show resolved
            </label>
          </div>
        </div>
        {q.isLoading && (
          <div className="panel-body">
            <Spinner />
          </div>
        )}
        {q.isError && (
          <div className="panel-body">
            <ErrorBox error={q.error} title="Could not load comments" />
          </div>
        )}
        {q.data && rows.length === 0 && <Empty title={showResolved ? "No comments" : "No open comments"}>Style-color comments include the style's comments.</Empty>}
        {rows.map((c) => (
          <div key={c.id} className={`comment${c.resolved ? " resolved" : ""}`}>
            <div className="meta">
              <b style={{ color: "var(--text)" }}>{c.author}</b>
              <span>{formatDate(c.created_at)}</span>
              {c.attribute_code && <Badge color="teal">{attrLabel(c.attribute_code)}</Badge>}
              {c.entity_id !== entityId && <Badge title={`Comment on ${c.entity_id}`}>from parent</Badge>}
              {c.mentions.length > 0 && <span className="faint">mentions {c.mentions.join(", ")}</span>}
              {c.resolved ? (
                <Badge color="green">resolved</Badge>
              ) : (
                <button className="link small" disabled={resolve.isPending} onClick={() => resolve.mutate(c.id)}>
                  Resolve
                </button>
              )}
            </div>
            <Body text={c.body} />
          </div>
        ))}
      </div>
    </div>
  );
}
