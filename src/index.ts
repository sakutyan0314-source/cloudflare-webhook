// src/index.ts (Clean ES Module Format - Phase 2 Affiliate Optimization)

const HTML_HEADERS = { "Content-Type": "text/html; charset=utf-8" };
const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };
const TEXT_HEADERS = { "Content-Type": "text/plain; charset=utf-8" };
const PRIVATE_JSON_HEADERS = {
  ...JSON_HEADERS,
  "Cache-Control": "no-store"
};
const PRIVATE_TEXT_HEADERS = {
  ...TEXT_HEADERS,
  "Cache-Control": "no-store"
};
const AUTHORIZATION_HEADER_MAX_LENGTH = 1024;
const EXTERNAL_API_TIMEOUTS = {
  gemini: 45_000,
  claude: 60_000,
  openai: 60_000,
  discord: 10_000
};
const LLM_MAX_ATTEMPTS = 2;
const DISCORD_MAX_ATTEMPTS = 3;
const MAX_RETRY_AFTER_MS = 30_000;
const RETRYABLE_HTTP_STATUSES = new Set([408, 429]);
const PIPELINE_LEASE_MS = 15 * 60 * 1000;
const IDEMPOTENCY_KEY_MAX_LENGTH = 128;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const ERROR_SUMMARY_MAX_LENGTH = 160;

class OperationError extends Error {
  constructor({ stage, provider, errorCode, httpStatus = null, retryable = false, attempt = 1 }) {
    super("Operation failed");
    this.name = "OperationError";
    this.stage = stage;
    this.provider = provider;
    this.errorCode = errorCode;
    this.httpStatus = httpStatus;
    this.retryable = retryable;
    this.attempt = attempt;
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "") {
      return handleHomePage(env, url);
    }
    if (url.pathname === "/sitemap.xml") {
  return handleSitemap(env);
}
function handleRobots(env) {
  try {
    const siteUrl = getSiteUrl(env);
    const body = `User-agent: *
Allow: /

Sitemap: ${siteUrl}/sitemap.xml
`;

    return new Response(body, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=300"
      }
    });
  } catch (error) {
    logOperationFailure(error, "robots", "worker");
    return new Response("Site configuration error.", {
      status: 500,
      headers: TEXT_HEADERS
    });
  }
}
if (url.pathname === "/robots.txt") {
  return handleRobots(env);
}
    const articleMatch = url.pathname.match(/^\/article\/(\d+)\/?$/);

if (articleMatch) {
  return handleArticlePage(env, articleMatch[1]);
}
    if (url.pathname === "/test-multillm") {
      const accessError = await authorizeOperationsRequest(request, env, "POST");
      if (accessError) return accessError;
      return handleTestMultiLlm(request, env);
    }
    if (url.pathname === "/view-logs") {
      const accessError = await authorizeOperationsRequest(request, env, "GET");
      if (accessError) return accessError;
      return handleViewLogs(env);
    }
    if (url.pathname === "/test-discord") {
      const accessError = await authorizeOperationsRequest(request, env, "POST");
      if (accessError) return accessError;
      return handleTestDiscord(env);
    }
    if (url.pathname === "/get-task") {
      return new Response("Not Found", { status: 404, headers: TEXT_HEADERS });
    }
    if (url.pathname === "/test") {
      const accessError = await authorizeOperationsRequest(request, env, "POST");
      if (accessError) return accessError;
      try {
        const report = await sendAutomatedReport(env);
        return new Response(
          `[テスト実行成功] Discordへ通知を送信しました。\n\n${report}`,
          { headers: PRIVATE_TEXT_HEADERS }
        );
      } catch (error) {
        logOperationFailure(error, "test", "worker");
        return new Response("Operation failed", {
          status: 500,
          headers: PRIVATE_TEXT_HEADERS
        });
      }
    }
    return new Response("Not Found", { status: 404, headers: TEXT_HEADERS });
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runScheduledPipeline(env, {}, event.scheduledTime));
  }
};

async function authorizeOperationsRequest(request, env, allowedMethod) {
  if (request.method !== allowedMethod) {
    return new Response(
      JSON.stringify({ status: "error", message: "Method Not Allowed" }),
      {
        status: 405,
        headers: {
          ...PRIVATE_JSON_HEADERS,
          "Allow": allowedMethod
        }
      }
    );
  }

  const expectedToken = env?.OPERATIONS_API_TOKEN;
  if (typeof expectedToken !== "string" || expectedToken.length === 0) {
    return new Response(
      JSON.stringify({ status: "error", message: "Service Unavailable" }),
      { status: 503, headers: PRIVATE_JSON_HEADERS }
    );
  }

  const authorization = request.headers.get("Authorization");
  if (
    typeof authorization !== "string" ||
    authorization.length > AUTHORIZATION_HEADER_MAX_LENGTH
  ) {
    return unauthorizedResponse();
  }

  const match = authorization.match(/^Bearer ([^\s]+)$/i);
  if (!match || !(await tokensMatch(match[1], expectedToken))) {
    return unauthorizedResponse();
  }

  return null;
}

function unauthorizedResponse() {
  return new Response(
    JSON.stringify({ status: "error", message: "Unauthorized" }),
    {
      status: 401,
      headers: {
        ...PRIVATE_JSON_HEADERS,
        "WWW-Authenticate": "Bearer"
      }
    }
  );
}

async function tokensMatch(receivedToken, expectedToken) {
  const encoder = new TextEncoder();
  const [receivedDigest, expectedDigest] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(receivedToken)),
    crypto.subtle.digest("SHA-256", encoder.encode(expectedToken))
  ]);
  const receivedBytes = new Uint8Array(receivedDigest);
  const expectedBytes = new Uint8Array(expectedDigest);
  let difference = 0;

  for (let index = 0; index < receivedBytes.length; index += 1) {
    difference |= receivedBytes[index] ^ expectedBytes[index];
  }

  return difference === 0;
}

