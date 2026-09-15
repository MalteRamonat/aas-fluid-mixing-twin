-- Time-series store for the ModVA twin. One schema for measured and simulated runs so an
-- overlay is a single query. Applied idempotently by TimescaleStore.apply_schema().
--
-- Long format on purpose: channel sets differ between measured runs (47 or 41 columns) and
-- simulated runs (29), and a long table absorbs that without migrations. Volume is small
-- (55 runs x ~370 rows x ~47 channels ~ 960 k rows).

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS run (
    run_id          TEXT PRIMARY KEY,
    origin          TEXT NOT NULL CHECK (origin IN ('measured', 'simulated')),
    scenario        TEXT NOT NULL,
    anomaly_label   SMALLINT NOT NULL,
    -- Wall clock as recorded in "Server Time". The benchmark states no time zone, so the
    -- value is kept verbatim rather than being assigned one.
    started_at      TIMESTAMP NOT NULL,
    ended_at        TIMESTAMP NOT NULL,
    duration_s      DOUBLE PRECISION NOT NULL,
    record_count    INTEGER NOT NULL,
    schema_variant  TEXT NOT NULL,          -- 'full' | 'reduced' (dataset_0)
    source_file     TEXT,
    usable          BOOLEAN NOT NULL DEFAULT TRUE,
    note            TEXT,
    -- [{label, onset_s, end_s, source}] from data/fault_annotations.yaml; [] for normal runs.
    fault_windows   JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Simulation parameter set (schedule, overrides); NULL for measured runs.
    params          JSONB,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sample (
    run_id   TEXT NOT NULL REFERENCES run (run_id) ON DELETE CASCADE,
    ts       TIMESTAMP NOT NULL,            -- "Server Time"; synthetic for simulated runs
    t_rel_s  DOUBLE PRECISION NOT NULL,     -- "Session Time Stamps" / Modelica time
    channel  TEXT NOT NULL,                 -- CSV column name, verbatim (typo included)
    value    DOUBLE PRECISION               -- NULL where the CSV cell is empty
);

SELECT create_hypertable('sample', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS sample_run_channel_t ON sample (run_id, channel, t_rel_s);

-- Point-in-time label per sample, resolved from the operator's onset times
-- (RunMetadata.label_at). One row per timestamp, not per channel.
CREATE TABLE IF NOT EXISTS sample_label (
    run_id   TEXT NOT NULL REFERENCES run (run_id) ON DELETE CASCADE,
    t_rel_s  DOUBLE PRECISION NOT NULL,
    label    SMALLINT NOT NULL,
    PRIMARY KEY (run_id, t_rel_s)
);
