# ADR-0016: Document Identity, Deletion Lifecycle, and Data Integrity

**Date**: 2026-07-30
**Status**: accepted
**Deciders**: KB RAG system design

## Context

Live operation of the ingestion pipeline surfaced three structural gaps, not
hypothetical ones:

1. **Identity collision causing silent data loss.** `document_id` was
   derived from only the blob's top-level upload folder
   (`blob_name.split("/")[1]`). Two different files uploaded to the same
   folder — `cooking-made-easy/Cooking-Made-Easy.pdf` followed later by
   `cooking-made-easy/CSHE-Recipe-Book-2022.pdf` — received the *same*
   `document_id`. Azure AI Search's `upload_documents` is an upsert by `id`
   (`{document_id}_chunk_{i}`), so the second file's chunks silently
   overwrote the first file's Search entries at matching `chunk_index`
   positions. This was only discovered because a user noticed a PDF they
   expected to see in search results was missing — a full day after the
   overwrite happened.
2. **No deletion contract.** Nothing cleaned up Azure Search or Mongo when a
   blob was deleted. 92 orphaned Search chunks and 8 stale Mongo records
   accumulated silently from earlier testing before being found and
   manually purged in the same investigation as (1).
3. **No safety net.** Blob soft-delete was disabled on the storage account
   (`stdevaz1dp001`), so every corrective deletion performed during that
   investigation — including the orphaned-chunk cleanup itself — was
   permanent with no recovery window.

None of these are edge cases; they're the absence of an identity scheme and
a lifecycle model for documents moving through create → index → archive →
delete.

## Decision

1. **Content-addressed `document_id`** (`document_identity.py`): a
   human-readable slug of `upload_folder` + `filename`, plus a short SHA-256
   hash of the exact path as a collision-safety suffix. Physical blob
   storage layout stays keyed by `upload_folder`/`filename` (unchanged,
   human-browsable); only the Search/Mongo identity key changed.
2. **`environment` field** on every Mongo and Search record (default
   `"dev"`, from the `ENVIRONMENT` app setting), enforced in the new
   reconciliation job's queries — lets a future prod deployment of the same
   Function App module filter dev-vs-prod traffic without a schema
   redesign, without provisioning a second Search index/Mongo database now
   (no prod workload exists yet to justify that cost).
3. **Two-phase soft-delete, not event-cascaded deletion.** `DELETE
   /manage/documents/{id}` now marks the Mongo record `status="deleted"`
   (kept, not removed), moves its blob to a `deleted/` holding container,
   and removes its Search chunks immediately (Search is a derived,
   regenerable index — no reason to soft-delete it too). A nightly
   `purge_job.py` timer hard-deletes anything in `deleted/` past a 7-day
   retention window and marks the Mongo record `status="purged"`. A Blob
   Storage lifecycle-management policy on the same container is a redundant
   backstop, not the primary mechanism.

   Reacting to `BlobDeleted` events was considered and rejected — see
   Alternatives.
4. **Nightly reconciliation job** (`reconciliation_job.py`): diffs Mongo's
   `status="indexed"` document_ids against what Search actually has for the
   same `environment`, logging drift in both directions. Detection only, not
   auto-healing (see Alternatives).
5. **Blob soft-delete + container soft-delete enabled** on `stdevaz1dp001`
   (7-day retention, applied out-of-band via `az storage account
   blob-service-properties update` — see Consequences for why this isn't a
   Terraform-managed resource). Blob **versioning** was attempted but is
   unsupported on this HNS/Data Lake Gen2 account
   (`FeatureNotSupportedForAccount`).
6. **Azure Monitor alerting**: a Log Analytics-scoped scheduled query alert
   (`azurerm_monitor_scheduled_query_rules_alert_v2`, not a classic metric
   alert — see Alternatives) fires on `AppTraces`/`AppExceptions` with
   `SeverityLevel >= 3` or containing `"Failed to process"` /
   `"Reconciliation drift"`, emailing the configured `alert_email`.

## Alternatives Considered

### Alternative 1: `document_id` = SHA-256 hash of file content
- **Pros**: Even stronger collision resistance than a path-derived hash;
  identical bytes always get the same id regardless of where uploaded.
- **Cons**: Every re-upload of a *corrected* version of the same document
  (same path, new content) becomes an entirely new, unrelated
  `document_id` — the old chunks are never superseded, just orphaned again.
  Also produces opaque, non-human-readable ids, losing the
  browsability that made choosing folder names like
  `cooking-made-easy-youth-guide` useful during manual investigation this
  same day.
- **Why not**: Path-derived ids give retry idempotency (a retried upload to
  the same path produces the same id) and correct "resubmission" semantics
  (same path = same logical document, content update is an upsert) without
  either problem.

### Alternative 2: React to `BlobDeleted` events for cleanup
- **Pros**: Fully automatic — no separate admin action needed to clean up
  after a blob is deleted.
- **Cons**: `stage7_archive.py`'s own archive step deletes the source blob
  as its last action on every *successful* run. A handler listening for
  `BlobDeleted` on the source container cannot distinguish "successfully
  archived" from "user wants this gone" — it would delete a document's
  Search chunks and Mongo record immediately after creating them, on every
  successful document, which is exactly the class of self-inflicted bug
  this system already hit once (ADR for the archive self-triggering loop).
