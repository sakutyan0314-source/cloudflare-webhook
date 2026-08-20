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
const INTERNAL_REQUEST_MAX_BYTES = 16 * 1024;
const APPROVED_CANARY_PATH = "/internal/approved-canary";
const APPROVED_CANARY_PUBLICATION_PATH = "/internal/approved-canary/publication";
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
const PIPELINE_DEADLINE_MS = 8 * 60 * 1000;
const MANUAL_HOURLY_LIMIT = 1;
const MANUAL_DAILY_LIMIT = 2;
const CRON_DAILY_LIMIT = 1;
const GLOBAL_DAILY_LIMIT = 3;
const IDEMPOTENCY_KEY_MAX_LENGTH = 128;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const ERROR_SUMMARY_MAX_LENGTH = 160;
const RECONCILIATION_NOTE_MAX_LENGTH = 240;
const RECONCILIATION_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

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
    if (url.pathname === APPROVED_CANARY_PATH) {
      return handleApprovedCanaryRequest(request, env);
    }
    if (url.pathname === APPROVED_CANARY_PUBLICATION_PATH) {
      return handleApprovedCanaryPublicationRequest(request, env);
    }
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
    const affiliateMatch = url.pathname.match(/^\/go\/amazon\/(\d+)\/?$/);
    if (affiliateMatch) {
      return handleAffiliateRedirect(request, env, affiliateMatch[1], url.searchParams);
    }
    const categoryMatch = url.pathname.match(/^\/category\/([a-z-]+)\/?$/);
    if (categoryMatch) {
      return handleCategoryPage(env, categoryMatch[1]);
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
    if (url.pathname === "/pipeline-reconciliation") {
      const allowedMethod = request.method === "GET" ? "GET" : "POST";
      const accessError = await authorizeOperationsRequest(request, env, allowedMethod);
      if (accessError) return accessError;
      return request.method === "GET"
        ? handlePipelineReconciliationList(env)
        : handlePipelineReconciliationAction(request, env);
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

function internalError(classification, status = 400) {
  return new Response(JSON.stringify({ status: "error", classification }), {
    status, headers: PRIVATE_JSON_HEADERS
  });
}

async function parseInternalJsonRequest(request, allowedFields) {
  const contentType = request.headers.get("Content-Type") || "";
  const length = Number(request.headers.get("Content-Length") || "0");
  if (!contentType.toLowerCase().startsWith("application/json") || !Number.isFinite(length) || length > INTERNAL_REQUEST_MAX_BYTES) {
    throw new Error("request_invalid");
  }
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > INTERNAL_REQUEST_MAX_BYTES) throw new Error("request_invalid");
  let payload;
  try { payload = JSON.parse(text); } catch { throw new Error("request_invalid"); }
  if (!payload || Array.isArray(payload) || typeof payload !== "object" || Object.keys(payload).some((key) => !allowedFields.has(key))) {
    throw new Error("request_invalid");
  }
  return payload;
}

async function handleApprovedCanaryRequest(request, env) {
  const accessError = await authorizeOperationsRequest(request, env, "POST");
  if (accessError) return accessError;
  try {
    const payload = await parseInternalJsonRequest(request, new Set(["trigger_type", "production_input_id", "approval_id", "production_execution_id", "pipeline_run_id"]));
    if (payload.trigger_type !== "approved_canary" || Object.keys(payload).length !== 5 || !["production_input_id", "approval_id", "production_execution_id"].every((key) => typeof payload[key] === "string" && payload[key]) || !Number.isSafeInteger(payload.pipeline_run_id) || payload.pipeline_run_id < 1) throw new Error("request_invalid");
    const runtime = env?.APPROVED_CANARY_RUNTIME;
    if (!runtime || typeof runtime.resolve !== "function") return internalError("canary_runtime_unavailable", 503);
    const resolved = await runtime.resolve(payload);
    const { runApprovedCanaryWorker } = await import("./approved_canary_worker_adapter.js");
    const result = await runApprovedCanaryWorker({ ...resolved, request: resolved.request, authorize: async () => {}, validate: resolved.validate });
    return new Response(JSON.stringify({ status: "accepted", execution_classification: result?.state || "accepted" }), { status: 202, headers: PRIVATE_JSON_HEADERS });
  } catch { return internalError("approved_canary_request_rejected"); }
}

async function handleApprovedCanaryPublicationRequest(request, env) {
  const accessError = await authorizeOperationsRequest(request, env, "POST");
  if (accessError) return accessError;
  try {
    const fields = new Set(["trigger_type", "staging_draft_id", "production_execution_id", "production_input_id", "publication_approval_id", "quality_gate_audit_id", "final_content_fingerprint"]);
    const payload = await parseInternalJsonRequest(request, fields);
    if (payload.trigger_type !== "approved_canary_publication" || Object.keys(payload).length !== fields.size) throw new Error("request_invalid");
    if ([...fields].filter((key) => key !== "trigger_type").some((key) => typeof payload[key] !== "string" || !payload[key])) throw new Error("request_invalid");
    const runtime = env?.APPROVED_CANARY_PUBLICATION_RUNTIME;
    if (!runtime || typeof runtime.resolve !== "function") return internalError("publication_runtime_unavailable", 503);
    const resolved = await runtime.resolve(payload);
    const { runApprovedCanaryPublication } = await import("./publication_worker_adapter.js");
    const result = await runApprovedCanaryPublication({ ...resolved, request: resolved.request, authorize: async () => {} });
    return new Response(JSON.stringify({ status: "accepted", final_article_id: result?.final_article_id ?? null }), { status: 202, headers: PRIVATE_JSON_HEADERS });
  } catch { return internalError("publication_request_rejected"); }
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
    const { results } = await env.DB.prepare(
      "SELECT * FROM curation_logs ORDER BY id DESC LIMIT 1000"
    ).all();
    const publicArticles = (results ?? []).filter((row) => readSeoArticle(row).seoStatus !== "needs_review");
    const totalItems = publicArticles.length;
    const totalPages = Math.ceil(totalItems / perPage) || 1;
    if (currentPage > totalPages) {
      return new Response("ページが見つかりません。", {
        status: 404,
        headers: TEXT_HEADERS
      });
    }
    const offset = (currentPage - 1) * perPage;
    const pageResults = publicArticles.slice(offset, offset + perPage);
    const affiliateTag = env.AMAZON_TAG || "default-22";
    const html = renderHomePage(pageResults, {
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

function nonPublicArticleResponse() {
  return new Response("記事が見つかりませんでした。", {
    status: 404,
    headers: {
      ...TEXT_HEADERS,
      "X-Robots-Tag": "noindex"
    }
  });
}

const SEO_CATEGORIES = new Set([
  "ai-automation",
  "saas-cloud",
  "security-governance",
  "engineering-infrastructure",
  "dx-organization",
  "marketing-cx",
  "uncategorized"
]);
const SEO_STATUSES = new Set(["legacy", "ready", "needs_review"]);
const AFFILIATE_PLACEMENTS = new Set(["article", "discord"]);
const AFFILIATE_LINK_TYPE = "amazon_search";
const MIN_SEO_ARTICLE_BODY_LENGTH = 240;
const RECENT_ARTICLE_SIMILARITY_THRESHOLD = 0.8;
const QUALITY_GATE_AUDIT_SCHEMA_VERSION = "quality-gate-audit-v1";
const SEO_QUALITY_THRESHOLD_VERSION = "seo_quality_threshold_v1";
const QUALITY_GATE_CHECK_NAMES = new Set(["h1_structure", "title_presence", "body_presence", "body_length", "h2_count", "description_presence", "category_allowed", "duplicate_similarity"]);
const QUALITY_GATE_CHECK_STATUSES = new Set(["pass", "fail", "not_evaluated", "review_required"]);
const QUALITY_GATE_CLASSIFICATIONS = new Set(["pass", "fail", "needs_review", "input_invalid"]);
const QUALITY_GATE_REASON_CODES = new Set(["h1_missing_or_invalid", "title_missing", "body_missing", "description_missing", "category_not_allowed", "body_length_below_minimum", "insufficient_h2_count", "seo_quality_check_failed", "duplicate_risk_exceeded"]);

function seoText(value) {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

function seoDate(value, fallback) {
  const candidate = seoText(value);
  return candidate && Number.isFinite(Date.parse(candidate)) ? candidate : fallback;
}

function legacyArticleTitle(content, id) {
  const firstLine = content.split(/\r?\n/).find((line) => line.trim()) || `記事 ${id}`;
  return firstLine.replace(/^#+\s*/, "").slice(0, 80);
}

function legacyArticleDescription(content) {
  return content
    .replace(/[#>*_`\[\]\(\)]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 160);
}

function readSeoArticle(row) {
  const content = String(row?.content || "");
  const bodyMarkdown = seoText(row?.body_markdown) || content;
  const createdAt = seoDate(row?.created_at, new Date(0).toISOString());
  const publishedAt = seoDate(row?.published_at, createdAt);
  const updatedAt = seoDate(row?.updated_at, publishedAt);
  const category = SEO_CATEGORIES.has(row?.category) ? row.category : "uncategorized";
  const seoStatus = SEO_STATUSES.has(row?.seo_status) ? row.seo_status : "legacy";

  return {
    id: row?.id,
    title: seoText(row?.title) || legacyArticleTitle(bodyMarkdown, row?.id),
    description: seoText(row?.description) || legacyArticleDescription(bodyMarkdown),
    bodyMarkdown,
    category,
    publishedAt,
    updatedAt,
    seoStatus
  };
}

function determineArticleCategory(content) {
  const lower = String(content || "").toLowerCase();
  if (lower.includes("セキュリティ") || lower.includes("サイバー") || lower.includes("ガバナンス") || lower.includes("リスク")) {
    return "security-governance";
  }
  if (lower.includes("saas") || lower.includes("クラウド")) return "saas-cloud";
  if (lower.includes("プログラミング") || lower.includes("開発") || lower.includes("エンジニア") || lower.includes("アーキテクチャ") || lower.includes("インフラ")) {
    return "engineering-infrastructure";
  }
  if (lower.includes("マーケティング") || lower.includes("cx") || lower.includes("顧客") || lower.includes("sales")) {
    return "marketing-cx";
  }
  if (lower.includes("dx") || lower.includes("マネジメント") || lower.includes("組織") || lower.includes("リーダーシップ") || lower.includes("人材")) {
    return "dx-organization";
  }
  if (lower.includes("ai") || lower.includes("人工知能") || lower.includes("自動化") || lower.includes("エージェント") || lower.includes("生成ai")) {
    return "ai-automation";
  }
  return "uncategorized";
}

function titleSimilarity(left, right) {
  const normalize = (value) => String(value || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
  const leftText = normalize(left);
  const rightText = normalize(right);
  if (!leftText || !rightText) return 0;
  if (leftText === rightText) return 1;
  const shingles = (value) => {
    const result = new Set();
    for (let index = 0; index <= value.length - 3; index += 1) result.add(value.slice(index, index + 3));
    return result.size > 0 ? result : new Set([value]);
  };
  const leftShingles = shingles(leftText);
  const rightShingles = shingles(rightText);
  const intersection = [...leftShingles].filter((value) => rightShingles.has(value)).length;
  return intersection / (leftShingles.size + rightShingles.size - intersection);
}

function parseGeneratedSeoArticle(markdown, nowIso) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const firstContentIndex = lines.findIndex((line) => line.trim() !== "");
  const titleMatch = firstContentIndex >= 0 ? lines[firstContentIndex].trim().match(/^#\s+(.+)$/) : null;
  if (!titleMatch) return null;
  const title = titleMatch[1].trim();
  const bodyMarkdown = lines.filter((_, index) => index !== firstContentIndex).join("\n").trim();
  const description = legacyArticleDescription(bodyMarkdown);
  const category = determineArticleCategory(`${title}\n${bodyMarkdown}`);
  if (!title || !description || !bodyMarkdown || !SEO_CATEGORIES.has(category)) return null;
  return {
    content: String(markdown || "").trim(),
    title,
    description,
    bodyMarkdown,
    category,
    publishedAt: nowIso,
    updatedAt: nowIso,
    seoStatus: "ready"
  };
}

function qualityGateCheck(status, extra = {}) {
  return { status, ...extra };
}

/* This function deliberately returns only numeric/category audit data.  It
 * never places generated prose in the audit object. */
function evaluateSeoQuality(markdown, runId, nowIso) {
  const text = typeof markdown === "string" ? markdown : "";
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const firstContentIndex = lines.findIndex((line) => line.trim() !== "");
  const titleMatch = firstContentIndex >= 0 ? lines[firstContentIndex].trim().match(/^#\s+(.+)$/) : null;
  const title = titleMatch?.[1]?.trim() || "";
  const bodyMarkdown = firstContentIndex >= 0 ? lines.filter((_, index) => index !== firstContentIndex).join("\n").trim() : "";
  const description = legacyArticleDescription(bodyMarkdown);
  const category = determineArticleCategory(`${title}\n${bodyMarkdown}`);
  const h2Count = (bodyMarkdown.match(/^##\s+\S/gm) || []).length;
  const reasonCodes = [];
  const checks = {
    h1_structure: qualityGateCheck(titleMatch ? "pass" : "fail"),
    title_presence: qualityGateCheck(title ? "pass" : "fail"),
    body_presence: qualityGateCheck(bodyMarkdown ? "pass" : "fail"),
    body_length: qualityGateCheck(bodyMarkdown.length >= MIN_SEO_ARTICLE_BODY_LENGTH ? "pass" : "fail", { observed_value: bodyMarkdown.length, required_min: MIN_SEO_ARTICLE_BODY_LENGTH }),
    h2_count: qualityGateCheck(h2Count >= 1 ? "pass" : "fail", { observed_value: h2Count, required_min: 1 }),
    description_presence: qualityGateCheck(description ? "pass" : "fail"),
    category_allowed: qualityGateCheck(SEO_CATEGORIES.has(category) ? "pass" : "fail"),
    duplicate_similarity: qualityGateCheck("not_evaluated", { observed_value: null, threshold: RECENT_ARTICLE_SIMILARITY_THRESHOLD, compared_article_count: 0 })
  };
  if (!titleMatch) reasonCodes.push("h1_missing_or_invalid");
  if (!title) reasonCodes.push("title_missing");
  if (!bodyMarkdown) reasonCodes.push("body_missing");
  if (!description) reasonCodes.push("description_missing");
  if (!SEO_CATEGORIES.has(category)) reasonCodes.push("category_not_allowed");
  if (bodyMarkdown.length < MIN_SEO_ARTICLE_BODY_LENGTH) reasonCodes.push("body_length_below_minimum");
  if (h2Count < 1) reasonCodes.push("insufficient_h2_count");
  const classification = reasonCodes.length ? "fail" : "pass";
  return {
    article: classification === "pass" ? {
      content: text.trim(), title, description, bodyMarkdown, category,
      publishedAt: nowIso, updatedAt: nowIso, seoStatus: "ready"
    } : null,
    audit: {
      schema_version: QUALITY_GATE_AUDIT_SCHEMA_VERSION, run_id: runId, stage: "seo_quality",
      classification, reason_codes: reasonCodes, threshold_version: SEO_QUALITY_THRESHOLD_VERSION,
      evaluated_at: nowIso, checks
    }
  };
}

function finalizeDuplicateQualityAudit(evaluation, recentArticles) {
  if (evaluation.audit.classification !== "pass" || !evaluation.article) return evaluation;
  const similarities = recentArticles.map((row) => titleSimilarity(evaluation.article.title, readSeoArticle(row).title));
  const highest = similarities.length ? Math.max(...similarities) : 0;
  const reviewRequired = highest >= RECENT_ARTICLE_SIMILARITY_THRESHOLD;
  const audit = {
    ...evaluation.audit,
    classification: reviewRequired ? "needs_review" : "pass",
    reason_codes: reviewRequired ? ["duplicate_risk_exceeded"] : [],
    checks: { ...evaluation.audit.checks, duplicate_similarity: qualityGateCheck(reviewRequired ? "review_required" : "pass", {
      observed_value: highest, threshold: RECENT_ARTICLE_SIMILARITY_THRESHOLD, compared_article_count: recentArticles.length
    }) }
  };
  return { article: { ...evaluation.article, seoStatus: reviewRequired ? "needs_review" : "ready" }, audit };
}

function serializeQualityGateAudit(audit) {
  if (!audit || typeof audit !== "object" || Object.keys(audit).length !== 8 ||
      audit.schema_version !== QUALITY_GATE_AUDIT_SCHEMA_VERSION || audit.stage !== "seo_quality" ||
      !QUALITY_GATE_CLASSIFICATIONS.has(audit.classification) || audit.threshold_version !== SEO_QUALITY_THRESHOLD_VERSION ||
      typeof audit.run_id !== "number" || !Number.isSafeInteger(audit.run_id) || audit.run_id < 1 ||
      typeof audit.evaluated_at !== "string" || !Array.isArray(audit.reason_codes) || !audit.checks || typeof audit.checks !== "object") {
    throw new OperationError({ stage: "seo_quality", provider: "audit", errorCode: "quality_gate_audit_write_failed" });
  }
  const checkNames = Object.keys(audit.checks);
  if (checkNames.length !== 8 || checkNames.some((name) => !QUALITY_GATE_CHECK_NAMES.has(name)) ||
      audit.reason_codes.some((code) => !QUALITY_GATE_REASON_CODES.has(code)) || new Set(audit.reason_codes).size !== audit.reason_codes.length) {
    throw new OperationError({ stage: "seo_quality", provider: "audit", errorCode: "quality_gate_audit_write_failed" });
  }
  const checks = checkNames.sort().map((checkName) => {
    const check = audit.checks[checkName];
    const allowed = new Set(["status", "observed_value", "required_min", "required_max", "threshold", "compared_article_count"]);
    if (!check || typeof check !== "object" || Object.keys(check).some((key) => !allowed.has(key)) || !QUALITY_GATE_CHECK_STATUSES.has(check.status)) throw new OperationError({ stage: "seo_quality", provider: "audit", errorCode: "quality_gate_audit_write_failed" });
    for (const key of ["observed_value", "required_min", "required_max", "threshold", "compared_article_count"]) if (check[key] != null && (!Number.isFinite(check[key]) || check[key] < 0)) throw new OperationError({ stage: "seo_quality", provider: "audit", errorCode: "quality_gate_audit_write_failed" });
    return { check_name: checkName, status: check.status, observed_value: check.observed_value ?? null, required_min: check.required_min ?? null, required_max: check.required_max ?? null, threshold: check.threshold ?? null, compared_article_count: check.compared_article_count ?? null };
  });
  return { audit_id: crypto.randomUUID(), pipeline_run_id: audit.run_id, schema_version: audit.schema_version, stage: audit.stage, classification: audit.classification, threshold_version: audit.threshold_version, evaluated_at: audit.evaluated_at, checks, reasons: audit.reason_codes.map((reason_code, reason_order) => ({ reason_code, reason_order })) };
}

async function persistQualityGateAudit(db, runtime, audit) {
  try {
    const record = serializeQualityGateAudit(audit);
    const statements = [db.prepare(`INSERT INTO quality_gate_audits (audit_id, pipeline_run_id, schema_version, stage, classification, threshold_version, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?)`).bind(record.audit_id, record.pipeline_run_id, record.schema_version, record.stage, record.classification, record.threshold_version, record.evaluated_at)];
    for (const check of record.checks) statements.push(db.prepare(`INSERT INTO quality_gate_audit_checks (audit_id, check_name, status, observed_value, required_min, required_max, threshold, compared_article_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).bind(record.audit_id, check.check_name, check.status, check.observed_value, check.required_min, check.required_max, check.threshold, check.compared_article_count));
    for (const reason of record.reasons) statements.push(db.prepare(`INSERT INTO quality_gate_audit_reasons (audit_id, reason_code, reason_order) VALUES (?, ?, ?)`).bind(record.audit_id, reason.reason_code, reason.reason_order));
    if (!db || typeof db.batch !== "function") throw new Error("audit batch unavailable");
    const results = await db.batch(statements);
    if (!Array.isArray(results) || results.length !== statements.length || results.some((result) => statementChanges(result) !== 1)) throw new Error("audit batch invalid");
  } catch {
    throw new OperationError({ stage: "seo_quality", provider: "audit", errorCode: "quality_gate_audit_write_failed" });
  }
}

async function prepareSeoArticleForSave(db, markdown, runId, runtime = {}) {
  const nowIso = runtimeNow(runtime).toISOString();
  let evaluation = evaluateSeoQuality(markdown, runId, nowIso);
  if (evaluation.audit.classification === "fail") {
    await persistQualityGateAudit(db, runtime, evaluation.audit);
    throw new OperationError({ stage: "seo_quality", provider: "worker", errorCode: "seo_quality_failed" });
  }

  let recentArticles;
  try {
    const result = await db.prepare(
      "SELECT * FROM curation_logs ORDER BY id DESC LIMIT 5"
    ).all();
    recentArticles = result?.results ?? [];
  } catch {
    const audit = { ...evaluation.audit, classification: "input_invalid", reason_codes: ["seo_quality_check_failed"], checks: { ...evaluation.audit.checks, duplicate_similarity: qualityGateCheck("not_evaluated", { observed_value: null, threshold: RECENT_ARTICLE_SIMILARITY_THRESHOLD, compared_article_count: 0 }) } };
    await persistQualityGateAudit(db, runtime, audit);
    throw new OperationError({ stage: "seo_quality", provider: "d1", errorCode: "seo_quality_check_failed" });
  }
  evaluation = finalizeDuplicateQualityAudit(evaluation, recentArticles);
  await persistQualityGateAudit(db, runtime, evaluation.audit);
  return evaluation.article;
}

function renderInlineMarkdown(value) {
  const text = String(value || "");
  const linkPattern = /\[([^\]]+)\]\(([^\s)]+)\)/g;
  let output = "";
  let cursor = 0;
  let match;

  while ((match = linkPattern.exec(text)) !== null) {
    output += escapeHtml(text.slice(cursor, match.index));
    const label = escapeHtml(match[1]);
    let href;
    try {
      const parsedUrl = new URL(match[2]);
      href = ["https:", "http:"].includes(parsedUrl.protocol) ? parsedUrl.href : null;
    } catch {
      href = null;
    }
    output += href
      ? `<a href="${escapeHtml(href)}" rel="nofollow noopener noreferrer">${label}</a>`
      : escapeHtml(match[0]);
    cursor = linkPattern.lastIndex;
  }

  return output + escapeHtml(text.slice(cursor));
}

function renderArticleMarkdown(markdown, pageTitle) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let paragraph = [];
  let listItems = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (listItems.length === 0) return;
    blocks.push(`<ul>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
    listItems = [];
  };
  const flushText = () => {
    flushParagraph();
    flushList();
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed === "") {
      flushText();
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushText();
      const level = heading[1].length;
      const headingText = heading[2].trim();
      if (level === 1 && headingText === pageTitle.trim()) continue;
      const tag = level === 3 ? "h3" : "h2";
      blocks.push(`<${tag}>${renderInlineMarkdown(headingText)}</${tag}>`);
      continue;
    }

    const listItem = trimmed.match(/^[-*]\s+(.+)$/);
    if (listItem) {
      flushParagraph();
      listItems.push(listItem[1]);
      continue;
    }

    flushList();
    paragraph.push(trimmed);
  }

  flushText();
  return blocks.length > 0 ? blocks.join("\n") : "<p>本文はありません。</p>";
}

function categoryLabel(category) {
  const labels = {
    "ai-automation": "AI・自動化",
    "saas-cloud": "SaaS・クラウド",
    "security-governance": "セキュリティ・ガバナンス",
    "engineering-infrastructure": "開発・インフラ",
    "dx-organization": "DX・組織変革",
    "marketing-cx": "マーケティング・CX",
    uncategorized: "その他"
  };
  return labels[category] || labels.uncategorized;
}

function isPublicArticle(article) {
  return article.seoStatus !== "needs_review";
}

function isPublicCategory(category) {
  return SEO_CATEGORIES.has(category) && category !== "uncategorized";
}

function categoryUrl(siteUrl, category) {
  return `${siteUrl}/category/${category}`;
}

function sortArticlesByUpdatedAt(articles) {
  return [...articles].sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt));
}

function categoryArticles(rows, category) {
  return sortArticlesByUpdatedAt(
    (rows ?? []).map((row) => readSeoArticle(row)).filter((article) =>
      isPublicArticle(article) && article.category === category
    )
  );
}

function relatedArticles(rows, article) {
  if (!isPublicCategory(article.category)) return [];
  return categoryArticles(rows, article.category)
    .filter((candidate) => candidate.id !== article.id)
    .slice(0, 3);
}

function jsonLd(value) {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

function breadcrumbJsonLd(siteUrl, items) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: item.url
    }))
  };
}

function renderBreadcrumb(items) {
  return `<nav class="breadcrumb" aria-label="パンくずリスト">${items.map((item, index) =>
    index === items.length - 1
      ? `<span aria-current="page">${escapeHtml(item.name)}</span>`
      : `<a href="${escapeHtml(item.url)}">${escapeHtml(item.name)}</a>`
  ).join("<span class=\"breadcrumb-separator\" aria-hidden=\"true\">›</span>")}</nav>`;
}

function articleBreadcrumb(siteUrl, article) {
  const items = [{ name: "ホーム", url: `${siteUrl}/` }];
  if (isPublicCategory(article.category)) {
    items.push({ name: categoryLabel(article.category), url: categoryUrl(siteUrl, article.category) });
  }
  items.push({ name: article.title, url: `${siteUrl}/article/${article.id}` });
  return items;
}

function renderRelatedArticles(articles) {
  if (articles.length === 0) return "";
  return `<section class="related-articles" aria-labelledby="related-articles-heading">
  <h2 id="related-articles-heading">関連記事</h2>
  <ul>${articles.map((article) => `<li><a href="/article/${escapeHtml(String(article.id))}">${escapeHtml(article.title)}</a></li>`).join("")}</ul>
</section>`;
}

async function handleCategoryPage(env, category) {
  try {
    if (!isPublicCategory(category)) return nonPublicArticleResponse();
    const siteUrl = getSiteUrl(env);
    const { results } = await env.DB.prepare(
      "SELECT * FROM curation_logs ORDER BY id DESC LIMIT 1000"
    ).all();
    const articles = categoryArticles(results, category);
    if (articles.length === 0) return nonPublicArticleResponse();
    const label = categoryLabel(category);
    const canonicalUrl = categoryUrl(siteUrl, category);
    const pageTitle = `${label}の記事一覧 | テクノロジー＆ビジネストレンド最速まとめ速報`;
    const description = `${label}に関する記事一覧です。AI、SaaS、セキュリティなどの最新動向を整理してお届けします。`;
    const breadcrumbs = [
      { name: "ホーム", url: `${siteUrl}/` },
      { name: label, url: canonicalUrl }
    ];
    const posts = articles.map((article) => `<article class="post">
  <h2><a href="/article/${escapeHtml(String(article.id))}">${escapeHtml(article.title)}</a></h2>
  <p>${escapeHtml(article.description)}</p>
  <a href="/article/${escapeHtml(String(article.id))}">続きを読む &rarr;</a>
</article>`).join("");
    const html = `<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(pageTitle)}</title><meta name="description" content="${escapeHtml(description)}">
<link rel="canonical" href="${canonicalUrl}">
<meta property="og:type" content="website"><meta property="og:title" content="${escapeHtml(pageTitle)}"><meta property="og:description" content="${escapeHtml(description)}"><meta property="og:url" content="${canonicalUrl}">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="${escapeHtml(pageTitle)}"><meta name="twitter:description" content="${escapeHtml(description)}">
<script type="application/ld+json">${jsonLd(breadcrumbJsonLd(siteUrl, breadcrumbs))}</script>
</head><body><main><h1>${escapeHtml(label)}の記事一覧</h1>${renderBreadcrumb(breadcrumbs)}<div class="posts">${posts}</div></main></body></html>`;
    return new Response(html, { headers: HTML_HEADERS });
  } catch (error) {
    logOperationFailure(error, "category_page", "worker");
    return new Response("記事の読み込み中にエラーが発生しました。", { status: 500, headers: TEXT_HEADERS });
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
      "SELECT * FROM curation_logs WHERE id = ? LIMIT 1"
    ).bind(id).first();

    if (!row) {
      return nonPublicArticleResponse();
    }

    const article = readSeoArticle(row);
    if (article.seoStatus === "needs_review") return nonPublicArticleResponse();
    const content = article.bodyMarkdown;
    const pageTitle = article.title;
    const description = article.description;
    const dateStr = new Date(article.updatedAt).toLocaleString("ja-JP");

    const keyword = determineAffiliateKeyword(content);
    const affiliateUrl = affiliateRedirectUrl(siteUrl, id, "article");
const canonicalUrl = `${siteUrl}/article/${id}`;
    const breadcrumbs = articleBreadcrumb(siteUrl, article);
    let related = [];
    if (isPublicCategory(article.category)) {
      try {
        const { results } = await env.DB.prepare(
          "SELECT * FROM curation_logs ORDER BY id DESC LIMIT 1000"
        ).all();
        related = relatedArticles(results, article);
      } catch (error) {
        logOperationFailure(error, "related_articles", "d1");
      }
    }
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
${jsonLd({
  "@context": "https://schema.org",
  "@type": "Article",
  headline: pageTitle,
  description: description,
  datePublished: article.publishedAt,
  dateModified: article.updatedAt,
  articleSection: article.category,
  mainEntityOfPage: {
    "@type": "WebPage",
    "@id": canonicalUrl
  },
  url: canonicalUrl
})}
</script>
<script type="application/ld+json">
${jsonLd(breadcrumbJsonLd(siteUrl, breadcrumbs))}
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

    .breadcrumb { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 18px; font-size: 13px; }
    .breadcrumb-separator { color: #777; }
    .related-articles { margin-top: 32px; padding-top: 20px; border-top: 1px solid #eaeaea; }
    .related-articles h2 { font-size: 20px; }
    .related-articles li { margin: 8px 0; }
  </style>
</head>
<body>
  <main class="container">
    ${renderBreadcrumb(breadcrumbs)}
    <a class="back-link" href="/">← 記事一覧へ戻る</a>

    <article>
      <h1>${escapeHtml(pageTitle)}</h1>

      <div class="meta">
        更新日時: ${escapeHtml(dateStr)}
      </div>

      <div class="content">${renderArticleMarkdown(content, pageTitle)}</div>

      <div class="affiliate-box">
        🛒 厳選おすすめ関連アイテム（${escapeHtml(keyword)}）：
        <a
          href="${escapeHtml(affiliateUrl)}"
          target="_blank"
          rel="nofollow sponsored noopener"
        >Amazonで最新商品をチェックする</a>
      </div>
      ${renderRelatedArticles(related)}
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

function affiliateRedirectUrl(siteUrl, articleId, placement) {
  return `${siteUrl}/go/amazon/${encodeURIComponent(String(articleId))}?placement=${encodeURIComponent(placement)}`;
}

function buildAmazonSearchUrl(content, amazonTag) {
  const keyword = determineAffiliateKeyword(content);
  const affiliateTag = amazonTag || "default-22";
  return `https://www.amazon.co.jp/s?k=${encodeURIComponent(keyword)}&tag=${encodeURIComponent(affiliateTag)}`;
}

async function handleAffiliateRedirect(request, env, articleId, searchParams) {
  if (request.method !== "GET") {
    return new Response("Method Not Allowed", { status: 405, headers: { ...TEXT_HEADERS, "Allow": "GET" } });
  }
  const id = Number.parseInt(articleId, 10);
  const placement = searchParams.get("placement");
  if (
    !Number.isInteger(id) || id < 1 ||
    searchParams.size !== 1 || searchParams.getAll("placement").length !== 1 ||
    !AFFILIATE_PLACEMENTS.has(placement)
  ) {
    return new Response("Invalid affiliate link", { status: 400, headers: TEXT_HEADERS });
  }

  try {
    const row = await env.DB.prepare("SELECT * FROM curation_logs WHERE id = ? LIMIT 1").bind(id).first();
    if (!row || readSeoArticle(row).seoStatus === "needs_review") return nonPublicArticleResponse();
    const article = readSeoArticle(row);
    const clickedAt = new Date().toISOString();
    await env.DB.prepare(
      `INSERT INTO affiliate_click_events
        (event_id, article_id, link_type, placement, category, clicked_at)
       VALUES (?, ?, ?, ?, ?, ?)`
    ).bind(crypto.randomUUID(), id, AFFILIATE_LINK_TYPE, placement, article.category, clickedAt).run();
    return new Response(null, {
      status: 302,
      headers: {
        "Location": buildAmazonSearchUrl(article.bodyMarkdown, env.AMAZON_TAG),
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex",
        "Referrer-Policy": "strict-origin-when-cross-origin"
      }
    });
  } catch (error) {
    logOperationFailure(error, "affiliate_redirect", "d1");
    return new Response("Affiliate link unavailable", {
      status: 503,
      headers: { ...TEXT_HEADERS, "Cache-Control": "no-store", "X-Robots-Tag": "noindex" }
    });
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
    const safe = normalizeOperationError(error, "test_multillm", "worker");
    const status = safe.errorCode === "pipeline_limit_exceeded"
      ? 429
      : safe.errorCode === "pipeline_deadline_exceeded"
        ? 504
        : safe.stage === "pipeline_acquire"
          ? 503
          : 500;
    const headers = { ...PRIVATE_JSON_HEADERS };
    if (status === 429 && Number.isFinite(safe.retryAfterSeconds)) {
      headers["Retry-After"] = String(Math.max(1, Math.ceil(safe.retryAfterSeconds)));
    }
    return new Response(JSON.stringify({ status: "error", message: "Operation failed" }, null, 2), {
      status,
      headers
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

function classifyReconciliationRun(run, now) {
  const hasArticle = Number(run.has_article) === 1;
  const leaseExpired = Date.parse(run.lease_expires_at) <= now.getTime();
  if (run.notification_status === "sending") return "delivery_unknown_human_review";
  if (run.status === "running" && hasArticle) return "saved_state_repair_available";
  if (run.status === "running" && leaseExpired) return "stale_without_article_can_fail";
  if (run.status === "running") return "active_no_action";
  if (run.status === "saved" && run.notification_status === "pending") {
    return "saved_unsent_manual_resume_required";
  }
  if (run.status === "saved" && run.notification_status === "failed") {
    return "notification_failed_manual_review";
  }
  return "no_action";
}

async function handlePipelineReconciliationList(env, runtime = {}) {
  try {
    const now = runtimeNow(runtime);
    const { results } = await env.DB.prepare(
      `SELECT r.id, r.trigger_type, r.status, r.stage, r.article_id,
              r.notification_status, r.notification_attempt_count,
              r.error_code, r.lease_expires_at, r.started_at, r.updated_at,
              CASE WHEN c.id IS NULL THEN 0 ELSE 1 END AS has_article
       FROM pipeline_runs r
       LEFT JOIN curation_logs c ON c.pipeline_run_id = r.id
       WHERE (r.status = 'running' AND r.lease_expires_at <= ?)
          OR r.status = 'saved'
          OR r.notification_status = 'sending'
       ORDER BY r.updated_at ASC
       LIMIT 100`
    ).bind(now.toISOString()).all();
    const runs = (results ?? []).map((run) => ({
      ...run,
      reconciliation_class: classifyReconciliationRun(run, now)
    }));
    return new Response(JSON.stringify({ status: "success", asOf: now.toISOString(), runs }, null, 2), {
      headers: PRIVATE_JSON_HEADERS
    });
  } catch (error) {
    logOperationFailure(error, "pipeline_reconciliation_list", "d1");
    return new Response(JSON.stringify({ status: "error", message: "Operation failed" }), {
      status: 500,
      headers: PRIVATE_JSON_HEADERS
    });
  }
}

function reconciliationActionDefinition(action, nowIso) {
  const definitions = {
    mark_stale_failed: {
      resultingStatus: "failed",
      resultingNotificationStatus: "pending",
      eligibility: "r.status = 'running' AND r.notification_status = 'pending' AND r.lease_expires_at <= ? AND NOT EXISTS (SELECT 1 FROM curation_logs c WHERE c.pipeline_run_id = r.id)",
      eligibilityArgs: [nowIso],
      update: `UPDATE pipeline_runs
        SET status = 'failed', error_code = 'stale_run_reconciled_no_article',
            error_retryable = 0, error_summary = 'worker:stale_run_reconciled_no_article',
            updated_at = ?, failed_at = ?
        WHERE id = ? AND status = 'running' AND notification_status = 'pending'
          AND lease_expires_at <= ? AND NOT EXISTS
            (SELECT 1 FROM curation_logs c WHERE c.pipeline_run_id = pipeline_runs.id)`,
      updateArgs: [nowIso, nowIso]
    },
    repair_saved_state: {
      resultingStatus: "saved",
      resultingNotificationStatus: "pending",
      eligibility: "r.status = 'running' AND r.notification_status = 'pending' AND EXISTS (SELECT 1 FROM curation_logs c WHERE c.pipeline_run_id = r.id)",
      eligibilityArgs: [],
      update: `UPDATE pipeline_runs
        SET status = 'saved', stage = 'discord', notification_status = 'pending',
            article_id = (SELECT id FROM curation_logs WHERE pipeline_run_id = pipeline_runs.id LIMIT 1),
            saved_at = COALESCE(saved_at, ?), updated_at = ?
        WHERE id = ? AND status = 'running' AND notification_status = 'pending'
          AND EXISTS (SELECT 1 FROM curation_logs c WHERE c.pipeline_run_id = pipeline_runs.id)`,
      updateArgs: [nowIso, nowIso]
    },
    confirm_notification_delivered: {
      resultingStatus: "completed",
      resultingNotificationStatus: "sent",
      eligibility: "r.status = 'saved' AND r.notification_status = 'sending' AND EXISTS (SELECT 1 FROM curation_logs c WHERE c.pipeline_run_id = r.id)",
      eligibilityArgs: [],
      update: `UPDATE pipeline_runs
        SET status = 'completed', stage = 'done', notification_status = 'sent',
            notified_at = COALESCE(notified_at, ?), completed_at = ?, updated_at = ?,
            error_code = NULL, error_http_status = NULL, error_retryable = 0, error_summary = NULL
        WHERE id = ? AND status = 'saved' AND notification_status = 'sending'
          AND EXISTS (SELECT 1 FROM curation_logs c WHERE c.pipeline_run_id = pipeline_runs.id)`,
      updateArgs: [nowIso, nowIso, nowIso]
    },
    confirm_notification_not_delivered: {
      resultingStatus: "saved",
      resultingNotificationStatus: "failed",
      eligibility: "r.status = 'saved' AND r.notification_status = 'sending' AND EXISTS (SELECT 1 FROM curation_logs c WHERE c.pipeline_run_id = r.id)",
      eligibilityArgs: [],
      update: `UPDATE pipeline_runs
        SET status = 'saved', stage = 'discord', notification_status = 'failed',
            error_code = 'manual_confirmed_not_delivered', error_retryable = 0,
            error_summary = 'operator:manual_confirmed_not_delivered', updated_at = ?
        WHERE id = ? AND status = 'saved' AND notification_status = 'sending'
          AND EXISTS (SELECT 1 FROM curation_logs c WHERE c.pipeline_run_id = pipeline_runs.id)`,
      updateArgs: [nowIso]
    }
  };
  return definitions[action] ?? null;
}

async function handlePipelineReconciliationAction(request, env, runtime = {}) {
  const operationKey = request.headers.get("Reconciliation-Key");
  if (!operationKey || !RECONCILIATION_KEY_PATTERN.test(operationKey)) {
    return new Response(JSON.stringify({ status: "error", message: "Valid Reconciliation-Key is required" }), {
      status: 400, headers: PRIVATE_JSON_HEADERS
    });
  }
  let input;
  try {
    input = await request.json();
  } catch {
    return new Response(JSON.stringify({ status: "error", message: "Invalid JSON" }), {
      status: 400, headers: PRIVATE_JSON_HEADERS
    });
  }
  const runId = Number(input?.runId);
  const action = input?.action;
  const evidence = typeof input?.evidence === "string" ? input.evidence.trim() : "";
  const nowIso = runtimeNow(runtime).toISOString();
  const definition = reconciliationActionDefinition(action, nowIso);
  if (!Number.isSafeInteger(runId) || runId < 1 || !definition || evidence.length < 10 || evidence.length > RECONCILIATION_NOTE_MAX_LENGTH) {
    return new Response(JSON.stringify({ status: "error", message: "Invalid reconciliation request" }), {
      status: 400, headers: PRIVATE_JSON_HEADERS
    });
  }
  try {
    const existing = await env.DB.prepare(
      "SELECT pipeline_run_id, action FROM pipeline_reconciliation_events WHERE operation_key = ? LIMIT 1"
    ).bind(operationKey).first();
    if (existing) {
      const matches = Number(existing.pipeline_run_id) === runId && existing.action === action;
      return new Response(JSON.stringify({ status: matches ? "already_applied" : "conflict", runId, action }), {
        status: matches ? 200 : 409, headers: PRIVATE_JSON_HEADERS
      });
    }
    const eventInsert = env.DB.prepare(
      `INSERT INTO pipeline_reconciliation_events
        (operation_key, pipeline_run_id, action, previous_status,
         previous_notification_status, resulting_status,
         resulting_notification_status, evidence_summary, created_at)
       SELECT ?, r.id, ?, r.status, r.notification_status, ?, ?, ?, ?
       FROM pipeline_runs r WHERE r.id = ? AND ${definition.eligibility}`
    ).bind(
      operationKey, action, definition.resultingStatus,
      definition.resultingNotificationStatus, evidence, nowIso, runId,
      ...definition.eligibilityArgs
    );
    const stateUpdate = env.DB.prepare(definition.update).bind(
      ...definition.updateArgs, runId, ...definition.eligibilityArgs
    );
    const [eventResult, updateResult] = await env.DB.batch([eventInsert, stateUpdate]);
    if (statementChanges(eventResult) !== 1 || statementChanges(updateResult) !== 1) {
      throw new OperationError({
        stage: "pipeline_reconciliation", provider: "d1", errorCode: "state_conflict"
      });
    }
    return new Response(JSON.stringify({ status: "applied", runId, action }), {
      headers: PRIVATE_JSON_HEADERS
    });
  } catch (error) {
    logOperationFailure(error, "pipeline_reconciliation_action", "d1");
    const safe = normalizeOperationError(error, "pipeline_reconciliation", "d1");
    const status = safe.errorCode === "state_conflict" ? 409 : 500;
    return new Response(JSON.stringify({ status: "error", message: "Operation failed" }), {
      status, headers: PRIVATE_JSON_HEADERS
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
    const message = buildDiscordMessage(
      latestLog.content, latestLog.created_at, env.AMAZON_TAG, getSiteUrl(env), latestLog.id
    );
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

function utcDayBounds(date) {
  const start = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  return { start, end: new Date(start.getTime() + 24 * 60 * 60 * 1000) };
}

function pipelineDeadlineRuntime(runtime, startedAt) {
  const deadlineAt = Date.parse(startedAt) + PIPELINE_DEADLINE_MS;
  return { ...runtime, deadlineAt };
}

function deadlineRemainingMs(runtime) {
  if (!Number.isFinite(runtime.deadlineAt)) return Infinity;
  return runtime.deadlineAt - runtimeNow(runtime).getTime();
}

function pipelineDeadlineError(stage, provider = "worker") {
  return new OperationError({
    stage,
    provider,
    errorCode: "pipeline_deadline_exceeded",
    retryable: false
  });
}

function assertPipelineDeadline(runtime, stage, provider = "worker") {
  if (deadlineRemainingMs(runtime) <= 0) throw pipelineDeadlineError(stage, provider);
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
    "SELECT * FROM curation_logs WHERE pipeline_run_id = ? LIMIT 1"
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

  let existing;
  try {
    existing = await getPipelineRunByKey(db, specification.idempotencyKey);
  } catch {
    throw new OperationError({
      stage: "pipeline_acquire",
      provider: "d1",
      errorCode: "budget_check_failed",
      retryable: true
    });
  }
  if (existing) return { run: existing, acquired: false };

  const day = utcDayBounds(now);
  const hourStart = new Date(now.getTime() - 60 * 60 * 1000);
  let insertResult;

  try {
    insertResult = await db.prepare(
      `INSERT INTO pipeline_runs (
        execution_id, idempotency_key, trigger_type, scheduled_for,
        status, stage, attempt_count, notification_status,
        lease_expires_at, started_at, updated_at
      )
      SELECT ?, ?, ?, ?, 'running', 'gemini', 1, 'pending', ?, ?, ?
      WHERE (SELECT COUNT(*) FROM pipeline_runs WHERE started_at >= ? AND started_at < ?) < ?
        AND (
          (? = 'manual'
            AND (SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'manual' AND status IN ('running', 'saved')) < 1
            AND (SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'manual' AND started_at > ? AND started_at <= ?) < ?
            AND (SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'manual' AND started_at >= ? AND started_at < ?) < ?)
          OR
          (? = 'cron'
            AND (SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'cron' AND started_at >= ? AND started_at < ?) < ?)
        )`
    ).bind(
      executionId,
      specification.idempotencyKey,
      specification.triggerType,
      specification.scheduledFor,
      leaseExpiresAt,
      nowIso,
      nowIso,
      day.start.toISOString(),
      day.end.toISOString(),
      GLOBAL_DAILY_LIMIT,
      specification.triggerType,
      hourStart.toISOString(),
      nowIso,
      MANUAL_HOURLY_LIMIT,
      day.start.toISOString(),
      day.end.toISOString(),
      MANUAL_DAILY_LIMIT,
      specification.triggerType,
      day.start.toISOString(),
      day.end.toISOString(),
      CRON_DAILY_LIMIT
    ).run();
  } catch {
    // UNIQUE conflicts and ambiguous write results are resolved by reading the key.
  }

  let run;
  try {
    run = await getPipelineRunByKey(db, specification.idempotencyKey);
  } catch {
    throw new OperationError({
      stage: "pipeline_acquire",
      provider: "d1",
      errorCode: "budget_check_failed",
      retryable: true
    });
  }
  if (!run) {
    if (insertResult && statementChanges(insertResult) === 0) {
      let limitState;
      try {
        limitState = await db.prepare(
          `SELECT
            (SELECT COUNT(*) FROM pipeline_runs WHERE started_at >= ? AND started_at < ?) AS daily_total,
            (SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'manual' AND status IN ('running', 'saved')) AS active_manual,
            (SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'manual' AND started_at > ? AND started_at <= ?) AS hourly_manual,
            (SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'manual' AND started_at >= ? AND started_at < ?) AS daily_manual,
            (SELECT COUNT(*) FROM pipeline_runs WHERE trigger_type = 'cron' AND started_at >= ? AND started_at < ?) AS daily_cron,
            (SELECT MIN(started_at) FROM pipeline_runs WHERE trigger_type = 'manual' AND started_at > ? AND started_at <= ?) AS oldest_hourly_manual`
        ).bind(
          day.start.toISOString(), day.end.toISOString(),
          hourStart.toISOString(), nowIso,
          day.start.toISOString(), day.end.toISOString(),
          day.start.toISOString(), day.end.toISOString(),
          hourStart.toISOString(), nowIso
        ).first();
      } catch {
        throw new OperationError({
          stage: "pipeline_acquire",
          provider: "d1",
          errorCode: "budget_check_failed",
          retryable: true
        });
      }
      const limitError = new OperationError({
        stage: "pipeline_acquire",
        provider: "worker",
        errorCode: "pipeline_limit_exceeded"
      });
      const dayRetry = Math.ceil((day.end.getTime() - now.getTime()) / 1000);
      const hourlyRetry = limitState?.oldest_hourly_manual
        ? Math.ceil((Date.parse(limitState.oldest_hourly_manual) + 60 * 60 * 1000 - now.getTime()) / 1000)
        : 60 * 60;
      limitError.retryAfterSeconds = specification.triggerType === "manual" && Number(limitState?.hourly_manual) >= MANUAL_HOURLY_LIMIT
        ? Math.max(1, hourlyRetry)
        : Math.max(1, dayRetry);
      throw limitError;
    }
    throw new OperationError({
      stage: "pipeline_acquire",
      provider: "d1",
      errorCode: "write_failed"
    });
  }
  return { run, acquired: run.execution_id === executionId };
}

async function updateRunStage(db, runId, stage, runtime = {}) {
  assertPipelineDeadline(runtime, stage);
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
      (source_type, llm_name, content, created_at, pipeline_run_id,
       title, description, body_markdown, category,
       published_at, updated_at, seo_status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).bind(
    specification.sourceType,
    "Pro-Consensus Pipeline",
    article.content,
    nowIso,
    run.id,
    article.title,
    article.description,
    article.bodyMarkdown,
    article.category,
    article.publishedAt,
    article.updatedAt,
    article.seoStatus
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
  assertPipelineDeadline(runtime, "discord", "discord");
  const claimed = await claimNotification(env.DB, run.id, runtime);
  if (!claimed) return { outcome: "duplicate", runId: run.id, articleId: article.id };

  const message = buildDiscordMessage(
    article.content,
    article.created_at,
    env.AMAZON_TAG,
    optionalSiteUrl(env),
    article.id,
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
    if (safe.deliveryUnknown) {
      await env.DB.prepare(
        `UPDATE pipeline_runs
         SET status = 'saved', stage = 'discord', notification_status = 'sending',
             error_code = ?, error_http_status = ?, error_retryable = 0, error_summary = ?, updated_at = ?
         WHERE id = ?`
      ).bind(safe.errorCode, safe.httpStatus, safeErrorSummary(safe), nowIso, run.id).run();
      throw safe;
    }
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
    if (article.seo_status === "needs_review") {
      return { outcome: "needs_review", runId: run.id, articleId: article.id };
    }
    if (run.notification_status === "sending") {
      return { outcome: "notification_in_progress", runId: run.id, articleId: article.id };
    }
    if (run.status === "running") {
      return { outcome: "reconciliation_required", runId: run.id, articleId: article.id };
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
    return { outcome: "reconciliation_required", runId: run.id, articleId: null };
  }
  return { outcome: "in_progress", runId: run.id, articleId: null };
}

async function runReliablePipeline(env, specification, runtime = {}) {
  const acquisition = await acquirePipelineRun(env.DB, specification, runtime);
  const pipelineRuntime = pipelineDeadlineRuntime(runtime, acquisition.run.started_at);
  if (!acquisition.acquired) {
    return handleExistingPipelineRun(env, acquisition.run, specification, pipelineRuntime);
  }

  const run = acquisition.run;
  let stage = "gemini";
  try {
    await updateRunStage(env.DB, run.id, "gemini", pipelineRuntime);
    const draft = await callGemini(env.GEMINI_API_KEY, pipelineRuntime);
    stage = "claude";
    await updateRunStage(env.DB, run.id, stage, pipelineRuntime);
    const reviewed = await callClaude(env.CLAUDE_API_KEY, draft, pipelineRuntime);
    stage = "openai";
    await updateRunStage(env.DB, run.id, stage, pipelineRuntime);
    const finalArticle = await callOpenAI(env.OPENAI_API_KEY, reviewed, pipelineRuntime);
    stage = "seo_quality";
    await updateRunStage(env.DB, run.id, stage, pipelineRuntime);
    const seoArticle = await prepareSeoArticleForSave(env.DB, finalArticle, run.id, pipelineRuntime);
    stage = "d1_save";
    await updateRunStage(env.DB, run.id, stage, pipelineRuntime);
    const savedArticle = await saveArticleAndMarkSaved(env.DB, run, specification, seoArticle, pipelineRuntime);
    if (seoArticle.seoStatus === "needs_review") {
      return { outcome: "needs_review", runId: run.id, articleId: savedArticle.id };
    }
    assertPipelineDeadline(pipelineRuntime, "discord", "discord");
    return await sendSavedArticleNotification(env, { ...run, status: "saved" }, savedArticle, specification, pipelineRuntime);
  } catch (error) {
    const existingArticle = await getArticleForRun(env.DB, run.id);
    if (!existingArticle) await markPipelineFailed(env.DB, run.id, error, stage, pipelineRuntime);
    throw normalizeOperationError(error, stage, stage === "d1_save" ? "d1" : stage);
  }
}

async function runProConsensusPipeline(env, runtime = {}) {
  const draft = await callGemini(env.GEMINI_API_KEY, runtime);
  const reviewed = await callClaude(env.CLAUDE_API_KEY, draft, runtime);
  return callOpenAI(env.OPENAI_API_KEY, reviewed, runtime);
}

function buildDiscordMessage(content, createdAt, amazonTag, siteUrl, articleId, header = "📢 **【テクノロジー＆ビジネストレンド速報】**") {
  const keyword = determineAffiliateKeyword(content);
  const destination = typeof siteUrl === "string" && siteUrl !== "" && Number.isInteger(articleId) && articleId > 0
    ? affiliateRedirectUrl(siteUrl, articleId, "discord")
    : buildAmazonSearchUrl(content, amazonTag);
  const affiliateLink = `\n\n🛒 **おすすめアイテム（${keyword}）:** ${destination}`;
  return `${header}\n- **日時:** ${createdAt}\n\n${content}${affiliateLink}`;
}

function renderHomePage(results, options) {
  const { currentPage, totalPages, totalItems, siteUrl } = options;
  const canonicalUrl = currentPage === 1 ? `${siteUrl}/` : `${siteUrl}/?page=${currentPage}`;
  const pageSuffix = currentPage === 1 ? "" : ` | ${currentPage}ページ目`;
  const pageTitle = `テクノロジー＆ビジネストレンド最速まとめ速報${pageSuffix}`;
  const pageDescription = `AI、SaaS、セキュリティ、次世代インフラなど、最新のテクノロジーとビジネストレンドを分析・整理してお届けする情報メディアです。${currentPage === 1 ? "" : `現在は${currentPage}ページ目です。`}`;
  const previousUrl = currentPage === 2 ? `${siteUrl}/` : `${siteUrl}/?page=${currentPage - 1}`;
  const nextUrl = `${siteUrl}/?page=${currentPage + 1}`;
  const postsHtml = results.length > 0 ? results.map((row) => {
    const article = readSeoArticle(row);
    const dateStr = new Date(article.publishedAt).toLocaleString("ja-JP");
    const articleUrl = `/article/${escapeHtml(String(article.id))}`;

    return `
          <article class="post">
            <h2><a href="${articleUrl}">${escapeHtml(article.title)}</a></h2>
            <div class="meta">
              <span>公開日時: ${escapeHtml(dateStr)}</span>
              <span class="category">${escapeHtml(categoryLabel(article.category))}</span>
            </div>
            <p class="excerpt">${escapeHtml(article.description)}</p>
            <div class="read-more">
              <a href="${articleUrl}">続きを読む &rarr;</a>
            </div>
          </article>
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
    .post h2 { font-size: 19px; line-height: 1.5; margin: 0 0 10px; }
    .post h2 a { color: #111; text-decoration: none; }
    .post h2 a:hover { text-decoration: underline; }
    .meta { font-size: 12px; color: #888; margin-bottom: 10px; display: flex; gap: 15px; align-items: center; }
    .category { background: #edf4ff; border-radius: 999px; color: #1856a5; padding: 2px 8px; }
    .excerpt { font-size: 15px; line-height: 1.8; color: #222; margin: 0 0 15px; }
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
      "SELECT * FROM curation_logs ORDER BY id DESC LIMIT 1000"
    ).all();

    const publicArticles = (results ?? [])
      .map((row) => readSeoArticle(row))
      .filter((article) => isPublicArticle(article));
    const articleUrls = publicArticles
      .map((article) => {
      const lastmod = article.updatedAt
        ? new Date(article.updatedAt).toISOString()
        : new Date().toISOString();

      return `
  <url>
    <loc>${siteUrl}/article/${article.id}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>`;
      }).join("");

    const categoryUrls = [...new Set(publicArticles.map((article) => article.category))]
      .filter((category) => isPublicCategory(category))
      .sort()
      .map((category) => {
        const articles = publicArticles.filter((article) => article.category === category);
        const lastmod = new Date(Math.max(...articles.map((article) => Date.parse(article.updatedAt)))).toISOString();
        return `
  <url>
    <loc>${categoryUrl(siteUrl, category)}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
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
${categoryUrls}
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

function optionalSiteUrl(env) {
  return typeof env?.SITE_URL === "string" && env.SITE_URL.trim() !== "" ? getSiteUrl(env) : null;
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
    assertPipelineDeadline(runtime, options.stage, options.provider);
    const remainingMs = deadlineRemainingMs(runtime);
    const effectiveTimeoutMs = Math.max(1, Math.min(options.timeoutMs, remainingMs));
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), effectiveTimeoutMs);
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
      if (controller.signal.aborted && remainingMs <= options.timeoutMs) {
        operationError = pipelineDeadlineError(options.stage, options.provider);
      }
    } finally {
      clearTimeout(timer);
    }

    if (!operationError.retryable || attempt >= options.maxAttempts) {
      if (options.deliveryUnknownOnTransportFailure && ["timeout", "network_error", "pipeline_deadline_exceeded"].includes(operationError.errorCode)) {
        operationError.deliveryUnknown = true;
        operationError.retryable = false;
      }
      throw operationError;
    }

    if (options.deliveryUnknownOnTransportFailure && ["timeout", "network_error"].includes(operationError.errorCode)) {
      operationError.deliveryUnknown = true;
      operationError.retryable = false;
      throw operationError;
    }
    const delayMs = retryDelayMs(operationError, attempt, runtime);
    if (delayMs >= deadlineRemainingMs(runtime)) {
      throw pipelineDeadlineError(options.stage, options.provider);
    }
    await sleep(delayMs);
    assertPipelineDeadline(runtime, options.stage, options.provider);
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
    maxAttempts: DISCORD_MAX_ATTEMPTS,
    deliveryUnknownOnTransportFailure: true
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
            text: runtime.geminiInstruction || "現在(2026年8月)、世界のビジネス市場やテクノロジー全体（生成AI、SaaS、クラウド、サイバーセキュリティ、次世代インフラ、DX、組織マネジメント等）において最も狂気と変革をもたらしている最先端トレンドを1つ選定し、経営者や実務家の心を揺さぶる骨太な一次ドラフトを執筆してください。"
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