async function handleHomePage(env, url) {
  try {
    const siteUrl = getSiteUrl(env);
    const pageParam = parseInt(url.searchParams.get("page") || "1", 10);
    const currentPage = Number.isNaN(pageParam) || pageParam < 1 ? 1 : pageParam;
    const perPage = 5;
    const offset = (currentPage - 1) * perPage;
    const countResult = await env.DB.prepare(
      "SELECT COUNT(*) as total FROM curation_logs"
    ).first();
    const totalItems = countResult?.total ?? 0;
    const totalPages = Math.ceil(totalItems / perPage) || 1;
    if (currentPage > totalPages) {
      return new Response("ページが見つかりません。", {
        status: 404,
        headers: TEXT_HEADERS
      });
    }
    const { results } = await env.DB.prepare(
      "SELECT * FROM curation_logs ORDER BY id DESC LIMIT ? OFFSET ?"
    ).bind(perPage, offset).all();
    const affiliateTag = env.AMAZON_TAG || "default-22";
    const html = renderHomePage(results ?? [], {
      affiliateTag,
      currentPage,
      totalPages,
      totalItems,
      siteUrl
    });
    return new Response(html, { headers: HTML_HEADERS });
  } catch (error) {
    logOperationFailure(error, "home_page", "worker");
    return new Response("サイトの読み込み中にエラーが発生しました。", {
      status: 500,
      headers: TEXT_HEADERS
    });
  }
}
async function handleArticlePage(env, articleId) {
  try {
    const siteUrl = getSiteUrl(env);
    const id = Number.parseInt(articleId, 10);

    if (!Number.isInteger(id) || id < 1) {
      return new Response("記事IDが正しくありません。", {
        status: 400,
        headers: TEXT_HEADERS
      });
    }

    const row = await env.DB.prepare(
      "SELECT id, content, created_at FROM curation_logs WHERE id = ? LIMIT 1"
    ).bind(id).first();

    if (!row) {
      return new Response(
        `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>記事が見つかりません</title>
</head>
<body>
  <h1>記事が見つかりませんでした。</h1>
  <p><a href="/">トップページへ戻る</a></p>
</body>
</html>`,
        {
          status: 404,
          headers: HTML_HEADERS
        }
      );
    }

    const content = String(row.content || "");
    const firstLine =
      content.split(/\r?\n/).find((line) => line.trim()) || `記事 ${id}`;

    const pageTitle = firstLine
      .replace(/^#+\s*/, "")
      .slice(0, 80);

    const dateStr = new Date(row.created_at).toLocaleString("ja-JP");

    const affiliateTag = env.AMAZON_TAG || "default-22";
    const keyword = determineAffiliateKeyword(content);

    const affiliateUrl =
      `https://www.amazon.co.jp/s?k=${encodeURIComponent(keyword)}&tag=${encodeURIComponent(affiliateTag)}`;
const canonicalUrl = `${siteUrl}/article/${id}`;
const description = content.replace(/[#>*_`\[\]\(\)]/g, "").replace(/\s+/g, " ").trim().slice(0, 160);
    const html = `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(pageTitle)}</title>
  <meta name="description" content="${escapeHtml(description)}">
<link rel="canonical" href="${canonicalUrl}">

<meta property="og:type" content="article">
<meta property="og:title" content="${escapeHtml(pageTitle)}">
<meta property="og:description" content="${escapeHtml(description)}">
<meta property="og:url" content="${canonicalUrl}">
<meta property="og:site_name" content="テクノロジー＆ビジネストレンド最速まとめ速報">

<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="${escapeHtml(pageTitle)}">
<meta name="twitter:description" content="${escapeHtml(description)}">
<script type="application/ld+json">
${JSON.stringify({
  "@context": "https://schema.org",
  "@type": "Article",
  headline: pageTitle,
  description: description,
  datePublished: row.created_at,
  dateModified: row.created_at,
  mainEntityOfPage: {
    "@type": "WebPage",
    "@id": canonicalUrl
  },
  url: canonicalUrl
}).replace(/</g, "\\u003c")}
</script>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: #f7f9fa;
      color: #222;
      margin: 0;
      padding: 20px;
    }

    .container {
      max-width: 800px;
      margin: 0 auto;
      background: #fff;
      padding: 30px;
      border-radius: 8px;
    }

    .back-link {
      display: inline-block;
      margin-bottom: 20px;
    }

    h1 {
      font-size: 26px;
      line-height: 1.5;
    }

    .meta {
      color: #888;
      font-size: 13px;
      margin-bottom: 25px;
    }

    .content {
      white-space: pre-line;
      line-height: 1.9;
      font-size: 16px;
    }

    .affiliate-box {
      margin-top: 30px;
      padding: 15px;
      background: #fffbf0;
      border: 1px solid #ffeeba;
      border-radius: 6px;
    }
  </style>
</head>
<body>
  <main class="container">
    <a class="back-link" href="/">← 記事一覧へ戻る</a>

    <article>
      <h1>${escapeHtml(pageTitle)}</h1>

      <div class="meta">
        更新日時: ${escapeHtml(dateStr)}
      </div>

      <div class="content">${escapeHtml(content)}</div>

      <div class="affiliate-box">
        🛒 厳選おすすめ関連アイテム（${escapeHtml(keyword)}）：
        <a
          href="${escapeHtml(affiliateUrl)}"
          target="_blank"
          rel="nofollow"
        >Amazonで最新商品をチェックする</a>
      </div>
    </article>
  </main>
</body>
</html>`;

    return new Response(html, {
      headers: HTML_HEADERS
    });

  } catch (error) {
    logOperationFailure(error, "article_page", "worker");

    return new Response(
      "記事の読み込み中にエラーが発生しました。",
      {
        status: 500,
        headers: TEXT_HEADERS
      }
    );
  }
}
async function handleTestMultiLlm(request, env, runtime = {}) {
  const rawKey = request.headers.get("Idempotency-Key");
  const keyError = validateManualIdempotencyKey(rawKey);
  if (keyError) {
    return new Response(
      JSON.stringify({ status: "error", message: keyError }),
      { status: 400, headers: PRIVATE_JSON_HEADERS }
    );
  }

  try {
    const result = await runReliablePipeline(env, {
      triggerType: "manual",
      idempotencyKey: `manual:${rawKey}`,
      scheduledFor: null,
      sourceType: "pro_consensus_summary",
      discordHeader: null
    }, runtime);
    return new Response(
      JSON.stringify({
        status: result.outcome,
        pipelineRunId: result.runId,
        articleId: result.articleId ?? null
      }, null, 2),
      { headers: PRIVATE_JSON_HEADERS }
    );
  } catch (error) {
    logOperationFailure(error, "test_multillm", "worker");
    return new Response(JSON.stringify({ status: "error", message: "Operation failed" }, null, 2), {
      status: 500,
      headers: PRIVATE_JSON_HEADERS
    });
  }
}

async function handleViewLogs(env) {
  try {
    const { results } = await env.DB.prepare(
      "SELECT * FROM curation_logs ORDER BY id DESC LIMIT 20"
    ).all();
    return new Response(
      JSON.stringify({ status: "success", logs: results }, null, 2),
      { headers: PRIVATE_JSON_HEADERS }
    );
  } catch (error) {
    logOperationFailure(error, "view_logs", "d1");
    return new Response(JSON.stringify({ status: "error", message: "Operation failed" }, null, 2), {
      status: 500,
      headers: PRIVATE_JSON_HEADERS
    });
  }
}

async function handleTestDiscord(env) {
  try {
    const { results } = await env.DB.prepare(
      "SELECT * FROM curation_logs ORDER BY id DESC LIMIT 1"
    ).all();
    if (!results || results.length === 0) {
      return new Response(
        JSON.stringify({ status: "error", message: "No logs found in D1." }, null, 2),
        { status: 404, headers: PRIVATE_JSON_HEADERS }
      );
    }
    const latestLog = results[0];
    const message = buildDiscordMessage(latestLog.content, latestLog.created_at, env.AMAZON_TAG);
    const discordRes = await sendToDiscord(env.DISCORD_WEBHOOK_URL, message);
    return new Response(
      JSON.stringify({ status: "discord_sent_success", discordResponse: discordRes }, null, 2),
      { headers: PRIVATE_JSON_HEADERS }
    );
  } catch (error) {
    logOperationFailure(error, "test_discord", "worker");
    return new Response(JSON.stringify({ status: "error", message: "Operation failed" }, null, 2), {
      status: 500,
      headers: PRIVATE_JSON_HEADERS
    });
  }
}

async function runScheduledPipeline(env, runtime = {}, scheduledTime = Date.now()) {
  console.log("Cron triggered: Running Deep Pro-Consensus pipeline...");
  try {
    const normalizedScheduledTime = normalizeScheduledTime(scheduledTime);
    return await runReliablePipeline(env, {
      triggerType: "cron",
      idempotencyKey: `cron:${normalizedScheduledTime.key}`,
      scheduledFor: normalizedScheduledTime.iso,
      sourceType: "cron_pro_consensus",
      discordHeader: "🚀 **【自動速報配信（ビジネストレンド）】**"
    }, runtime);
  } catch (error) {
    logOperationFailure(error, "scheduled_pipeline", "worker");
    throw normalizeOperationError(error, "scheduled_pipeline", "worker");
  }
}

function validateManualIdempotencyKey(value) {
  if (typeof value !== "string" || value.length === 0) return "Idempotency-Key is required";
  if (value.trim() !== value || !IDEMPOTENCY_KEY_PATTERN.test(value)) {
    return "Invalid Idempotency-Key";
  }
  if (value.length > IDEMPOTENCY_KEY_MAX_LENGTH) return "Invalid Idempotency-Key";
  return null;
}

function normalizeScheduledTime(value) {
  const milliseconds = Number(value);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) {
    throw new OperationError({
      stage: "pipeline_acquire",
      provider: "worker",
      errorCode: "invalid_scheduled_time"
    });
  }
  const wholeMilliseconds = Math.trunc(milliseconds);
  return {
    key: String(wholeMilliseconds),
    iso: new Date(wholeMilliseconds).toISOString()
  };
}

function runtimeNow(runtime = {}) {
  const value = runtime.now ? runtime.now() : new Date();
  return value instanceof Date ? value : new Date(value);
}

function addMilliseconds(date, milliseconds) {
  return new Date(date.getTime() + milliseconds).toISOString();
}

function createExecutionId(runtime = {}) {
  if (runtime.randomUUID) return runtime.randomUUID();
  return crypto.randomUUID();
}

function statementChanges(result) {
  return Number(result?.meta?.changes ?? result?.changes ?? 0);
}

async function getPipelineRunByKey(db, idempotencyKey) {
  return db.prepare(
    "SELECT * FROM pipeline_runs WHERE idempotency_key = ? LIMIT 1"
  ).bind(idempotencyKey).first();
}

async function getArticleForRun(db, runId) {
  return db.prepare(
    "SELECT id, content, created_at, pipeline_run_id FROM curation_logs WHERE pipeline_run_id = ? LIMIT 1"
  ).bind(runId).first();
}

async function acquirePipelineRun(db, specification, runtime = {}) {
  if (!db) {
    throw new OperationError({
      stage: "pipeline_acquire",
      provider: "d1",
      errorCode: "binding_missing"
    });
  }
  const now = runtimeNow(runtime);
  const nowIso = now.toISOString();
  const executionId = createExecutionId(runtime);
  const leaseExpiresAt = addMilliseconds(now, PIPELINE_LEASE_MS);

  try {
    await db.prepare(
      `INSERT INTO pipeline_runs (
        execution_id, idempotency_key, trigger_type, scheduled_for,
        status, stage, attempt_count, notification_status,
        lease_expires_at, started_at, updated_at
      ) VALUES (?, ?, ?, ?, 'running', 'gemini', 1, 'pending', ?, ?, ?)`
    ).bind(
      executionId,
      specification.idempotencyKey,
      specification.triggerType,
      specification.scheduledFor,
      leaseExpiresAt,
      nowIso,
      nowIso
    ).run();
  } catch {
    // UNIQUE conflicts and ambiguous write results are resolved by reading the key.
  }

  const run = await getPipelineRunByKey(db, specification.idempotencyKey);
  if (!run) {
    throw new OperationError({
      stage: "pipeline_acquire",
      provider: "d1",
      errorCode: "write_failed"
    });
  }
  return { run, acquired: run.execution_id === executionId };
}

async function updateRunStage(db, runId, stage, runtime = {}) {
  const now = runtimeNow(runtime);
  await db.prepare(
    "UPDATE pipeline_runs SET stage = ?, updated_at = ?, lease_expires_at = ? WHERE id = ? AND status = 'running'"
  ).bind(stage, now.toISOString(), addMilliseconds(now, PIPELINE_LEASE_MS), runId).run();
}

function safeErrorSummary(error) {
  const safe = normalizeOperationError(error, "pipeline", "worker");
  return `${safe.provider}:${safe.errorCode}`.slice(0, ERROR_SUMMARY_MAX_LENGTH);
}

async function markPipelineFailed(db, runId, error, stage, runtime = {}) {
  const safe = normalizeOperationError(error, stage, "worker");
  const nowIso = runtimeNow(runtime).toISOString();
  await db.prepare(
    `UPDATE pipeline_runs
     SET status = 'failed', stage = ?, error_code = ?, error_http_status = ?,
         error_retryable = ?, error_summary = ?, updated_at = ?, failed_at = ?
     WHERE id = ?`
  ).bind(
    stage,
    safe.errorCode,
    safe.httpStatus,
    safe.retryable ? 1 : 0,
    safeErrorSummary(safe),
    nowIso,
    nowIso,
    runId
  ).run();
}

async function saveArticleAndMarkSaved(db, run, specification, article, runtime = {}) {
  const nowIso = runtimeNow(runtime).toISOString();
  const insertStatement = db.prepare(
    `INSERT INTO curation_logs
      (source_type, llm_name, content, created_at, pipeline_run_id)
     VALUES (?, ?, ?, ?, ?)`
  ).bind(
    specification.sourceType,
    "Pro-Consensus Pipeline",
    article,
    nowIso,
    run.id
  );
  const updateStatement = db.prepare(
    `UPDATE pipeline_runs
     SET status = 'saved', stage = 'discord', notification_status = 'pending',
         saved_at = ?, updated_at = ?
     WHERE id = ? AND status = 'running'`
  ).bind(nowIso, nowIso, run.id);

  try {
    if (typeof db.batch !== "function") {
      throw new Error("D1 batch unavailable");
    }
    await db.batch([insertStatement, updateStatement]);
  } catch {
    const existingArticle = await getArticleForRun(db, run.id);
    if (!existingArticle) {
      throw new OperationError({
        stage: "d1_save",
        provider: "d1",
        errorCode: "write_failed"
      });
    }
  }

  const savedArticle = await getArticleForRun(db, run.id);
  if (!savedArticle) {
    throw new OperationError({
      stage: "d1_save",
      provider: "d1",
      errorCode: "ambiguous_write"
    });
  }
  await db.prepare(
    "UPDATE pipeline_runs SET article_id = ?, status = 'saved', stage = 'discord', updated_at = ? WHERE id = ?"
  ).bind(savedArticle.id, nowIso, run.id).run();
  return savedArticle;
}

async function claimNotification(db, runId, runtime = {}) {
  const now = runtimeNow(runtime);
  const result = await db.prepare(
    `UPDATE pipeline_runs
     SET notification_status = 'sending', notification_attempt_count = notification_attempt_count + 1,
         updated_at = ?, lease_expires_at = ?
     WHERE id = ? AND status = 'saved' AND notification_status IN ('pending', 'failed')`
  ).bind(now.toISOString(), addMilliseconds(now, PIPELINE_LEASE_MS), runId).run();
  return statementChanges(result) === 1;
}

async function sendSavedArticleNotification(env, run, article, specification, runtime = {}) {
  const claimed = await claimNotification(env.DB, run.id, runtime);
  if (!claimed) return { outcome: "duplicate", runId: run.id, articleId: article.id };

  const message = buildDiscordMessage(
    article.content,
    article.created_at,
    env.AMAZON_TAG,
    specification.discordHeader || undefined
  );
  try {
    await sendToDiscord(env.DISCORD_WEBHOOK_URL, message, runtime);
    const nowIso = runtimeNow(runtime).toISOString();
    await env.DB.prepare(
      `UPDATE pipeline_runs
       SET status = 'completed', stage = 'done', notification_status = 'sent',
           notified_at = ?, completed_at = ?, updated_at = ?,
           error_code = NULL, error_http_status = NULL, error_retryable = 0, error_summary = NULL
       WHERE id = ? AND status = 'saved' AND notification_status = 'sending'`
    ).bind(nowIso, nowIso, nowIso, run.id).run();
    return { outcome: "completed", runId: run.id, articleId: article.id };
  } catch (error) {
    const safe = normalizeOperationError(error, "discord", "discord");
    const nowIso = runtimeNow(runtime).toISOString();
    await env.DB.prepare(
      `UPDATE pipeline_runs
       SET status = 'saved', stage = 'discord', notification_status = 'failed',
           error_code = ?, error_http_status = ?, error_retryable = ?, error_summary = ?, updated_at = ?
       WHERE id = ?`
    ).bind(
      safe.errorCode,
      safe.httpStatus,
      safe.retryable ? 1 : 0,
      safeErrorSummary(safe),
      nowIso,
      run.id
    ).run();
    throw safe;
  }
}

async function handleExistingPipelineRun(env, run, specification, runtime = {}) {
  if (run.status === "completed" || run.status === "failed") {
    return { outcome: run.status, runId: run.id, articleId: run.article_id ?? null };
  }

  const article = await getArticleForRun(env.DB, run.id);
  if (article) {
    if (run.notification_status === "sending") {
      return { outcome: "notification_in_progress", runId: run.id, articleId: article.id };
    }
    if (run.status === "running") {
      const nowIso = runtimeNow(runtime).toISOString();
      await env.DB.prepare(
        "UPDATE pipeline_runs SET status = 'saved', stage = 'discord', article_id = ?, saved_at = COALESCE(saved_at, ?), updated_at = ? WHERE id = ?"
      ).bind(article.id, nowIso, nowIso, run.id).run();
      run = await getPipelineRunByKey(env.DB, specification.idempotencyKey);
    }
    if (run.notification_status === "sent") {
      return { outcome: "completed", runId: run.id, articleId: article.id };
    }
    if (run.notification_status === "sending") {
      return { outcome: "notification_in_progress", runId: run.id, articleId: article.id };
    }
    return sendSavedArticleNotification(env, run, article, specification, runtime);
  }

  if (run.status === "running" && Date.parse(run.lease_expires_at) <= runtimeNow(runtime).getTime()) {
    const staleError = new OperationError({
      stage: run.stage,
      provider: "worker",
      errorCode: "stale_run_requires_reconciliation"
    });
    await markPipelineFailed(env.DB, run.id, staleError, run.stage, runtime);
    return { outcome: "failed", runId: run.id, articleId: null };
  }
  return { outcome: "in_progress", runId: run.id, articleId: null };
}

async function runReliablePipeline(env, specification, runtime = {}) {
  const acquisition = await acquirePipelineRun(env.DB, specification, runtime);
  if (!acquisition.acquired) {
    return handleExistingPipelineRun(env, acquisition.run, specification, runtime);
  }

  const run = acquisition.run;
  let stage = "gemini";
  try {
    await updateRunStage(env.DB, run.id, "gemini", runtime);
    const draft = await callGemini(env.GEMINI_API_KEY, runtime);
    stage = "claude";
    await updateRunStage(env.DB, run.id, stage, runtime);
    const reviewed = await callClaude(env.CLAUDE_API_KEY, draft, runtime);
    stage = "openai";
    await updateRunStage(env.DB, run.id, stage, runtime);
    const finalArticle = await callOpenAI(env.OPENAI_API_KEY, reviewed, runtime);
    stage = "d1_save";
    await updateRunStage(env.DB, run.id, stage, runtime);
    const savedArticle = await saveArticleAndMarkSaved(env.DB, run, specification, finalArticle, runtime);
    return await sendSavedArticleNotification(env, { ...run, status: "saved" }, savedArticle, specification, runtime);
  } catch (error) {
    const existingArticle = await getArticleForRun(env.DB, run.id);
    if (!existingArticle) await markPipelineFailed(env.DB, run.id, error, stage, runtime);
    throw normalizeOperationError(error, stage, stage === "d1_save" ? "d1" : stage);
  }
}

async function runProConsensusPipeline(env, runtime = {}) {
  const draft = await callGemini(env.GEMINI_API_KEY, runtime);
  const reviewed = await callClaude(env.CLAUDE_API_KEY, draft, runtime);
  return callOpenAI(env.OPENAI_API_KEY, reviewed, runtime);
}

function buildDiscordMessage(content, createdAt, amazonTag, header = "📢 **【テクノロジー＆ビジネストレンド速報】**") {
  const affiliateTag = amazonTag || "default-22";
  const keyword = determineAffiliateKeyword(content);
  const encodedKeyword = encodeURIComponent(keyword);
  const affiliateLink = `\n\n🛒 **おすすめアイテム（${keyword}）:** https://www.amazon.co.jp/s?k=${encodedKeyword}&tag=${affiliateTag}`;
  return `${header}\n- **日時:** ${createdAt}\n\n${content}${affiliateLink}`;
}

function renderHomePage(results, options) {
  const { affiliateTag, currentPage, totalPages, totalItems, siteUrl } = options;
  const canonicalUrl = currentPage === 1 ? `${siteUrl}/` : `${siteUrl}/?page=${currentPage}`;
  const pageSuffix = currentPage === 1 ? "" : ` | ${currentPage}ページ目`;
  const pageTitle = `テクノロジー＆ビジネストレンド最速まとめ速報${pageSuffix}`;
  const pageDescription = `AI、SaaS、セキュリティ、次世代インフラなど、最新のテクノロジーとビジネストレンドを分析・整理してお届けする情報メディアです。${currentPage === 1 ? "" : `現在は${currentPage}ページ目です。`}`;
  const previousUrl = currentPage === 2 ? `${siteUrl}/` : `${siteUrl}/?page=${currentPage - 1}`;
  const nextUrl = `${siteUrl}/?page=${currentPage + 1}`;
  const postsHtml = results.length > 0 ? results.map((row) => {
    const dateStr = new Date(row.created_at).toLocaleString("ja-JP");
    const keyword = determineAffiliateKeyword(row.content);
    const encodedKeyword = encodeURIComponent(keyword);
    const dynamicAffiliateUrl = `https://www.amazon.co.jp/s?k=${encodedKeyword}&tag=${escapeHtml(affiliateTag)}`;

    return `
          <div class="post">
            <div class="meta">
              <span>更新日時: ${escapeHtml(dateStr)}</span>
            </div>
            <div class="content">${escapeHtml(row.content)}</div>
            <div class="read-more">
              <a href="/article/${escapeHtml(String(row.id))}">続きを読む &rarr;</a>
            </div>
            <div class="affiliate-box">
              🛒 厳選おすすめ関連アイテム（${escapeHtml(keyword)}）: <a href="${dynamicAffiliateUrl}" target="_blank" rel="nofollow">Amazonで最新商品をチェックする</a>
            </div>
          </div>
        `;
  }).join("") : "<p>現在、蓄積されたデータはありません。</p>";

  return `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="google-site-verification" content="C2B44UChRSmhG5t80sCnRQg8q-sCGNQ84fBQPBJPzjk" />
  <title>${escapeHtml(pageTitle)}</title>
  <meta name="description" content="${escapeHtml(pageDescription)}">
<link rel="canonical" href="${canonicalUrl}">
${currentPage > 1 ? `<link rel="prev" href="${previousUrl}">` : ""}
${currentPage < totalPages ? `<link rel="next" href="${nextUrl}">` : ""}

<meta property="og:type" content="website">
<meta property="og:title" content="${escapeHtml(pageTitle)}">
<meta property="og:description" content="${escapeHtml(pageDescription)}">
<meta property="og:url" content="${canonicalUrl}">
<meta property="og:site_name" content="テクノロジー＆ビジネストレンド最速まとめ速報">

<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="${escapeHtml(pageTitle)}">
<meta name="twitter:description" content="${escapeHtml(pageDescription)}">
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: #f7f9fa; color: #333; margin: 0; padding: 20px; }
    .container { max-width: 800px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
    h1 { font-size: 24px; border-bottom: 2px solid #eaeaea; padding-bottom: 10px; margin-top: 0; color: #111; }
    .post { border-bottom: 1px solid #eee; padding: 25px 0; }
    .post:last-child { border-bottom: none; }
    .meta { font-size: 12px; color: #888; margin-bottom: 10px; display: flex; gap: 15px; align-items: center; }
    .content { font-size: 15px; line-height: 1.8; color: #222; margin-bottom: 15px; white-space: pre-line; }
    .read-more { margin-bottom: 15px; }
    .read-more a { color: #0070f3; text-decoration: none; font-size: 14px; font-weight: bold; }
    .read-more a:hover { text-decoration: underline; }
    .affiliate-box { background: #fffbf0; border: 1px solid #ffeeba; padding: 12px 15px; border-radius: 6px; font-size: 13px; }
    .affiliate-box a { color: #b12704; text-decoration: none; font-weight: bold; }
    .affiliate-box a:hover { text-decoration: underline; }
    .pagination { display: flex; justify-content: space-between; align-items: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eaeaea; font-size: 14px; }
    .pagination a { background: #0070f3; color: #fff; padding: 8px 16px; border-radius: 4px; text-decoration: none; font-weight: bold; }
    .pagination a:hover { background: #0051a2; }
    .pagination span { color: #666; }
    .pagination .disabled { background: #ccc; pointer-events: none; }
    .footer { text-align: center; font-size: 12px; color: #aaa; margin-top: 40px; border-top: 1px solid #eaeaea; padding-top: 15px; }
    .compliance-box { background: #fdfdfd; border: 1px solid #e5e5e5; padding: 12px 15px; border-radius: 6px; font-size: 11px; color: #666; text-align: left; margin-bottom: 20px; line-height: 1.6; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🔥 テクノロジー＆ビジネストレンド最速まとめ速報</h1>
    <p style="font-size: 13px; color: #666;">ビジネスパーソン必見。AI、SaaS、セキュリティ、次世代インフラなど、最先端のビジネス動向を深く鋭く分析し、実務に直結する熱の高いインサイトをお届けします。</p>
    <div class="posts">${postsHtml}</div>
    <div class="pagination">
      ${currentPage > 1 ? `<a href="/?page=${currentPage - 1}">&larr; 前のページへ</a>` : `<span class="disabled">&larr; 前のページへ</span>`}
      <span>ページ ${currentPage} / ${totalPages} (全 ${totalItems} 記事)</span>
      ${currentPage < totalPages ? `<a href="/?page=${currentPage + 1}">次のページへ &rarr;</a>` : `<span class="disabled">次のページへ &rarr;</span>`}
    </div>
    <div class="footer">
      <div class="compliance-box">
        <strong>【アフィリエイト・AI利用についてのご案内】</strong><br>
        当サイトに掲載されている情報には、Amazonアソシエイト・プログラムによる適格販売リンクが含まれています。<br>
        （Amazonのアソシエイトとして、当サイトは適格販売により収入を得ています。）<br>
        また、当サイトの記事コンテンツや要約の一部にはAI技術を活用しています。
      </div>
      &copy; 2026 ゼロキャピタル・自動トレンドまとめ速報 All Rights Reserved.
    </div>
  </div>
</body>
</html>`;
}
async function handleSitemap(env) {
  try {
    const siteUrl = getSiteUrl(env);
    const { results } = await env.DB.prepare(
      "SELECT id, created_at FROM curation_logs ORDER BY id DESC LIMIT 1000"
    ).all();

    const articleUrls = (results ?? []).map((row) => {
      const lastmod = row.created_at
        ? new Date(row.created_at).toISOString()
        : new Date().toISOString();

      return `
  <url>
    <loc>${siteUrl}/article/${row.id}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>`;
    }).join("");

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>${siteUrl}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
${articleUrls}
</urlset>`;

    return new Response(xml, {
      headers: {
        "Content-Type": "application/xml; charset=utf-8",
        "Cache-Control": "public, max-age=300"
      }
    });
  } catch (error) {
    logOperationFailure(error, "sitemap", "worker");
    return new Response("Sitemap generation error.", {
      status: 500,
      headers: TEXT_HEADERS
    });
  }
}
function determineAffiliateKeyword(content) {
  if (!content) return "ビジネス変革 DX 成功法則";
  const lower = content.toLowerCase();

  // 1. セキュリティ・ガバナンス系
  if (lower.includes("セキュリティ") || lower.includes("サイバー") || lower.includes("ガバナンス") || lower.includes("リスク")) {
    return "情報セキュリティ 対策 実務";
  }
  // 2. クラウド・インフラ系
  if (lower.includes("saas") || lower.includes("クラウド") || lower.includes("インフラ") || lower.includes("サーバー")) {
    return "クラウドインフラ 構築 運用";
  }
  // 3. 組織マネジメント・リーダーシップ系
  if (lower.includes("マネジメント") || lower.includes("組織") || lower.includes("リーダーシップ") || lower.includes("人材")) {
    return "マネジメント 組織改革 書籍";
  }
  // 4. マーケティング・CX系
  if (lower.includes("マーケティング") || lower.includes("cx") || lower.includes("顧客") || lower.includes("sales")) {
    return "デジタルマーケティング 実践手法";
  }
  // 5. ソフトウェア開発・エンジニアリング系
  if (lower.includes("プログラミング") || lower.includes("開発") || lower.includes("エンジニア") || lower.includes("アーキテクチャ")) {
    return "ソフトウェア設計 開発手法";
  }
  // 6. AI・自動化・最先端トレンド系
  if (lower.includes("ai") || lower.includes("人工知能") || lower.includes("自動化") || lower.includes("エージェント") || lower.includes("生成ai")) {
    return "生成AI ビジネス活用 実践";
  }

  // デフォルト
  return "ビジネス変革 DX 成功法則";
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function getSiteUrl(env) {
  const rawSiteUrl = env?.SITE_URL;

  if (typeof rawSiteUrl !== "string" || rawSiteUrl.trim() === "") {
    throw new Error("SITE_URL configuration is invalid.");
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(rawSiteUrl);
  } catch {
    throw new Error("SITE_URL configuration is invalid.");
  }

  if (
    parsedUrl.protocol !== "https:" ||
    parsedUrl.username !== "" ||
    parsedUrl.password !== "" ||
    parsedUrl.pathname !== "/" ||
    parsedUrl.search !== "" ||
    parsedUrl.hash !== ""
  ) {
    throw new Error("SITE_URL configuration is invalid.");
  }

  return parsedUrl.origin;
}

function isRetryableHttpStatus(status) {
  return RETRYABLE_HTTP_STATUSES.has(status) || (status >= 500 && status <= 599);
}

function parseRetryAfter(value, nowMs = Date.now()) {
  if (typeof value !== "string" || value.trim() === "") return null;
  const trimmed = value.trim();
  const seconds = Number(trimmed);

  if (Number.isFinite(seconds)) {
    return seconds >= 0
      ? Math.min(Math.round(seconds * 1000), MAX_RETRY_AFTER_MS)
      : null;
  }

  const dateMs = Date.parse(trimmed);
  if (!Number.isFinite(dateMs)) return null;
  return Math.min(Math.max(dateMs - nowMs, 0), MAX_RETRY_AFTER_MS);
}

function retryDelayMs(error, attempt, runtime) {
  if (Number.isFinite(error.retryAfterMs)) return error.retryAfterMs;
  const random = runtime.random ?? Math.random;
  return Math.min(250 * (2 ** (attempt - 1)) + Math.floor(random() * 250), MAX_RETRY_AFTER_MS);
}

function defaultSleep(delayMs) {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

function normalizeOperationError(error, stage, provider, attempt = 1) {
  if (error instanceof OperationError) return error;
  return new OperationError({
    stage,
    provider,
    errorCode: "unexpected_error",
    retryable: false,
    attempt
  });
}

function logOperationFailure(error, fallbackStage, fallbackProvider) {
  const safeError = normalizeOperationError(error, fallbackStage, fallbackProvider);
  console.error("Operation failure", {
    stage: safeError.stage,
    provider: safeError.provider,
    error_code: safeError.errorCode,
    http_status: safeError.httpStatus,
    retryable: safeError.retryable,
    attempt: safeError.attempt
  });
}

function requireProviderSecret(value, provider, stage) {
  if (typeof value !== "string" || value.length === 0) {
    throw new OperationError({
      stage,
      provider,
      errorCode: "configuration_missing"
    });
  }
}

async function parseJsonResponse(response, provider, stage, signal) {
  try {
    return await response.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new OperationError({
      stage,
      provider,
      errorCode: "invalid_json"
    });
  }
}

function requireResponseText(value, provider, stage) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new OperationError({
      stage,
      provider,
      errorCode: "invalid_response"
    });
  }
  return value.trim();
}

async function requestWithRetry(options, runtime = {}) {
  const fetchImpl = runtime.fetch ?? fetch;
  const sleep = runtime.sleep ?? defaultSleep;

  for (let attempt = 1; attempt <= options.maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeoutMs);
    let operationError;

    try {
      const response = await fetchImpl(options.url, {
        ...options.init,
        signal: controller.signal
      });

      if (response.ok) {
        return options.consumeResponse
          ? await options.consumeResponse(response, controller.signal)
          : response;
      }

      operationError = new OperationError({
        stage: options.stage,
        provider: options.provider,
        errorCode: "http_error",
        httpStatus: response.status,
        retryable: isRetryableHttpStatus(response.status),
        attempt
      });
      operationError.retryAfterMs = parseRetryAfter(response.headers?.get("Retry-After"));
      if (response.body && typeof response.body.cancel === "function") {
        await response.body.cancel().catch(() => {});
      }
    } catch (error) {
      operationError = error instanceof OperationError
        ? error
        : new OperationError({
          stage: options.stage,
          provider: options.provider,
          errorCode: controller.signal.aborted ? "timeout" : "network_error",
          retryable: true,
          attempt
        });
    } finally {
      clearTimeout(timer);
    }

    if (!operationError.retryable || attempt >= options.maxAttempts) {
      throw operationError;
    }

    await sleep(retryDelayMs(operationError, attempt, runtime));
  }

  throw new OperationError({
    stage: options.stage,
    provider: options.provider,
    errorCode: "retry_exhausted"
  });
}

async function sendToDiscord(webhookUrl, content, runtime = {}) {
  if (!webhookUrl) {
    throw new OperationError({
      stage: "discord",
      provider: "discord",
      errorCode: "configuration_missing"
    });
  }
  await requestWithRetry({
    provider: "discord",
    stage: "discord",
    url: webhookUrl,
    init: {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content })
    },
    timeoutMs: runtime.timeouts?.discord ?? EXTERNAL_API_TIMEOUTS.discord,
    maxAttempts: DISCORD_MAX_ATTEMPTS
  }, runtime);
  return "Message sent successfully to Discord.";
}

async function saveToD1(db, sourceType, llmName, content, createdAt) {
  if (!db) {
    throw new OperationError({
      stage: "d1_save",
      provider: "d1",
      errorCode: "binding_missing"
    });
  }
  try {
    await db.prepare(
      "INSERT INTO curation_logs (source_type, llm_name, content, created_at) VALUES (?, ?, ?, ?)"
    ).bind(sourceType, llmName, content, createdAt).run();
  } catch (error) {
    throw new OperationError({
      stage: "d1_save",
      provider: "d1",
      errorCode: "write_failed"
    });
  }
}

async function callGemini(apiKey, runtime = {}) {
  requireProviderSecret(apiKey, "gemini", "gemini");
  const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=${apiKey}`;
  const data = await requestWithRetry({
    provider: "gemini",
    stage: "gemini",
    url: endpoint,
    init: {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{
          parts: [{
            text: "現在(2026年8月)、世界のビジネス市場やテクノロジー全体（生成AI、SaaS、クラウド、サイバーセキュリティ、次世代インフラ、DX、組織マネジメント等）において最も狂気と変革をもたらしている最先端トレンドを1つ選定し、経営者や実務家の心を揺さぶる骨太な一次ドラフトを執筆してください。"
          }]
        }]
      })
    },
    consumeResponse: (response, signal) => parseJsonResponse(response, "gemini", "gemini", signal),
    timeoutMs: runtime.timeouts?.gemini ?? EXTERNAL_API_TIMEOUTS.gemini,
    maxAttempts: LLM_MAX_ATTEMPTS
  }, runtime);
  return requireResponseText(data.candidates?.[0]?.content?.parts?.[0]?.text, "gemini", "gemini");
}

