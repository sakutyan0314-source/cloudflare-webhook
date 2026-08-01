export interface Env {
  DISCORD_WEBHOOK_URL: string;
  AMAZON_TAG?: string;
  DB?: D1Database;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/test") {
      const report = await generateReport(env);
      return new Response(report, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
    return new Response("Automated Monetization Pipeline is running.", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  },

  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(sendAutomatedReport(env));
  },
};

async function generateReport(env: Env): Promise<string> {
  try {
    const tag = env.AMAZON_TAG || "tyansanku3325-22";
    // 正常系・動的アフィリエイトリンク付帯ロジック
    const sampleItem = "最新ビジネス・AIトレンド書籍";
    const encodedQuery = encodeURIComponent(sampleItem);
    const affiliateUrl = `https://www.amazon.co.jp/s?k=${encodedQuery}&tag=${tag}`;

    const reportContent = `【自動定期レポート】\n本日のピックアップ情報：\n- **${sampleItem}**\n- 詳細・購入リンク: ${affiliateUrl}`;
    return reportContent;
  } catch (error) {
    // 異常系・フォールバック処理（プロセス全体のクラッシュを防止）
    console.error("Report generation error:", error);
    return "【自動定期レポート】\n本日の情報収集中に一時的なエラーが発生しましたが、システムは正常稼働を維持しています。";
  }
}

async function sendAutomatedReport(env: Env): Promise<void> {
  const webhookUrl = env.DISCORD_WEBHOOK_URL;
  if (!webhookUrl) {
    console.error("Discord Webhook URL is not configured.");
    return;
  }

  const content = await generateReport(env);

  const response = await fetch(webhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });

  if (!response.ok) {
    console.error("Failed to send report to Discord:", await response.text());
  }
}
