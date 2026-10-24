# PIM API contract, Phase 4 additions (AI enrichment and quality)

Extends the Phase 1 to 3 contracts. Phase 4 covers AI-01 to AI-07 and GOV-03. Every AI output lands as a
suggestion (`ValueDraft` with `ai_generated=true`, `state=proposed`) and is accepted, edited then accepted,
regenerated, or rejected by a person (AI-03). Nothing in this contract writes a product value directly.

## Common shapes

```ts
type TaskType = "generate"|"adapt"|"extract"|"classify"|"check"|"restructure"|"expand";   // AI-05

interface BrandVoice { brand_code: string; label: string; tone: string; do_rules: string[]; dont_rules: string[];
  blocked_terms: string[]; trademark_terms: Record<string,string>; punctuation_rules: string[]; examples: string[];
  version: number; updated_at: string; updated_by?: string|null }

interface PromptTemplate { code: string; version: number; label: string; task_type: TaskType; target_attribute?: string|null;
  // extract / restructure write several attributes; classify targets a select attribute; check targets any text attribute
  output_attributes: string[]; channel_code?: string|null; family_code?: string|null; brand_code: string;
  body: string;                       // uses {{attr.<code>}}, {{core.<field>}}, {{input.text}}, {{channel.max_length}}
  input_attributes: string[]; input_shot_types: string[]; accepts_text_input: boolean; accepts_document: boolean;
  max_length?: number|null;           // null = from the attribute definition and channel requirement
  model_task: "copy"|"classify";      // which configured endpoint (AI-01)
  status: "draft"|"active"|"retired"; updated_at: string; updated_by?: string|null;
  eval_gate?: { last_run_id?: string|null; last_score?: number|null; blocked: boolean } }
interface TemplateVersion { version: number; body: string; updated_at: string; updated_by?: string|null; note?: string|null }

interface AiOutput { id: string; run_id?: string|null; entity_id: string; label: string; attribute_code: string; channel_code: string;
  task_type: TaskType; template_code: string; template_version: number; model: string;
  status: "proposed"|"accepted"|"edited"|"rejected"|"failed"|"needs_input"|"info";   // info = check / classify-below-threshold results
  proposed_value: unknown; current_value: unknown; final_value?: unknown;           // final_value after accept or edit
  diff: { op: "equal"|"insert"|"delete"; text: string }[];                            // word-level vs current_value
  draft_id?: string|null; confidence?: number|null; needs_input: string[]; grounding_errors: string[];
  check_findings?: { kind: string; message: string; severity: "error"|"warning" }[];  // task_type check
  rejection_reason?: string|null; edit_distance?: number|null; prompt_tokens: number; completion_tokens: number; latency_ms: number;
  inputs: { text?: string|null; image_asset_ids: string[] };   // replayed by regenerate
  created_by: string; created_at: string; decided_by?: string|null; decided_at?: string|null }

interface AiRun { id: string; kind: "single"|"bulk"|"eval"; template_code: string; template_version: number; task_type: TaskType;
  channel_code: string; selection: Record<string, unknown>; status: "sample_pending"|"sample_approved"|"running"|"completed"|"failed"|"cancelled";
  sample_entity_ids: string[]; total: number; done: number; proposed: number; failed: number; needs_input: number;
  created_by: string; created_at: string; finished_at?: string|null; job_run_id?: string|null; error?: string|null;
  report: Record<string, unknown> }

interface AiMetrics { template_code: string; template_version?: number|null; outputs: number; accepted: number; edited: number; rejected: number;
  pending: number; acceptance_rate: number|null; mean_edit_distance: number|null;
  rejection_reasons: { reason: string; count: number }[]; tokens: { prompt: number; completion: number } }

interface EvalCase { id: string; entity_id: string; label: string; attribute_code: string; reference_text: string; created_at: string }
interface EvalRun { id: string; template_code: string; template_version: number; model: string; status: "running"|"passed"|"blocked"|"failed";
  cases: number; scores: { overlap: number; length_ok: number; grounded: number; voice_ok: number; composite: number };
  baseline_run_id?: string|null; baseline_composite?: number|null; delta?: number|null; threshold: number; mlflow_run_id?: string|null;
  created_by: string; created_at: string; finished_at?: string|null; error?: string|null; sample: { entity_id: string; label: string; reference: string; output: string; overlap: number }[] }

interface QualitySettings { excluded_groups: string[]; weights: Record<string, number>;      // check code -> weight
  enabled_checks: string[]; grade_bands: { A: number; B: number; C: number; D: number } }      // minimum score per grade, E below D
interface QualityCheck { code: string; label: string; passed: boolean; weight: number; details: string[] }
interface QualityScore { entity_id: string; channel_code: string; grade: "A"|"B"|"C"|"D"|"E"; score: number; checks: QualityCheck[]; computed_at: string }
```