async function callClaude(apiKey, draftText, runtime = {}) {
  requireProviderSecret(apiKey, "claude", "claude");
  const data = await requestWithRetry({
    provider: "claude",
    stage: "claude",
    url: "https://api.anthropic.com/v1/messages",
    init: {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-6",
      max_tokens: 1500,
      messages: [{
        role: "user",
        content: `以下の一次ドラフトを基に、単なる表面的な要約ではなく、現場のビジネスパーソンが思わず唸るような「鋭い洞察」「組織が直面する生々しい課題」「他社に遅れを取ることの致命的なリスクと突破口」を交え、熱量のこもった重厚な文章へと深くリライト・推敲してください。\n\n【一次ドラフト】\n${draftText}`
      }]
    })
    },
    consumeResponse: (response, signal) => parseJsonResponse(response, "claude", "claude", signal),
    timeoutMs: runtime.timeouts?.claude ?? EXTERNAL_API_TIMEOUTS.claude,
    maxAttempts: LLM_MAX_ATTEMPTS
  }, runtime);
  return requireResponseText(data.content?.[0]?.text, "claude", "claude");
}

async function callOpenAI(apiKey, reviewedText, runtime = {}) {
  requireProviderSecret(apiKey, "openai", "openai");
  const data = await requestWithRetry({
    provider: "openai",
    stage: "openai",
    url: "https://api.openai.com/v1/chat/completions",
    init: {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model: "gpt-4o-mini",
      messages: [{
        role: "user",
        content: `以下の推敲済み記事を、2026年現在のリアルなビジネス環境に完全に適合させ、かつ読者の感情を動かす「意志と熱量」を持った最高峰のまとめ記事として最終ブラッシュアップしてください。形式は必ず以下の構造のみを使用してください。\n\n【必須の構造】\n# 【2026年最新】（テーマを表す強烈なタイトル）\n\n## 1. 【トレンドの核心と現状】\n（表面的な解説に留まらず、今何が起きているのかの深い洞察と熱量を込めた本文）\n\n## 2. 【現場が直面する課題と背景】\n（なぜこの動向が無視できないのか、企業や実務家が抱えるリアルな葛藤と市場の構造変化）\n\n## 3. 【明日からのビジネスを動かす戦略的インサイト】\n（単なる感想ではなく、読者が自社に持ち帰って即座に行動を起こすための具体的かつ力強い提言）\n\n【推敲済み記事】\n${reviewedText}`
      }],
      max_tokens: 1500
    })
    },
    consumeResponse: (response, signal) => parseJsonResponse(response, "openai", "openai", signal),
    timeoutMs: runtime.timeouts?.openai ?? EXTERNAL_API_TIMEOUTS.openai,
    maxAttempts: LLM_MAX_ATTEMPTS
  }, runtime);
  return requireResponseText(data.choices?.[0]?.message?.content, "openai", "openai");
}

