function clone(value) {
  return structuredClone(value);
}

export class PipelineD1Mock {
  constructor(options = {}) {
    this.options = options;
    this.state = {
      pipelineRuns: [],
      articles: [],
      qualityGateAudits: [],
      qualityGateChecks: [],
      qualityGateReasons: [],
      nextRunId: 1,
      nextArticleId: 1,
      batchCalls: 0
    };
  }

  prepare(sql) {
    return new StatementMock(this, sql);
  }

  async batch(statements) {
    this.state.batchCalls += 1;
    const before = clone(this.state);
    try {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      if (this.options.afterBatch && statements.some((statement) => statement.sql.startsWith("INSERT INTO curation_logs"))) await this.options.afterBatch();
      if (this.options.ambiguousBatchCommit && statements.some((statement) => statement.sql.startsWith("INSERT INTO curation_logs"))) throw new Error("ambiguous after commit");
      return results;
    } catch (error) {
      if (!this.options.ambiguousBatchCommit) this.state = before;
      throw error;
    }
  }

  seedRun(values = {}) {
    const run = {
      id: this.state.nextRunId++,
      execution_id: values.execution_id ?? `seed-${this.state.nextRunId}`,
      idempotency_key: values.idempotency_key ?? `seed:${this.state.nextRunId}`,
      trigger_type: values.trigger_type ?? "manual",
      scheduled_for: values.scheduled_for ?? null,
      status: values.status ?? "running",
      stage: values.stage ?? "gemini",
      article_id: values.article_id ?? null,
      attempt_count: values.attempt_count ?? 1,
      notification_status: values.notification_status ?? "pending",
      notification_attempt_count: values.notification_attempt_count ?? 0,
      error_code: values.error_code ?? null,
      error_http_status: values.error_http_status ?? null,
      error_retryable: values.error_retryable ?? 0,
      error_summary: values.error_summary ?? null,
      lease_expires_at: values.lease_expires_at ?? "2099-01-01T00:00:00.000Z",
      started_at: values.started_at ?? "2026-08-10T00:00:00.000Z",
      updated_at: values.updated_at ?? "2026-08-10T00:00:00.000Z",
      saved_at: values.saved_at ?? null,
      notified_at: values.notified_at ?? null,
      completed_at: values.completed_at ?? null,
      failed_at: values.failed_at ?? null
    };
    this.state.pipelineRuns.push(run);
    return run;
  }

  seedArticle(values = {}) {
    if (values.pipeline_run_id != null && this.state.articles.some(
      (article) => article.pipeline_run_id === values.pipeline_run_id
    )) throw new Error("UNIQUE pipeline_run_id");
    const article = {
      id: this.state.nextArticleId++,
      source_type: values.source_type ?? "test",
      llm_name: values.llm_name ?? "test",
      content: values.content ?? "article",
      created_at: values.created_at ?? "2026-08-10T00:00:00.000Z",
      pipeline_run_id: values.pipeline_run_id ?? null,
      title: values.title ?? null,
      description: values.description ?? null,
      body_markdown: values.body_markdown ?? null,
      category: values.category ?? "uncategorized",
      published_at: values.published_at ?? null,
      updated_at: values.updated_at ?? null,
      seo_status: values.seo_status ?? "legacy"
    };
    this.state.articles.push(article);
    return article;
  }
}

class StatementMock {
  constructor(db, sql) {
    this.db = db;
    this.sql = sql.replace(/\s+/g, " ").trim();
    this.args = [];
  }

  bind(...args) {
    this.args = args;
    return this;
  }

