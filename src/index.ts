
function attachAffiliateLink(targetUrl, affiliateId) {
  try {
    if (!targetUrl || typeof targetUrl !== "string" || !targetUrl.startsWith("http")) {
      return targetUrl;
    }
    const urlObj = new URL(targetUrl);
    if (urlObj.searchParams.has("tag") || urlObj.searchParams.has("aff_id")) {
      return targetUrl;
    }
    urlObj.searchParams.set("tag", affiliateId);
    return urlObj.toString();
  } catch (error) {
    console.error("Affiliate link attachment failed:", error);
    return targetUrl;
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === '/test-dispatch') {
      try {
        await executeReportPipeline(env);
        return new Response('レポートの即時配信テストが正常に完了しました。', { status: 200 });
      } catch (error) {
        return new Response(`配信エラー: ${error.message}`, { status: 500 });
      }
    }
    return new Response('Zero Capital Pipeline Active', { status: 200 });
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(executeReportPipeline(env));
  },
};

async function executeReportPipeline(env) {
  const { results } = await env.DB.prepare(
    "SELECT title, url, category FROM items ORDER BY created_at DESC LIMIT 5"
  ).all();

  if (!results || results.length === 0) {
    console.log("配信対象のデータがありません。");
    return;
  }

  const formattedItems = results.map((item) => {
    const affiliateUrl = attachAffiliateTag(item.url);
    return `• [${item.title}](${affiliateUrl})`;
  }).join("\n");

  const message = `【自動定期レポート】\n本日のピックアップ情報:\n\n${formattedItems}`;

  const response = await fetch(env.DISCORD_WEBHOOK_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: message }),
  });

  if (!response.ok) {
    throw new Error(`Discord通知に失敗しました: ${response.statusText}`);
  }
}

function attachAffiliateTag(originalUrl) {
  if (originalUrl.includes("example.com")) {
    return `${originalUrl}?tag=your_affiliate_id-22`;
  }
  return originalUrl;
}
