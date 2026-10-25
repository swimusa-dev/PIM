// EXP-01, EXP-02, EXP-05, EXP-06, IMG-07, Phase 5 EXP-09, EXP-10, EXP-11: expandable channel editor with tabs
// Target schema, Mapping, Image profile, Transport, Schedule and Health. Mapping and image profile share one
// draft saved with PUT /api/channels/{code}/mapping (needs the edit_profile channel right, RBAC-03); the
// Transport tab saves its own draft with PUT /api/channels/{code}/transport.

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { channelApi } from "../api/client";
import { channelRight, useMe } from "../api/hooks";
import type { Channel, ChannelMappingUpdate } from "../api/types";
import { Badge, ErrorBox, Spinner, Tabs, useToast } from "../components/Common";
import { SchemaTab } from "./channel/SchemaTab";
import { MappingTab } from "./channel/MappingTab";
import { EMPTY_IMAGE_PROFILE, ImageProfileTab } from "./channel/ImageProfileTab";
import { ScheduleTab } from "./channel/ScheduleTab";
import { HealthTab } from "./channel/HealthTab";
import { TransportTab } from "./channel/TransportTab";

type EditorTab = "schema" | "mapping" | "images" | "transport" | "schedule" | "health";

// EXP-01: the API stores attribute_mapping as PIM source (attribute code, ref path, core.<field>) -> target field.
// The editor keys its draft by target field, so the map is inverted on load and on save.
function targetKeyed(serverMap: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [source, target] of Object.entries(serverMap)) if (target) out[target] = source;
  return out;
}
function sourceKeyed(draftMap: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [target, source] of Object.entries(draftMap)) if (source) out[source] = target;
  return out;
}

export function ChannelEditor({ channel }: { channel: Channel }) {
  const qc = useQueryClient();
  const toast = useToast();
  const me = useMe();
  const canEdit = channelRight(me.data, channel.code, "edit_profile");
  const [tab, setTab] = useState<EditorTab>("schema");

  const schema = useQuery({ queryKey: ["channel", channel.code, "schema"], queryFn: () => channelApi.schema(channel.code) });
  const mapping = useQuery({ queryKey: ["channel", channel.code, "mapping"], queryFn: () => channelApi.mapping(channel.code) });
  const [draft, setDraft] = useState<ChannelMappingUpdate | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (mapping.data && !dirty) {
      setDraft({
        attribute_mapping: targetKeyed(mapping.data.attribute_mapping),
        transforms: mapping.data.transforms.map((t) => ({ ...t, args: { ...t.args } })),
        image_profile: { ...EMPTY_IMAGE_PROFILE, ...(mapping.data.image_profile ?? imageProfileFromConfig(channel)) },
      });
    }
  }, [mapping.data, dirty, channel]);

  const save = useMutation({
    mutationFn: () => channelApi.saveMapping(channel.code, { ...draft!, attribute_mapping: sourceKeyed(draft!.attribute_mapping) }),
    onSuccess: () => {
      toast("Mapping and image profile saved. The channel version was bumped.", "ok");
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["channel", channel.code] });
      qc.invalidateQueries({ queryKey: ["metadata", "channels"] });
      qc.invalidateQueries({ queryKey: ["products"], refetchType: "none" });
    },
    onError: (e) => toast(`Save failed: ${(e as Error).message}`, "error"),
  });

  const update = (d: ChannelMappingUpdate) => {
    setDraft(d);
    setDirty(true);
  };
  const gapCount = mapping.data ? mapping.data.gaps.required_fields_unmapped.length + mapping.data.gaps.mapped_fields_missing_in_schema.length : 0;

  return (
    <div className="channel-editor">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <Tabs<EditorTab>
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "schema", label: "Target schema", count: schema.data?.fields.length },
            { key: "mapping", label: "Mapping", count: gapCount || undefined },
            { key: "images", label: "Image profile" },
            { key: "transport", label: "Transport" },
            { key: "schedule", label: "Schedule" },
            { key: "health", label: "Health" },
          ]}
        />
        {(tab === "mapping" || tab === "images") && (
          <div className="row">
            {!canEdit && <Badge title="Editing needs the edit_profile right for this channel (or the * wildcard) on /api/me">read only</Badge>}
            {dirty && <span className="faint small">Unsaved changes</span>}
            <button
              className="small"
              disabled={!dirty || save.isPending}
              onClick={() => {
                setDirty(false);
                if (mapping.data) {
                  setDraft({
                    attribute_mapping: targetKeyed(mapping.data.attribute_mapping),
                    transforms: mapping.data.transforms.map((t) => ({ ...t, args: { ...t.args } })),
                    image_profile: { ...EMPTY_IMAGE_PROFILE, ...(mapping.data.image_profile ?? imageProfileFromConfig(channel)) },
                  });
                }
                qc.invalidateQueries({ queryKey: ["channel", channel.code, "mapping"] });
              }}
            >
              Discard
            </button>
            <button className="primary small" disabled={!canEdit || !dirty || !draft || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving" : "Save mapping and image profile"}
            </button>
          </div>
        )}
      </div>
      {tab === "schema" && <SchemaTab channel={channel} />}
      {(tab === "mapping" || tab === "images") && mapping.isLoading && <Spinner label="Loading mapping" />}
      {(tab === "mapping" || tab === "images") && mapping.isError && <ErrorBox error={mapping.error} title="Could not load the channel mapping" />}
      {tab === "mapping" && mapping.data && draft && <MappingTab schema={schema.data} server={mapping.data} draft={draft} setDraft={update} canEdit={canEdit} />}
      {tab === "images" && draft && (
        <ImageProfileTab profile={draft.image_profile ?? EMPTY_IMAGE_PROFILE} setProfile={(p) => update({ ...draft, image_profile: p })} canEdit={canEdit} />
      )}
      {tab === "transport" && <TransportTab channel={channel} canEdit={canEdit} />}
      {tab === "schedule" && <ScheduleTab channel={channel} canEdit={canEdit} />}
      {tab === "health" && <HealthTab channel={channel} />}
    </div>
  );
}

/** Fallback when GET mapping does not echo the image profile: read it from the channel config, if present. */
function imageProfileFromConfig(channel: Channel): Partial<ChannelMappingUpdate["image_profile"]> {
  const p = channel.config?.image_profile;
  return p && typeof p === "object" ? (p as ChannelMappingUpdate["image_profile"]) : {};
}