## Endpoints

### Brand voice and templates (AI-02)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ai/brand-voices` | `BrandVoice[]` |
| GET / PUT | `/api/ai/brand-voices/{brand_code}` | PUT body = BrandVoice fields (admin_metadata); bumps version |
| GET | `/api/ai/templates?task_type=&target=&status=` | `PromptTemplate[]` |
| POST | `/api/ai/templates` | create (admin_metadata) → PromptTemplate v1 (status draft) |
| GET | `/api/ai/templates/{code}` | PromptTemplate plus `versions: TemplateVersion[]` |
| PUT | `/api/ai/templates/{code}` | body = fields; a body change creates a new version (admin_metadata) |
| POST | `/api/ai/templates/{code}/activate` | status active; 409 when the eval gate blocks it |
| POST | `/api/ai/templates/{code}/preview` | body `{entity_id, channel_code?, text?}` → `{prompt: string, inputs: Record<string,unknown>, missing_inputs: string[]}` (renders only, no model call) |

### Ask AI, review, apply (AI-03, AI-05, AI-06)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/products/{id}/ai/templates?attribute=` | `{templates: PromptTemplate[], can_run: boolean}` applicable to this product (level, family, brand); the UI groups by task_type |
| POST | `/api/ai/ask` | body `{entity_id, template_code, channel_code?, text?: string, document?: {name, content_base64}, image_asset_ids?: string[]}` (permission run_ai and edit right on the target group) → `{outputs: AiOutput[]}`; one output per written attribute; 409 when the AI endpoint is not configured |
| GET | `/api/ai/outputs?entity_id=&run_id=&status=&page=` | `{rows: AiOutput[], total}` |
| POST | `/api/ai/outputs/{id}/accept` | body `{value?: unknown}` (when given, edited then accepted; keeps ai_generated) → AiOutput; approve right on the group, else the draft stays proposed and the output records `edited` with the new draft value |
| POST | `/api/ai/outputs/{id}/reject` | body `{reason: string}` → AiOutput |
| POST | `/api/ai/outputs/{id}/regenerate` | body `{note?: string}` → new AiOutput (the old one is rejected with reason "regenerated") |

### Bulk AI (AI-04)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ai/runs` | body `{template_code, selection: {view_id?, entity_ids?}, channel_code?}` → AiRun with `status: sample_pending` and the first 5 sample outputs generated synchronously (`outputs: AiOutput[]`) |
| GET | `/api/ai/runs?status=&page=` | `{rows: AiRun[], total}` |
| GET | `/api/ai/runs/{id}` | AiRun plus `outputs: AiOutput[]` (first 200) |
| POST | `/api/ai/runs/{id}/approve-samples` | starts the rest as the `pim_ai_bulk` job (inline locally) → AiRun running |
| POST | `/api/ai/runs/{id}/cancel` | → AiRun cancelled |
| POST | `/api/ai/runs/{id}/accept-all` | approve every proposed draft of the run; needs approve rights on the target group → `{accepted: n, skipped: n}` |
| GET | `/api/approvals?run_id=` | existing queue; items now carry `run_id` and `ai_output_id`, and the response adds `runs: {run_id, template_code, count}[]` |

### Evaluation and metrics (AI-07)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ai/metrics?template_code=` | `AiMetrics[]` per template (and version when template_code given) |
| GET | `/api/ai/eval/cases?attribute=` | `EvalCase[]` |
| POST | `/api/ai/eval/cases/build` | body `{attribute_code, limit: 50}` builds the set from approved, human-written values → `{created: n, total: n}` |
| DELETE | `/api/ai/eval/cases/{id}` | |
| GET | `/api/ai/eval/runs?template_code=` | `EvalRun[]` |
| POST | `/api/ai/eval/runs` | body `{template_code}` runs the set (job or inline) → EvalRun; `blocked` when composite drops more than `threshold` below the last passed run |

### Quality score (GOV-03)

| Method | Path | Purpose |
|---|---|---|
| GET / PUT | `/api/quality/settings` | QualitySettings (PUT admin_metadata) |
| POST | `/api/quality/recompute` | body `{entity_ids?: string[]}` → `{computed: n}` (all style-colors when omitted; job when large) |
| GET | `/api/products/{id}/quality` | `{scores: QualityScore[]}` (one per channel plus `""` = overall) |
| GET | `/api/quality/dashboard?by=family|season|channel` | `{rows: {key: string, label: string, A: n, B: n, C: n, D: n, E: n, avg_score: number}[]}` |
| POST | `/api/products/query` | grid rows add `quality: {[channel_code or "overall"]: {grade, score}}`; column key `quality:<channel or overall>` is sortable and filterable (`op: in`, value grades) |
```
