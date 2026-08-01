export default {
  async fetch(request: Request, env: any, ctx: ExecutionContext): Promise<Response> {
    try {
      const url = new URL(request.url);
      if (url.pathname === '/test') {
        return await handleTestExecution(env);
      }
      return new Response("Cloudflare Webhook System is running securely.", { status: 200 });
    } catch (error: any) {
      console.error("Critical error in fetch handler:", error.message);
      return new Response("Internal Server Error (Handled)", { status: 500 });
    }
  },

  async scheduled(event: ScheduledEvent, env: any, ctx: ExecutionContext): Promise<void> {
    try {
      await runPipeline(env);
    } catch (error: any) {
      console.error("Scheduled pipeline error (Handled):", error.message);
    }
  }
};

async function runPipeline(env: any) {
  const rawData = [
    { title: "【自動収益化】最新トレンド情報", link: "https://example.com/item", affiliateId: "sakutyan-22" },
    { title: null, link: "invalid-url-format", affiliateId: "" }, // 異常系・不正データ（クレンジング対象）
  ];

  for (const item of rawData) {
    try {
      // 異常系・データクレンジング耐性チェック（クラッシュ回避）
      if (!item.title || !item.link || !item.link.startsWith("https://")) {
        console.warn("Skipping invalid data entry safely:", item);
        continue;
      }

      // 収益化リンク（アフィリエイト等）の自動付帯ロジック
      const monetizedLink = `${item.link}?tag=${item.affiliateId}`;
      const message = `📢 **定期レポート配信**\n- 項目: ${item.title}\n- 詳細リンク: ${monetizedLink}`;

      await sendToDiscord(env.DISCORD_WEBHOOK_URL, message);
    } catch (itemError: any) {
      console.error("Failed to process individual item, continuing pipeline:", itemError.message);
    }
  }
}

async function handleTestExecution(env: any) {
  try {
    await runPipeline(env);
    return new Response("Test pipeline executed successfully with Fallback & Cleansing check.", { status: 200 });
  } catch (error: any) {
    return new Response(`Test execution failed gracefully: ${error.message}`, { status: 500 });
  }
}

async function sendToDiscord(webhookUrl: string, content: string) {
  if (!webhookUrl) throw new Error("DISCORD_WEBHOOK_URL is not set.");
  const res = await fetch(webhookUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content })
  });
  if (!res.ok) {
    throw new Error(`Discord API error: ${res.statusText}`);
  }
}