  async first() {
    if (this.sql.includes("FROM pipeline_runs WHERE idempotency_key")) {
      return this.db.state.pipelineRuns.find((run) => run.idempotency_key === this.args[0]) ?? null;
    }
    if (this.sql.includes("FROM curation_logs WHERE pipeline_run_id")) {
      return this.db.state.articles.find((article) => article.pipeline_run_id === this.args[0]) ?? null;
    }
    if (this.sql.startsWith("SELECT (SELECT COUNT(*) FROM pipeline_runs")) {
      if (this.db.options.failBudgetQuery) throw new Error("budget query failed");
      const [dayStart, dayEnd, hourStart, now] = this.args;
      const inRange = (value, start, end) => value >= start && value < end;
      const manualHourly = this.db.state.pipelineRuns.filter((run) =>
        run.trigger_type === "manual" && run.started_at > hourStart && run.started_at <= now
      );
      return {
        daily_total: this.db.state.pipelineRuns.filter((run) => inRange(run.started_at, dayStart, dayEnd)).length,
        active_manual: this.db.state.pipelineRuns.filter((run) =>
          run.trigger_type === "manual" && ["running", "saved"].includes(run.status)
        ).length,
        hourly_manual: manualHourly.length,
        daily_manual: this.db.state.pipelineRuns.filter((run) =>
          run.trigger_type === "manual" && inRange(run.started_at, this.args[4], this.args[5])
        ).length,
        daily_cron: this.db.state.pipelineRuns.filter((run) =>
          run.trigger_type === "cron" && inRange(run.started_at, this.args[6], this.args[7])
        ).length,
        oldest_hourly_manual: manualHourly.map((run) => run.started_at).sort()[0] ?? null
      };
    }
    return null;
  }

  async all() {
    if (this.sql.startsWith("SELECT * FROM curation_logs ORDER BY id DESC LIMIT 5")) {
      return { results: [...this.db.state.articles].sort((left, right) => right.id - left.id).slice(0, 5) };
    }
    return { results: [] };
  }

