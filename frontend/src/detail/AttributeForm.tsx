// DM-05, DM-01, DM-06, DM-11, AI-06: Attribute groups as collapsible sections, editors by data_type,
// inherited values read-only with "Edit at <level>" link, reference entity links, and a two-column
// global vs channel compare with "Copy to channel" for channel-scopable attributes. Each row carries
// id="attr-<code>" so the Ask AI panel can focus an attribute that the model needs filled (AI-06).

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import { canEdit, useMe } from "../api/hooks";
import type { AttributeDefinition, EditOutcome, OptionList, ProductGroupSection, ProductRow, ValueCell } from "../api/types";
import { AiBadge, ApprovalBadge, Badge, LockIcon, Provenance } from "../components/Common";
import { ValueEditor } from "../components/ValueEditor";
import { cellValue, displayValue, LEVEL_LABEL } from "../lib/format";

interface Outcome {
  outcome: EditOutcome | "saving" | "error";
  message?: string;
}

export function AttributeForm({
  entity,
  channelEntity,
  channelCode,
  groups,
  optionLists,
  onlyMissing,
}: {
  entity: ProductRow;
  /** Values resolved for the selected channel, when comparing (DM-06). */
  channelEntity?: ProductRow | null;
  channelCode: string | null;
  groups: ProductGroupSection[];
  optionLists: Record<string, OptionList>;
  /** When set, only these attribute codes are shown (show only missing required). */
  onlyMissing: Set<string> | null;
}) {
  const me = useMe();
  const qc = useQueryClient();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});

  const save = useMutation({
    mutationFn: ({ code, value, channel }: { code: string; value: unknown; channel: string | null }) =>
      api.products.setValues(entity.entity_id, { [code]: value }, channel),
    onMutate: ({ code, channel }) => setOutcomes((o) => ({ ...o, [okey(code, channel)]: { outcome: "saving" } })),
    onSuccess: (res, { code, channel }) => {
      const r = res.results.find((x) => x.attribute_code === code);
      setOutcomes((o) => ({ ...o, [okey(code, channel)]: { outcome: r?.outcome ?? "approved", message: r?.message } }));
      qc.invalidateQueries({ queryKey: ["product", entity.entity_id] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
    },
    onError: (e, { code, channel }) =>
      setOutcomes((o) => ({ ...o, [okey(code, channel)]: { outcome: "error", message: errorMessage(e) } })),
  });

  const sections = useMemo(() => {
    return groups
      .map((g) => ({
        ...g,
        attributes: g.attributes
          .filter((a) => !onlyMissing || onlyMissing.has(a.code))
          .slice()
          .sort((a, b) => a.sort_order - b.sort_order),
      }))
      .filter((g) => g.attributes.length > 0);
  }, [groups, onlyMissing]);

  const toggle = (code: string) =>
    setCollapsed((s) => {
      const n = new Set(s);
      if (n.has(code)) n.delete(code);
      else n.add(code);
      return n;
    });

  if (sections.length === 0) {
    return (
      <div className="empty">
        <strong>{onlyMissing ? "Nothing is missing for this channel" : "No attribute groups apply"}</strong>
        {onlyMissing
          ? "Every required attribute has a value. Turn off the toggle to see all attributes."
          : "Assign a family to this product so its attribute groups apply."}
      </div>
    );
  }

  const compare = !!channelCode;

  return (
    <div>
      {compare && (
        <div className="compare-head">
          <span>Attribute</span>
          <span>Global value</span>
          <span>{channelCode} override</span>
        </div>
      )}
      {sections.map((s) => {
        const isCollapsed = collapsed.has(s.group.code);
        const right = me.data?.data_rights[s.group.code] ?? "none";
        return (
          <div className="panel group-section" key={s.group.code}>
            <div className="group-head" onClick={() => toggle(s.group.code)}>
              <span>
                {isCollapsed ? "▸" : "▾"} {s.group.label}
                <span className="faint small" style={{ marginLeft: 8 }}>
                  {s.attributes.length} attribute{s.attributes.length === 1 ? "" : "s"}, owner {s.group.owning_role}
                </span>
              </span>
              <span className="row">
                {s.group.read_only && <Badge>read only</Badge>}
                <Badge color={right === "approve" ? "green" : right === "edit" ? "teal" : undefined}>your rights: {right}</Badge>
              </span>
            </div>
            {!isCollapsed &&
              s.attributes.map((a) => (
                <AttributeRow
                  key={a.code}
                  attr={a}
                  entity={entity}
                  channelEntity={channelEntity}
                  channelCode={channelCode}
                  optionList={a.option_list_code ? optionLists[a.option_list_code] : undefined}
                  optionLists={optionLists}
                  groupReadOnly={s.group.read_only}
                  editable={canEdit(me.data, a)}
                  outcomes={outcomes}
                  missing={!!onlyMissing}
                  onSave={(code, value, channel) => save.mutate({ code, value, channel })}
                />
              ))}
          </div>
        );
      })}
    </div>
  );
}

const okey = (code: string, channel: string | null) => `${channel ?? ""}|${code}`;

function AttributeRow({
  attr,
  entity,
  channelEntity,
  channelCode,
  optionList,
  optionLists,
  groupReadOnly,
  editable,
  outcomes,
  missing,
  onSave,
}: {
  attr: AttributeDefinition;
  entity: ProductRow;
  channelEntity?: ProductRow | null;
  channelCode: string | null;
  optionList?: OptionList;
  optionLists: Record<string, OptionList>;
  groupReadOnly: boolean;
  editable: boolean;
  outcomes: Record<string, Outcome>;
  missing: boolean;
  onSave: (code: string, value: unknown, channel: string | null) => void;
}) {
  const cell = entity.values[attr.code];
  const compare = !!channelCode && attr.channel_scopable;
  const chCell = channelEntity?.values[attr.code];

  const baseEditable =
    editable && !groupReadOnly && attr.status !== "deprecated" && attr.source_of_truth !== "erp" && attr.level === entity.level;
  const globalEditable = baseEditable && !(cell?.read_only ?? false);
  const channelEditable = baseEditable && !(chCell?.read_only && chCell.read_only_reason !== "inherited");

  return (
    <div id={`attr-${attr.code}`} className={`attr-row${compare ? " compare" : ""}${missing ? " missing" : ""}`}>
      <div className="attr-label">
        {attr.label}
        {attr.unit && <span className="faint"> ({attr.unit})</span>}
        <LockIcon cell={cell} />
        {cell?.ai_generated && <AiBadge />}
        <span className="code">
          {attr.code} <span className="faint">{attr.data_type}</span>
          {attr.status === "deprecated" && <Badge color="red">deprecated</Badge>}
          {attr.channel_scopable && !compare && <Badge title="Can hold a per-channel override">channel</Badge>}
        </span>
        {attr.help_text && <div className="help">{attr.help_text}</div>}
      </div>

      <ValueColumn
        attr={attr}
        cell={cell}
        optionList={optionList}
        optionLists={optionLists}
        editable={globalEditable}
        outcome={outcomes[okey(attr.code, null)]}
        onSave={(v) => onSave(attr.code, v, null)}
        entityLevel={entity.level}
      />

      {compare && (
        <div>
          <ValueColumn
            attr={attr}
            cell={chCell}
            optionList={optionList}
            optionLists={optionLists}
            editable={channelEditable}
            outcome={outcomes[okey(attr.code, channelCode)]}
            onSave={(v) => onSave(attr.code, v, channelCode)}
            entityLevel={entity.level}
            isChannel
          />
          {channelEditable && (
            <button
              className="small mt8"
              title={`Copy the global value into the ${channelCode} override`}
              onClick={() => onSave(attr.code, cellValue(cell), channelCode)}
              disabled={cellValue(cell) === null || cellValue(cell) === undefined}
            >
              Copy to channel
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ValueColumn({
  attr,
  cell,
  optionList,
  optionLists,
  editable,
  outcome,
  onSave,
  entityLevel,
  isChannel,
}: {
  attr: AttributeDefinition;
  cell: ValueCell | undefined;
  optionList?: OptionList;
  optionLists: Record<string, OptionList>;
  editable: boolean;
  outcome?: Outcome;
  onSave: (v: unknown) => void;
  entityLevel: string;
  isChannel?: boolean;
}) {
  const value = cellValue(cell);
  const inherited = cell?.inherited_from ?? (attr.level !== entityLevel && attr.level in LEVEL_LABEL ? { level: attr.level, entity_id: "" } : null);

  const renderReadOnly = () => {
    if (attr.data_type === "reference_entity") {
      const v = value as { id?: string; code?: string; label?: string } | string | null;
      const id = typeof v === "string" ? v : (v?.id ?? v?.code);
      const label = typeof v === "string" ? v : (v?.label ?? v?.code ?? v?.id);
      return (
        <div className="readonly-value">
          {id && attr.reference_type_code ? (
            <Link to={`/reference/${encodeURIComponent(attr.reference_type_code)}/${encodeURIComponent(id)}`}>{label}</Link>
          ) : (
            <span className="faint">{label ?? "not linked"}</span>
          )}
          {id && attr.reference_type_code && <span className="help">Shared record. Edit it on the reference page; every linked product updates.</span>}
        </div>
      );
    }
    const text = cell?.not_applicable ? "N/A" : displayValue(value, attr, optionLists);
    return (
      <div className="readonly-value">
        {text || <span className="faint">{isChannel ? "no override (falls back to global)" : "empty"}</span>}
        {cell?.is_default && <span className="faint"> (default)</span>}
      </div>
    );
  };

  return (
    <div className="attr-value">
      {editable && attr.data_type !== "reference_entity" ? (
        <ValueEditor
          key={`${attr.code}:${cell?.version ?? 0}:${JSON.stringify(value ?? null)}`}
          attr={attr}
          optionList={optionList}
          value={cell?.draft ? cell.draft.value : value}
          onCommit={(v) => {
            if (JSON.stringify(v ?? null) !== JSON.stringify(value ?? null)) onSave(v);
          }}
        />
      ) : (
        <Provenance cell={cell}>{renderReadOnly()}</Provenance>
      )}
      <div className="attr-meta">
        {cell && (
          <>
            <span>{cell.source_type}</span>
            {cell.set_by && <span>by {cell.set_by}</span>}
            <ApprovalBadge state={cell.approval_state} />
          </>
        )}
        {cell?.draft && (
          <Badge color="amber" title={`Draft by ${cell.draft.set_by}`}>
            Draft, pending approval
          </Badge>
        )}
        {cell?.raw_value && <span title="ERP raw value before normalization (IMP-11)">ERP raw: {cell.raw_value}</span>}
        {inherited && (
          <span>
            Inherited from {LEVEL_LABEL[inherited.level] ?? inherited.level}.{" "}
            {inherited.entity_id ? (
              <Link to={`/products/${encodeURIComponent(inherited.entity_id)}`}>Edit at {LEVEL_LABEL[inherited.level] ?? inherited.level}</Link>
            ) : (
              <span>Edit at the owning {LEVEL_LABEL[inherited.level] ?? inherited.level}.</span>
            )}
          </span>
        )}
        {attr.allows_not_applicable && editable && (
          <button className="link small" onClick={() => onSave(null)} title="Clear the value">
            clear
          </button>
        )}
        {outcome?.outcome === "saving" && <span>saving</span>}
        {outcome?.outcome === "approved" && <Badge color="green">saved</Badge>}
        {outcome?.outcome === "draft" && <Badge color="amber">Draft, pending approval</Badge>}
        {(outcome?.outcome === "rejected" || outcome?.outcome === "error") && (
          <span className="field-error">{outcome.message ?? "Rejected"}</span>
        )}
      </div>
    </div>
  );
}
