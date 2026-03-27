CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    task_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_updated_at_desc
    ON tasks (updated_at DESC);

CREATE TABLE IF NOT EXISTS evaluation_records (
    evaluation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL,
    request_json JSONB NOT NULL,
    result_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evaluation_records_task_recorded_at
    ON evaluation_records (task_id, recorded_at);
