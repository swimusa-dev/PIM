// Product Information Setup File export: fill an uploaded setup file with PIM values, or build a new one for pasted
// style numbers. Both download an .xlsx in the setup file layout with a "PIM Export Report" sheet.

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type FileDownload } from "../api/client";
import { ErrorBox } from "../components/Common";

function useDownloadUrl(result: FileDownload | undefined): string | undefined {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    if (!result) return undefined;
    const u = URL.createObjectURL(result.blob);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [result]);
  return url;
}

function Summary({ result }: { result: FileDownload }) {
  const url = useDownloadUrl(result);
  const s = result.summary;
  return (
    <div className="stack gap8 mt8">
      <div className="row">
        {url && (
          <a className="btn primary" href={url} download={result.fileName}>
            Download {result.fileName}
          </a>
        )}
      </div>
      <ul className="small">
        <li>
          {s.matched} of {s.rows} rows matched a style-color in the PIM. {s.cells_filled} cells filled
          {s.cells_changed > 0 && `, ${s.cells_changed} of them replacing a different value in the file (listed in the report sheet)`}.
        </li>
        {s.not_in_pim?.length > 0 && <li>Not found in the PIM: {s.not_in_pim.join(", ")}</li>}
        {(s.styles_not_found?.length ?? 0) > 0 && <li>Styles not found: {s.styles_not_found?.join(", ")}</li>}
        {s.no_key?.length > 0 && <li>Rows without a Style # or Color Code: {s.no_key.join(", ")}</li>}
        {s.columns_without_pim_attribute?.length > 0 && (
          <li>
            Columns the PIM has no attribute for yet, so they keep whatever the file had: {s.columns_without_pim_attribute.join(", ")}
          </li>
        )}
        {s.images_dropped && <li>Pictures embedded in the uploaded file are not carried over; Style Image holds the PIM image link.</li>}
      </ul>
    </div>
  );
}

export function SetupFilePage() {
  const [file, setFile] = useState<File | null>(null);
  const [keep, setKeep] = useState(false);
  const [styles, setStyles] = useState("");
  const fill = useMutation({ mutationFn: () => api.setupFile.fill(file as File, keep) });
  const create = useMutation({ mutationFn: () => api.setupFile.create({ styles }) });

  return (
    <div>
      <div className="page-header">
        <h1>Product Information Setup File</h1>
      </div>
      <p className="muted small">
        Builds the VA Product Information Setup File from approved PIM data. Drafts, unapproved AI suggestions and unconfirmed
        defaults are left out.
      </p>
      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <h3>Fill a setup file</h3>
          </div>
          <div className="panel-body stack gap16">
            <p className="small">
              Upload a setup file. Each row is matched to the PIM by Style # and Color Code, and the PIM's values are written into
              the matching columns. Columns the PIM does not hold are left as they are.
            </p>
            <input type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <label className="inline">
              <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
              Only fill empty cells (keep every value already in the file)
            </label>
            {fill.isError && <ErrorBox error={fill.error} title="Could not fill the setup file" />}
            <div className="row">
              <button className="primary" disabled={!file || fill.isPending} onClick={() => fill.mutate()}>
                {fill.isPending ? "Filling" : "Fill from PIM"}
              </button>
            </div>
            {fill.data && <Summary result={fill.data} />}
          </div>
        </div>
        <div className="panel">
          <div className="panel-header">
            <h3>New setup file</h3>
          </div>
          <div className="panel-body stack gap16">
            <p className="small">
              Paste style numbers, one per line or separated by commas. Add a color code (6000150-MBU) for one color; a style number
              alone brings every color.
            </p>
            <textarea value={styles} onChange={(e) => setStyles(e.target.value)} placeholder={"6000150\n6131286-KLP"} style={{ width: "100%", minHeight: 120 }} />
            {create.isError && <ErrorBox error={create.error} title="Could not build the setup file" />}
            <div className="row">
              <button className="primary" disabled={!styles.trim() || create.isPending} onClick={() => create.mutate()}>
                {create.isPending ? "Building" : "Build setup file"}
              </button>
            </div>
            {create.data && <Summary result={create.data} />}
          </div>
        </div>
      </div>
    </div>
  );
}
