"""One-customer migration rehearsal for IT Glue and Hudu.

Modules:
    redact     secret handling: fingerprints, raw-payload scrubbing, text redaction
    transport  HTTP access to the source API (the only module that talks to the network)
    sources    staging: fetch one source organization into StagedRecord rows
    normalize  source record -> canonical record (shared with the legacy importer)
    targets    canonical record -> ClientSt0r model (field specs, natural keys, writes)
    planner    build / correct / freeze a plan
    applier    apply exactly the frozen plan (idempotent, resumable)
    undo       roll a plan back without undoing later local edits
    report     redacted reconciliation report
    inventory  permission-checked per-customer inventory export
"""