- **Why not**: An explicit, admin-triggered soft-delete operation is the
  only design that can tell these two cases apart; event-cascaded deletion
  structurally cannot.

### Alternative 3: Auto-heal drift found by the reconciliation job
- **Pros**: Missing documents get fixed without a human noticing and acting.
- **Cons**: "Missing from Search" is ambiguous — which blob should be
  re-read to regenerate it? The source blob may already be archived, soft-
  deleted, or purged by the time drift is detected. Auto-re-triggering
  ingestion from inferred state risks a second, different silent-overwrite
  bug on top of the first.
- **Why not**: Detection-and-alert is the safe default until a
  well-scoped, explicitly-triggered "re-ingest from archive" operation
  exists as its own reviewed feature.

### Alternative 4: Classic Azure Monitor metric alert on the Function App
- **Pros**: Simpler resource, no KQL query to maintain.
- **Cons**: This system's Application Insights resource is workspace-based
  (`IngestionMode: LogAnalytics`) — confirmed live that `az monitor
  app-insights query` and, by the same mechanism, classic metric alerts
  scoped to the Function App resource do not see this data. Only queries
  against the linked Log Analytics workspace's `AppTraces`/`AppExceptions`
  tables do.
- **Why not**: A metric alert here would silently never fire — discovered
  this exact failure mode live while debugging App Insights queries earlier
  the same day.

### Alternative 5: Provision a real second (prod) Search index / Mongo database now
- **Pros**: Full dev/prod isolation immediately; no future migration needed.
- **Cons**: No prod workload exists yet — everything today runs in one dev
  subscription and resource group. A second Search index and Mongo database
  would sit empty, adding cost and operational surface for a phase that
  hasn't started.
- **Why not**: The `environment` field gives the same isolation capability
  (filterable in every query) without provisioning unused infrastructure.
  Revisit when a real prod deployment is scheduled.

## Consequences

### Positive
- The exact collision bug that caused silent data loss (Alternative 1's
  motivating incident) is now structurally prevented, not just patched for
  the one instance found.
- Deletions are recoverable for 7 days at two independent layers (app-level
  `deleted/` container + purge job, and storage-account-level blob/container
  soft-delete) instead of zero.
- Drift between Mongo and Search — previously invisible until a human
  happened to notice — is now checked nightly and alerts by email.
- `DELETE /manage/documents/{id}` also fixed a latent bug found while
  rewriting it: it deleted from the *source* container
  (`storage_container_name`), but a successfully-processed document's blob
  has already been moved to `processed/` by the archive step by the time
  anyone would call delete — the original hard-delete would have silently
  no-op'd on the blob step for every already-processed document. The new
  code checks `processed/` first, then falls back to the source container.

### Negative
- Two ingestion paths now exist with different `document_id` schemes: the
  CMS management API (`backend/api/management/router.py`) mints a random
  UUID at upload time (never collides by construction), while the direct
  blob-upload path (used for testing, and for the pipeline's Event
  Grid-triggered production flow) uses the new path-derived scheme. Both
  are stable and collision-resistant, but they look different, which is
  worth knowing when debugging.
- Blob soft-delete configuration on `stdevaz1dp001` is **not**
  Terraform-managed — the AzureRM provider only exposes `blob_properties`
  as a nested block on a *managed* `azurerm_storage_account` resource, not
  attachable to the `data` source this project uses for a shared,
  externally-provisioned account (see ADR-0014). It was applied
  out-of-band via `az storage account blob-service-properties update` and
  is documented in `modules/storage/main.tf` as a comment so it isn't
  mistaken for drift.
- Blob versioning could not be enabled at all — unsupported on HNS/Data
  Lake Gen2 accounts. Soft-delete is the only recovery mechanism available
  at the storage-account level for this account.
- Pre-existing, unrelated Terraform state drift was discovered while
  validating this work (a full `terraform plan` wants to add ~25 resources,
  consistent with Redis/Cosmos having been provisioned manually outside
  Terraform in an earlier session). Not addressed here — deliberately out
  of scope, and reconciling it is a separate decision with its own risk
  profile.

### Risks
- **Reconciliation job cost/quota**: nightly full-index Search queries and
  full Mongo collection scans are cheap at current scale (tens of
  documents) but should be revisited if the corpus grows into the
  thousands — the job currently has no pagination limit by design (an
  explicit fix for a *different* bug where `top=1000` silently truncated
  comparisons), which means it will eventually need query-side filtering or
  batching rather than removing that fix.
- **Alert fatigue**: the alert rule fires on any `SeverityLevel >= 3` trace
  or exception, not just document-processing failures — if other noisy
  error logging is added to this Function App later, the alert may need
  narrowing to avoid being ignored.
- **Two-phase delete still depends on the purge job actually running**: if
  the timer trigger silently stops firing, soft-deleted documents
  accumulate in `deleted/` past their intended retention — mitigated by the
  Blob lifecycle-management policy backstop, but that backstop doesn't
  update the Mongo `status="purged"` field, so Mongo and blob storage could
  drift from each other in that failure mode specifically.
