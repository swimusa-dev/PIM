// IMG-07: Image profile per channel. Shot types multi-select from /api/metadata/shot-types, width, height,
// format, pad to ratio, background and naming template. Saved together with the mapping (PUT mapping).

import { useShotTypes } from "../../api/hooks";
import type { ImageProfile } from "../../api/types";
import { ErrorBox, Spinner } from "../../components/Common";

export const EMPTY_IMAGE_PROFILE: ImageProfile = { shot_types: [], format: "jpg", pad_to_ratio: null, background: null, naming: null };

export function ImageProfileTab({ profile, setProfile, canEdit }: { profile: ImageProfile; setProfile: (p: ImageProfile) => void; canEdit: boolean }) {
  const shotTypes = useShotTypes();
  const toggleShot = (code: string) =>
    setProfile({ ...profile, shot_types: profile.shot_types.includes(code) ? profile.shot_types.filter((s) => s !== code) : [...profile.shot_types, code] });

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Image profile</h3>
        <span className="muted small">Renditions for this channel are created with these settings (IMG-07). Save with the mapping.</span>
      </div>
      <div className="panel-body">
        <fieldset disabled={!canEdit} style={{ border: "none", padding: 0, margin: 0 }}>
          <div className="stack gap16">
            <div>
              <div className="muted small mb8">Shot types sent to this channel (in slot order)</div>
              {shotTypes.isLoading && <Spinner label="Loading shot types" />}
              {shotTypes.isError && <ErrorBox error={shotTypes.error} title="Could not load shot types" />}
              {shotTypes.data && shotTypes.data.length === 0 && <span className="faint">No shot types are defined under the metadata.</span>}
              <div className="checklist">
                {(shotTypes.data ?? []).map((s) => (
                  <label key={s.code} className="inline">
                    <input type="checkbox" checked={profile.shot_types.includes(s.code)} onChange={() => toggleShot(s.code)} /> {s.label}
                  </label>
                ))}
              </div>
            </div>
            <div className="form-grid">
              <label className="field">
                Width (px)
                <input type="number" min={1} value={profile.width ?? ""} onChange={(e) => setProfile({ ...profile, width: e.target.value === "" ? undefined : Number(e.target.value) })} />
              </label>
              <label className="field">
                Height (px)
                <input type="number" min={1} value={profile.height ?? ""} onChange={(e) => setProfile({ ...profile, height: e.target.value === "" ? undefined : Number(e.target.value) })} />
              </label>
              <label className="field">
                Format
                <select value={profile.format} onChange={(e) => setProfile({ ...profile, format: e.target.value as ImageProfile["format"] })}>
                  <option value="jpg">jpg</option>
                  <option value="png">png</option>
                  <option value="webp">webp</option>
                </select>
              </label>
              <label className="field">
                Pad to ratio (optional)
                <input value={profile.pad_to_ratio ?? ""} placeholder="e.g. 3:4 or 1:1" onChange={(e) => setProfile({ ...profile, pad_to_ratio: e.target.value || null })} />
              </label>
              <label className="field">
                Background
                <select value={profile.background ?? ""} onChange={(e) => setProfile({ ...profile, background: (e.target.value || null) as ImageProfile["background"] })}>
                  <option value="">Keep original</option>
                  <option value="white">White</option>
                  <option value="transparent">Transparent</option>
                </select>
              </label>
              <label className="field" style={{ gridColumn: "1 / -1" }}>
                Naming template
                <input className="mono" value={profile.naming ?? ""} placeholder="{{style_number}}-{{color_code}}-{{seq}}" onChange={(e) => setProfile({ ...profile, naming: e.target.value || null })} />
                <span className="help">Placeholders: {"{{style_number}}, {{color_code}}, {{shot_type}}, {{seq}}"} and any attribute as {"{{attr.code}}"}.</span>
              </label>
            </div>
          </div>
        </fieldset>
      </div>
    </div>
  );
}
