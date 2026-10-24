// IMP-01 import wizard: Upload, Map, Validate, Match, Review and Commit as a stepper.
// Also IMP-02 to IMP-08 and IMP-12 through the step components in src/imports.

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ImportBatch } from "../api/types";
import { ErrorBox, Spinner } from "../components/Common";
import { UploadStep } from "../imports/UploadStep";
import { MapStep } from "../imports/MapStep";
import { ValidateStep } from "../imports/ValidateStep";
import { MatchStep } from "../imports/MatchStep";
import { ReviewStep } from "../imports/ReviewStep";
import { reachedStep, STEPS, type StepKey } from "../imports/shared";
import { BatchStatusBadge } from "./Imports";
import { formatDate, LEVEL_LABEL } from "../lib/format";

export function ImportWizardPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();

  const q = useQuery({
    queryKey: ["imports", "batch", id],
    queryFn: () => api.imports.batch(id!),
    enabled: !!id,
    refetchInterval: (query) => (query.state.data?.status === "committing" ? 2000 : false),
  });
  const batch = id ? q.data ?? null : null;
  const reached = reachedStep(batch?.status);

  const stepFromUrl = params.get("step") as StepKey | null;
  const [step, setStep] = useState<StepKey>(stepFromUrl ?? "upload");
  useEffect(() => {
    if (stepFromUrl && STEPS.some((s) => s.key === stepFromUrl)) setStep(stepFromUrl);
  }, [stepFromUrl]);

  // Default to the next step the status allows when no step is in the URL.
  useEffect(() => {
    if (!batch) return;
    if (stepFromUrl) return;
    const target = batch.worksheet_id && reached === 1 ? "validate" : STEPS[Math.min(reached, STEPS.length - 1)].key;
    setStep(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch?.id]);

  const go = (k: StepKey) => {
    setStep(k);
    setParams({ step: k }, { replace: true });
  };
  const onBatch = (b: ImportBatch) => {
    qc.setQueryData(["imports", "batch", b.id], b);
    if (!id) navigate(`/imports/${encodeURIComponent(b.id)}?step=${b.worksheet_id ? "validate" : b.status === "mapped" ? "validate" : "map"}`, { replace: true });
  };

  const stepIndex = useMemo(() => STEPS.findIndex((s) => s.key === step), [step]);
  const stepsVisible = STEPS;
  const locked = batch?.status === "committing";

  if (id && q.isLoading) return <Spinner label="Loading import batch" />;
  if (id && q.isError) return <ErrorBox error={q.error} title="Could not load the import batch" />;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="muted small">
            <Link to="/imports">Imports</Link> / {batch ? `Batch ${batch.id}` : "New import"}
          </div>
          <h1 className="row">
            {batch ? `Import ${batch.id}` : "New import"}
            {batch && <BatchStatusBadge status={batch.status} />}
          </h1>
          {batch && (
            <div className="muted small">
              {batch.source_code}, {LEVEL_LABEL[batch.level]}, created by {batch.created_by} at {formatDate(batch.created_at)}
            </div>
          )}
        </div>
      </div>

      <div className="stepper" role="tablist">
        {stepsVisible.map((s, i) => {
          const done = i < reached && i !== stepIndex;
          const enabled = i <= reached && !locked;
          return (
            <button
              key={s.key}
              role="tab"
              aria-selected={s.key === step}
              className={s.key === step ? "current" : done ? "done" : ""}
              disabled={!enabled}
              onClick={() => go(s.key)}
            >
              <span className="n">{done ? "✓" : i + 1}</span>
              {s.label}
            </button>
          );
        })}
      </div>

      {step === "upload" && <UploadStep batch={batch} onBatch={onBatch} onNext={() => go(batch?.worksheet_id ? "validate" : "map")} />}
      {step === "map" && batch && <MapStep key={batch.id} batch={batch} onBatch={onBatch} onNext={() => go("validate")} onBack={() => go("upload")} />}
      {step === "validate" && batch && <ValidateStep batch={batch} onBatch={onBatch} onNext={() => go("match")} onBack={() => go(batch.worksheet_id ? "upload" : "map")} />}
      {step === "match" && batch && <MatchStep batch={batch} onBatch={onBatch} onNext={() => go("review")} onBack={() => go("validate")} />}
      {step === "review" && batch && <ReviewStep batch={batch} onBatch={onBatch} onBack={() => go("match")} />}
      {step !== "upload" && !batch && <ErrorBox error="Upload a file first." title="No batch yet" />}
    </div>
  );
}