  async run() {
    const { state, options } = this.db;
    if (this.sql.startsWith("INSERT INTO pipeline_runs")) {
      const [executionId, key, triggerType, scheduledFor, lease, started, updated] = this.args;
      if (state.pipelineRuns.some((run) => run.execution_id === executionId || run.idempotency_key === key)) {
        throw new Error("UNIQUE pipeline run");
      }
      if (this.sql.includes("SELECT ?, ?, ?, ?") && options.failConditionalInsert) {
        throw new Error("conditional insert failed");
      }
      if (this.sql.includes("SELECT ?, ?, ?, ?")) {
        const inRange = (value, start, end) => value >= start && value < end;
        const dailyTotal = state.pipelineRuns.filter((run) => inRange(run.started_at, this.args[7], this.args[8])).length;
        const activeManual = state.pipelineRuns.filter((run) =>
          run.trigger_type === "manual" && ["running", "saved"].includes(run.status)
        ).length;
        const hourlyManual = state.pipelineRuns.filter((run) =>
          run.trigger_type === "manual" && run.started_at > this.args[11] && run.started_at <= this.args[12]
        ).length;
        const dailyManual = state.pipelineRuns.filter((run) =>
          run.trigger_type === "manual" && inRange(run.started_at, this.args[14], this.args[15])
        ).length;
        const dailyCron = state.pipelineRuns.filter((run) =>
          run.trigger_type === "cron" && inRange(run.started_at, this.args[18], this.args[19])
        ).length;
        const allowed = dailyTotal < this.args[9] && (
          (triggerType === "manual" && activeManual < 1 && hourlyManual < this.args[13] && dailyManual < this.args[16]) ||
          (triggerType === "cron" && dailyCron < this.args[20])
        );
        if (!allowed) return { meta: { changes: 0 } };
      }
      const run = this.db.seedRun({
        execution_id: executionId,
        idempotency_key: key,
        trigger_type: triggerType,
        scheduled_for: scheduledFor,
        lease_expires_at: lease,
        started_at: started,
        updated_at: updated
      });
      if (options.ambiguousRunInsert) throw new Error("ambiguous after run insert");
      return { meta: { changes: 1, last_row_id: run.id } };
    }

    if (this.sql.startsWith("INSERT INTO curation_logs")) {
      const [sourceType, llmName, content, createdAt, pipelineRunId,
        title, description, bodyMarkdown, category,
        publishedAt, updatedAt, seoStatus] = this.args;
      if (options.failArticleInsert) throw new Error("article insert failed");
      const article = this.db.seedArticle({
        source_type: sourceType,
        llm_name: llmName,
        content,
        created_at: createdAt,
        pipeline_run_id: pipelineRunId,
        title,
        description,
        body_markdown: bodyMarkdown,
        category,
        published_at: publishedAt,
        updated_at: updatedAt,
        seo_status: seoStatus
      });
      return { meta: { changes: 1, last_row_id: article.id } };
    }

    if (this.sql.startsWith("INSERT INTO quality_gate_audits")) {
      if (options.failQualityGateAudit || state.qualityGateAudits.some((audit) => audit.audit_id === this.args[0] || (audit.pipeline_run_id === this.args[1] && audit.stage === this.args[3]))) throw new Error("quality audit insert failed");
      state.qualityGateAudits.push({ audit_id: this.args[0], pipeline_run_id: this.args[1], schema_version: this.args[2], stage: this.args[3], classification: this.args[4], threshold_version: this.args[5], evaluated_at: this.args[6] });
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("INSERT INTO quality_gate_audit_checks")) {
      if (options.failQualityGateAuditChecks) throw new Error("quality check insert failed");
      state.qualityGateChecks.push({ audit_id: this.args[0], check_name: this.args[1], status: this.args[2] });
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("INSERT INTO quality_gate_audit_reasons")) {
      state.qualityGateReasons.push({ audit_id: this.args[0], reason_code: this.args[1], reason_order: this.args[2] });
      return { meta: { changes: 1 } };
    }

    const runId = this.args.at(-1);
    const run = state.pipelineRuns.find((candidate) => candidate.id === runId);
    if (!run) return { meta: { changes: 0 } };

    if (this.sql.startsWith("UPDATE pipeline_runs SET stage = ?")) {
      if (run.status !== "running") return { meta: { changes: 0 } };
      [run.stage, run.updated_at, run.lease_expires_at] = this.args;
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("SET status = 'failed'")) {
      [run.stage, run.error_code, run.error_http_status, run.error_retryable,
        run.error_summary, run.updated_at, run.failed_at] = this.args;
      run.status = "failed";
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("SET status = 'saved', stage = 'discord', notification_status = 'pending'")) {
      if (run.status !== "running") return { meta: { changes: 0 } };
      run.status = "saved";
      run.stage = "discord";
      run.notification_status = "pending";
      [run.saved_at, run.updated_at] = this.args;
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("SET article_id = ?")) {
      [run.article_id, run.updated_at] = this.args;
      run.status = "saved";
      run.stage = "discord";
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("notification_attempt_count = notification_attempt_count + 1")) {
      if (run.status !== "saved" || !["pending", "failed"].includes(run.notification_status)) {
        return { meta: { changes: 0 } };
      }
      run.notification_status = "sending";
      run.notification_attempt_count += 1;
      [run.updated_at, run.lease_expires_at] = this.args;
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("SET status = 'completed'")) {
      [run.notified_at, run.completed_at, run.updated_at] = this.args;
      run.status = "completed";
      run.stage = "done";
      run.notification_status = "sent";
      run.error_code = null;
      run.error_http_status = null;
      run.error_retryable = 0;
      run.error_summary = null;
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("notification_status = 'failed'")) {
      [run.error_code, run.error_http_status, run.error_retryable,
        run.error_summary, run.updated_at] = this.args;
      run.status = "saved";
      run.stage = "discord";
      run.notification_status = "failed";
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("notification_status = 'sending'") && this.sql.includes("error_code = ?")) {
      [run.error_code, run.error_http_status, run.error_summary, run.updated_at] = this.args;
      run.status = "saved";
      run.stage = "discord";
      run.notification_status = "sending";
      run.error_retryable = 0;
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("saved_at = COALESCE")) {
      [run.article_id, run.saved_at, run.updated_at] = this.args;
      run.status = "saved";
      run.stage = "discord";
      return { meta: { changes: 1 } };
    }
    return { meta: { changes: 0 } };
  }
}
