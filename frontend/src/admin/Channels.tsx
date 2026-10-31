// EXP-01, EXP-02, EXP-05, EXP-06, EXP-13, IMG-07: Channels. Label, enabled, protected fields list, requirement set
// (PUT /api/metadata/channels/{code}); each row expands into the ChannelEditor (schema, mapping, image profile,
// schedule, health).

import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useChannels } from "../api/hooks";
import type { Channel } from "../api/types";
import { Badge, Dialog, Empty, ErrorBox, Spinner, useToast } from "../components/Common";
import { ChannelEditor } from "./ChannelEditor";
import { EligibilityDialog, RecomputeButton } from "./Eligibility";

export function ChannelsTab() {
  const channels = useChannels();
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<Channel | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [eligibilityFor, setEligibilityFor] = useState<Channel | null>(null);
  const [needsApply, setNeedsApply] = useState(false);
  const options = useQuery({ queryKey: ["metadata", "eligibility-options"], queryFn: api.metadata.eligibilityOptions });
  const scopeLabel = (code: string) => options.data?.brand_scopes.find((s) => s.code === code)?.label ?? code;

  const save = useMutation({
    mutationFn: (c: Channel) => api.metadata.saveChannel(c.code, c),
    onSuccess: () => {
      toast("Channel saved", "ok");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["metadata"] });
    },
    onError: (e) => toast(`Save failed: ${(e as Error).message}`, "error"),
  });

  if (channels.isLoading) return <Spinner label="Loading channels" />;
  if (channels.isError) return <ErrorBox error={channels.error} title="Could not load channels" />;

  return (
    <div>
      <div className="row mb8" style={{ justifyContent: "space-between" }}>
        <span className="muted small">Protected fields are never proposed in an update package (EXP-13), for example Layer's cross-sell metafields.</span>
        <button
          className="primary"
          onClick={() =>
            setEditing({ code: "", label: "", adapter: "", kind: "dtc", enabled: false, requirement_set_code: null, protected_fields: [], config: {}, version: 0 })
          }
        >
          Add channel
        </button>
      </div>
      {needsApply && (
        <div className="panel mb8">
          <div className="panel-body row" style={{ justifyContent: "space-between" }}>
            <span className="small">Eligibility changed. Apply it to the products already loaded to update channel readiness.</span>
            <RecomputeButton primary onDone={() => setNeedsApply(false)} />
          </div>
        </div>
      )}
      {channels.data!.length === 0 ? (
        <Empty title="No channels">Add Shopify first; retailer and marketplace channels follow.</Empty>
      ) : (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Code</th>
                <th>Label</th>
                <th>Kind</th>
                <th>Adapter</th>
                <th>Enabled</th>
                <th>Requirement set</th>
                <th>Eligible brands</th>
                <th>Protected fields</th>
                <th>Version</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {channels.data!.map((c) => (
                <Fragment key={c.code}>
                <tr className={expanded === c.code ? "expanded" : ""}>
                  <td className="mono">
                    <button className="link" onClick={() => setExpanded(expanded === c.code ? null : c.code)} title="Open the schema, mapping, image profile, schedule and health tabs">
                      {expanded === c.code ? "v" : ">"} {c.code}
                    </button>
                  </td>
                  <td>{c.label}</td>
                  <td>{c.kind}</td>
                  <td className="mono">{c.adapter}</td>
                  <td>{c.enabled ? <Badge color="green">enabled</Badge> : <Badge>disabled</Badge>}</td>
                  <td className="mono">{c.requirement_set_code ?? <span className="faint">none</span>}</td>
                  <td>
                    <div className="chips">
                      {(c.eligibility?.brand_scopes ?? []).map((code) => (
                        <span key={code} className="badge">
                          {scopeLabel(code)}
                        </span>
                      ))}
                      {(c.eligibility?.brand_scopes ?? []).length === 0 && <span className="faint">every brand</span>}
                    </div>
                  </td>
                  <td>
                    <div className="chips">
                      {c.protected_fields.map((f) => (
                        <span key={f} className="badge amber">
                          {f}
                        </span>
                      ))}
                      {c.protected_fields.length === 0 && <span className="faint">none</span>}
                    </div>
                  </td>
                  <td className="num">{c.version}</td>
                  <td className="nowrap">
                    <button className="small" onClick={() => setExpanded(expanded === c.code ? null : c.code)}>
                      {expanded === c.code ? "Close" : "Configure"}
                    </button>{" "}
                    <button className="small" onClick={() => setEditing(c)}>
                      Edit
                    </button>{" "}
                    <button className="small" onClick={() => setEligibilityFor(c)} title="Which brands and products this channel admits">
                      Eligibility
                    </button>
                  </td>
                </tr>
                {expanded === c.code && (
                  <tr className="expanded-row">
                    <td colSpan={10}>
                      <ChannelEditor channel={c} />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {eligibilityFor && (
        <EligibilityDialog
          channel={eligibilityFor}
          onClose={() => setEligibilityFor(null)}
          onSaved={() => {
            setEligibilityFor(null);
            setNeedsApply(true);
          }}
        />
      )}
      {editing && (
        <ChannelDialog
          initial={editing}
          isNew={!channels.data!.some((c) => c.code === editing.code)}
          busy={save.isPending}
          error={save.error}
          onClose={() => setEditing(null)}
          onSave={(c) => save.mutate(c)}
        />
      )}
    </div>
  );
}

function ChannelDialog({
  initial,
  isNew,
  busy,
  error,
  onClose,
  onSave,
}: {
  initial: Channel;
  isNew: boolean;
  busy: boolean;
  error: unknown;
  onClose: () => void;
  onSave: (c: Channel) => void;
}) {
  const [c, setC] = useState<Channel>(initial);
  const [protectedText, setProtectedText] = useState(initial.protected_fields.join("\n"));
  const [configText, setConfigText] = useState(JSON.stringify(initial.config ?? {}, null, 2));
  const [configError, setConfigError] = useState<string | null>(null);

  const submit = () => {
    let config: Record<string, unknown> = {};
    try {
      config = configText.trim() ? JSON.parse(configText) : {};
      setConfigError(null);
    } catch {
      setConfigError("Config must be valid JSON");
      return;
    }
    onSave({
      ...c,
      protected_fields: protectedText.split(/\r?\n|,/).map((s) => s.trim()).filter(Boolean),
      config,
    });
  };

  return (
    <Dialog
      title={isNew ? "Add channel" : `Edit channel ${c.code}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="primary" onClick={submit} disabled={busy || !c.code || !c.label}>
            {busy ? "Saving" : "Save"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <label className="field">
          Code
          <input className="mono" value={c.code} disabled={!isNew} onChange={(e) => setC({ ...c, code: e.target.value })} />
        </label>
        <label className="field">
          Label
          <input value={c.label} onChange={(e) => setC({ ...c, label: e.target.value })} />
        </label>
        <label className="field">
          Kind
          <select value={c.kind} onChange={(e) => setC({ ...c, kind: e.target.value as Channel["kind"] })}>
            <option value="dtc">dtc</option>
            <option value="marketplace">marketplace</option>
            <option value="retailer">retailer</option>
          </select>
        </label>
        <label className="field">
          Adapter
          <input className="mono" value={c.adapter} onChange={(e) => setC({ ...c, adapter: e.target.value })} placeholder="shopify, walmart, feed" />
        </label>
        <label className="field">
          Requirement set code
          <input className="mono" value={c.requirement_set_code ?? ""} onChange={(e) => setC({ ...c, requirement_set_code: e.target.value || null })} />
        </label>
        <label className="inline" style={{ alignSelf: "end" }}>
          <input type="checkbox" checked={c.enabled} onChange={(e) => setC({ ...c, enabled: e.target.checked })} /> Enabled
        </label>
        <label className="field" style={{ gridColumn: "1 / -1" }}>
          Protected fields (one per line)
          <textarea className="mono" value={protectedText} onChange={(e) => setProtectedText(e.target.value)} />
        </label>
        <label className="field" style={{ gridColumn: "1 / -1" }}>
          Config JSON (no secrets here; credentials live in app secret resources, GOV-05)
          <textarea className={configError ? "mono invalid" : "mono"} value={configText} onChange={(e) => setConfigText(e.target.value)} />
          {configError && <span className="field-error">{configError}</span>}
        </label>
      </div>
      {error ? <ErrorBox error={error} title="Save failed" /> : null}
    </Dialog>
  );
}