async function generateReport(env) {
  try {
    const tag = env.AMAZON_TAG || "tyansaku3325-22";
    const sampleItem = "最新ビジネスAIトレンド書籍";
    const encodedQuery = encodeURIComponent(sampleItem);
    const affiliateUrl = `https://www.amazon.co.jp/s?k=${encodedQuery}&tag=${tag}`;
    return `【自動定期レポート】\n本日のピックアップ情報：\n- **${sampleItem}**\n- 詳細・購入リンク: ${affiliateUrl}`;
  } catch (error) {
    logOperationFailure(error, "report_generation", "worker");
    return "【自動定期レポート】\n本日の情報収集中に一時的なエラーが発生しましたが、システムは正常稼働を維持しています。";
  }
}

async function sendAutomatedReport(env, runtime = {}) {
  const webhookUrl = env.DISCORD_WEBHOOK_URL;
  if (!webhookUrl) {
    throw new OperationError({
      stage: "discord",
      provider: "discord",
      errorCode: "configuration_missing"
    });
  }
  const content = await generateReport(env);
  await sendToDiscord(webhookUrl, content, runtime);
  return content;
}

async function handleGetTask(request, env) {
  try {
    let targetKeyword = "ビジネス変革 DX 成功法則";
    let articleTitle = "最新ビジネストレンド";

    if (env && env.DB) {
      const latestRecord = await env.DB.prepare(
        "SELECT content, created_at FROM curation_logs ORDER BY id DESC LIMIT 1"
      ).first();

      if (latestRecord && latestRecord.content) {
        targetKeyword = determineAffiliateKeyword(latestRecord.content);
        articleTitle = latestRecord.content.slice(0, 30).replace(/[\r\n]+/g, " ");
      }
    }

    const taskData = {
      status: "success",
      task_id: "task_" + Date.now(),
      action: "check_and_swipe",
      target_url: "https://www.amazon.co.jp/s?k=" + encodeURIComponent(targetKeyword),
      parameters: {
        keyword: targetKeyword,
        context_title: articleTitle
      },
      message: `Dynamic task dispatched for keyword: ${targetKeyword}`
    };

    return new Response(JSON.stringify(taskData, null, 2), {
      headers: { 
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*" 
      },
      status: 200
    });
  } catch (error) {
    const errorResponse = {
      status: "error",
      message: error instanceof Error ? error.message : String(error)
    };
    return new Response(JSON.stringify(errorResponse, null, 2), {
      headers: { "Content-Type": "application/json" },
      status: 200
    });
  }
}
