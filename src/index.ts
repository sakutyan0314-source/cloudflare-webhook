// src/index.ts (Clean ES Module Format - Phase 2 Affiliate Optimization)

const HTML_HEADERS = { "Content-Type": "text/html; charset=utf-8" };
const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };
const TEXT_HEADERS = { "Content-Type": "text/plain; charset=utf-8" };

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "") {
      return handleHomePage(env, url);
    }
    if (url.pathname === "/sitemap.xml") {
  return handleSitemap(env, url);
}
    const articleMatch = url.pathname.match(/^\/article\/(\d+)\/?$/);

if (articleMatch) {
  return handleArticlePage(env, articleMatch[1]);
}
    if (url.pathname === "/test-multillm") {
      return handleTestMultiLlm(env);
    }
    if (url.pathname === "/view-logs") {
      return handleViewLogs(env);
    }
    if (url.pathname === "/test-discord") {
      return handleTestDiscord(env);
    }
    if (url.pathname === "/get-task") {
      return handleGetTask(request, env);
    }
    if (url.pathname === "/test") {
      try {
        await sendAutomatedReport(env);
        const report = await generateReport(env);
        return new Response(
          `[テスト実行成功] Discordへ通知を送信しました。\n\n${report}`,
          { headers: TEXT_HEADERS }
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return new Response(`テスト実行エラー: ${message}`, {
          status: 500,
          headers: TEXT_HEADERS
        });
      }
    }
    return new Response("Not Found", { status: 404, headers: TEXT_HEADERS });
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runScheduledPipeline(env));
  }
};

async function handleHomePage(env, url) {
  try {
    const pageParam = parseInt(url.searchParams.get("page") || "1", 10);
    const currentPage = Number.isNaN(pageParam) || pageParam < 1 ? 1 : pageParam;
    const perPage = 5;
    const offset = (currentPage - 1) * perPage;
    const countResult = await env.DB.prepare(
      "SELECT COUNT(*) as total FROM curation_logs"
    ).first();
    const totalItems = countResult?.total ?? 0;
    const totalPages = Math.ceil(totalItems / perPage) || 1;
    const { results } = await env.DB.prepare(
      "SELECT * FROM curation_logs ORDER BY id DESC LIMIT ? OFFSET ?"
    ).bind(perPage, offset).all();
    const affiliateTag = env.AMAZON_TAG || "default-22";
    const html = renderHomePage(results ?? [], {
      affiliateTag,
      currentPage,
      totalPages,
      totalItems
    });
    return new Response(html, { headers: HTML_HEADERS });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return new Response(`サイトの読み込み中にエラーが発生しました: ${message}`, {
      status: 500,
      headers: TEXT_HEADERS
    });
  }
}
async function handleArticlePage(env, articleId) {
  try {
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

    const html = `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(pageTitle)}</title>
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
    const message =
      error instanceof Error ? error.message : String(error);

    console.error("Article page error:", error);

    return new Response(
      `記事の読み込み中にエラーが発生しました: ${message}`,
      {
        status: 500,
        headers: TEXT_HEADERS
      }
    );
  }
}
async function handleTestMultiLlm(env) {
  const timestamp = (new Date()).toISOString();
  try {
    const finalArticle = await runProConsensusPipeline(env);
    await saveToD1(env.DB, "pro_consensus_summary", "Pro-Consensus Pipeline", finalArticle, timestamp);
    return new Response(
      JSON.stringify({ status: "completed_deep_consensus", article: finalArticle }, null, 2),
      { headers: JSON_HEADERS }
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return new Response(JSON.stringify({ status: "error", message }, null, 2), {
      status: 500,
      headers: JSON_HEADERS
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
      { headers: JSON_HEADERS }
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return new Response(JSON.stringify({ status: "error", message }, null, 2), {
      status: 500,
      headers: JSON_HEADERS
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
        { status: 404, headers: JSON_HEADERS }
      );
    }
    const latestLog = results[0];
    const message = buildDiscordMessage(latestLog.content, latestLog.created_at, env.AMAZON_TAG);
    const discordRes = await sendToDiscord(env.DISCORD_WEBHOOK_URL, message);
    return new Response(
      JSON.stringify({ status: "discord_sent_success", discordResponse: discordRes }, null, 2),
      { headers: JSON_HEADERS }
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return new Response(JSON.stringify({ status: "error", message }, null, 2), {
      status: 500,
      headers: JSON_HEADERS
    });
  }
}

async function runScheduledPipeline(env) {
  console.log("Cron triggered: Running Deep Pro-Consensus pipeline...");
  try {
    const finalArticle = await runProConsensusPipeline(env);
    const timestamp = (new Date()).toISOString();
    await saveToD1(env.DB, "cron_pro_consensus", "Pro-Consensus Pipeline", finalArticle, timestamp);
    const message = buildDiscordMessage(
      finalArticle,
      timestamp,
      env.AMAZON_TAG,
      "🚀 **【自動速報配信（ビジネストレンド）】**"
    );
    await sendToDiscord(env.DISCORD_WEBHOOK_URL, message);
  } catch (error) {
    console.error("Error in scheduled execution:", error);
  }
}

async function runProConsensusPipeline(env) {
  const draft = await callGemini(env.GEMINI_API_KEY);
  const reviewed = await callClaude(env.CLAUDE_API_KEY, draft);
  return callOpenAI(env.OPENAI_API_KEY, reviewed);
}

function buildDiscordMessage(content, createdAt, amazonTag, header = "📢 **【テクノロジー＆ビジネストレンド速報】**") {
  const affiliateTag = amazonTag || "default-22";
  const keyword = determineAffiliateKeyword(content);
  const encodedKeyword = encodeURIComponent(keyword);
  const affiliateLink = `\n\n🛒 **おすすめアイテム（${keyword}）:** https://www.amazon.co.jp/s?k=${encodedKeyword}&tag=${affiliateTag}`;
  return `${header}\n- **日時:** ${createdAt}\n\n${content}${affiliateLink}`;
}

function renderHomePage(results, options) {
  const { affiliateTag, currentPage, totalPages, totalItems } = options;
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
  <title>テクノロジー＆ビジネストレンド最速まとめ速報</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: #f7f9fa; color: #333; margin: 0; padding: 20px; }
    .container { max-width: 800px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
    h1 { font-size: 24px; border-bottom: 2px solid #eaeaea; padding-bottom: 10px; margin-top: 0; color: #111; }
    .post { border-bottom: 1px solid #eee; padding: 25px 0; }
    .post:last-child { border-bottom: none; }
    .meta { font-size: 12px; color: #888; margin-bottom: 10px; display: flex; gap: 15px; align-items: center; }
    .content { font-size: 15px; line-height: 1.8; color: #222; margin-bottom: 15px; white-space: pre-line; }
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
async function handleSitemap(env, url) {
  try {
    const { results } = await env.DB.prepare(
      "SELECT id, created_at FROM curation_logs ORDER BY id DESC LIMIT 1000"
    ).all();

    const baseUrl = url.origin;

    const articleUrls = (results ?? []).map((row) => {
      const lastmod = row.created_at
        ? new Date(row.created_at).toISOString()
        : new Date().toISOString();

      return `
  <url>
    <loc>${baseUrl}/article/${row.id}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>`;
    }).join("");

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>${baseUrl}/</loc>
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
    const message = error instanceof Error ? error.message : String(error);

    return new Response(`Sitemap generation error: ${message}`, {
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

async function sendToDiscord(webhookUrl, content) {
  if (!webhookUrl) throw new Error("DISCORD_WEBHOOK_URL is not configured.");
  const response = await fetch(webhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content })
  });
  if (!response.ok) throw new Error(`Discord API Error: HTTP ${response.status}`);
  return "Message sent successfully to Discord.";
}

async function saveToD1(db, sourceType, llmName, content, createdAt) {
  if (!db) return;
  try {
    await db.prepare(
      "INSERT INTO curation_logs (source_type, llm_name, content, created_at) VALUES (?, ?, ?, ?)"
    ).bind(sourceType, llmName, content, createdAt).run();
  } catch (error) {
    console.error(`Failed to save to D1 for ${llmName}:`, error);
  }
}

async function callGemini(apiKey) {
  if (!apiKey) throw new Error("GEMINI_API_KEY is missing");
  const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=${apiKey}`;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contents: [{
        parts: [{
          text: "現在(2026年8月)、世界のビジネス市場やテクノロジー全体（生成AI、SaaS、クラウド、サイバーセキュリティ、次世代インフラ、DX、組織マネジメント等）において最も狂気と変革をもたらしている最先端トレンドを1つ選定し、経営者や実務家の心を揺さぶる骨太な一次ドラフトを執筆してください。"
        }]
      }]
    })
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  return data.candidates?.[0]?.content?.parts?.[0]?.text || "No response";
}

async function callClaude(apiKey, draftText) {
  if (!apiKey) throw new Error("CLAUDE_API_KEY is missing");
  const response = await fetch("https://api.anthropic.com/v1/messages", {
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
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  return data.content?.[0]?.text || "No response";
}

async function callOpenAI(apiKey, reviewedText) {
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  const response = await fetch("https://api.openai.com/v1/chat/completions", {
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
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  return data.choices?.[0]?.message?.content || "No response";
}

async function generateReport(env) {
  try {
    const tag = env.AMAZON_TAG || "tyansaku3325-22";
    const sampleItem = "最新ビジネスAIトレンド書籍";
    const encodedQuery = encodeURIComponent(sampleItem);
    const affiliateUrl = `https://www.amazon.co.jp/s?k=${encodedQuery}&tag=${tag}`;
    return `【自動定期レポート】\n本日のピックアップ情報：\n- **${sampleItem}**\n- 詳細・購入リンク: ${affiliateUrl}`;
  } catch (error) {
    console.error("Report generation error:", error);
    return "【自動定期レポート】\n本日の情報収集中に一時的なエラーが発生しましたが、システムは正常稼働を維持しています。";
  }
}

async function sendAutomatedReport(env) {
  const webhookUrl = env.DISCORD_WEBHOOK_URL;
  if (!webhookUrl) {
    console.error("Discord Webhook URL is not configured.");
    return;
  }
  const content = await generateReport(env);
  const response = await fetch(webhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content })
  });
  if (!response.ok) {
    console.error("Failed to send report to Discord:", await response.text());
  }
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