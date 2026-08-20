# Master Blueprint v2.1

## ゼロキャピタル＆マルチエージェント型 自律ビジネス拡張システム

**制定日:** 2026-08-09  
**最終同期日:** 2026-08-20
**文書状態:** 正式基準文書 v2.1（現在HEAD・本番確認済み状態・未反映状態を分離して記録）
**対象プロジェクト:** `cloudflare-webhook` を第1号事業エンジンとする会社構想全体  
**管理原則:** 本文書を会社構想・技術開発・AI運用の Single Source of Truth とする

---

## 1. この設計図の目的

本設計図は、単なるサイト開発メモではない。会社が何を目指し、現在どこまで実現し、次に何を行い、どの条件で事業を拡張するかを一貫して判断するための基準文書である。

今後、担当する人間・AI・開発環境・チャットが変わっても、次の事項を維持する。

- 最終ビジョンを短期施策より優先する
- 実装済みの事実と将来構想を混同しない
- 第1号事業で閉じた収益・改善ループを作ってから横展開する
- 人間が重要判断と不可逆操作を統制する
- ゼロキャピタル原則を守り、実収益を再投資して拡張する
- 変更の根拠、検証結果、履歴を残し、再現可能にする

## 2. 最終ビジョン

複数のAIエージェントが役割分担し、次の事業サイクルを継続的に実行する自律型企業システムを構築する。

> 生成 → 公開 → 集客 → 収益 → 計測 → 分析 → 改善 → 再投資 → 事業横展開

最終状態では、各エージェントが共通データと会社方針を参照し、施策を提案・実行・評価する。人間は会社の所有者・最終意思決定者として、目的、予算、リスク許容度、重要な外部操作を統制する。

目標は「記事を自動生成するサイト」ではない。第1号事業で獲得した技術、データ、収益、運用知識を再利用し、新しい収益エンジンを低コストで立ち上げ続ける会社基盤を作ることである。

## 3. 会社の基本原則

### 3.1 ゼロキャピタル原則

- 初期段階は無料枠、既存資産、自動化を優先する
- 継続費用を発生させる前に、期待効果・上限・停止条件を定める
- 収益は計測可能な施策へ段階的に再投資する
- 売上ではなく、費用控除後の利益と再現性を重視する

### 3.2 小さな閉ループを先に完成させる

会社全体を同時に作らず、第1号事業で以下を実証する。

1. コンテンツまたは価値を自動生成できる
2. 安全に公開・配信できる
3. ユーザーを獲得できる
4. 収益が発生する
5. 行動・成果・費用を計測できる
6. データから改善案を作れる
7. 改善を安全に反映し、効果を比較できる

### 3.3 事実と構想の分離

すべての機能・施策を、次のいずれかで管理する。

- **本番確認済み:** 本番環境で動作を確認した
- **実装済み・未反映:** ローカル実装または検証済みだが、本番未反映
- **計画中:** 優先順位と目的が合意されている
- **構想:** 長期候補であり、実装・採用は未決定

「予定がある」ことを「実装済み」と表現してはならない。

### 3.4 安全と可逆性

- 読み取り、ローカル実装、テストなど安全で可逆な作業はまとめて進める
- 本番デプロイ、Git push、外部公開は事前状態と差分を確認する
- D1データ削除、履歴書き換え、force push、認証・課金変更など重大操作は人間の明示確認を必須とする
- 想定外の差分・対象環境・権限問題を検出したら停止し、勝手に復元・削除しない
- シークレットをコード、ログ、設計図、Git履歴へ保存しない

### 3.5 変更完了の必須工程

機能・安全基盤・運用コード・schema・設定の変更は、規模にかかわらず次の順序で完了を判断する。

1. コード変更
2. migration変更（必要な場合のみ）
3. ローカルテスト・構文・差分確認
4. 本番影響確認（必要な場合はread-only preflight）
5. `MASTER_BLUEPRINT.md` 更新
6. 関連運用文書更新
7. 意図したファイルだけをcommit・push

設計書または関連運用文書の更新を省いた「実装完了」報告は禁止する。本番反映の有無は、Git commitやローカルテストではなく、Cloudflare/D1のread-only確認で区別する。

## 3.6 2026-08-20時点の正規状態

この節は、以降に残る旧versionの変更履歴より優先する。旧記録は経緯の証跡であり、現行設計または現行本番状態の根拠には使用しない。

### 実装・Git

- 正規HEADは、このv2.1同期commitを含む `main` とする。`main` と `origin/main` は同期済みであることを、commit/pushごとに確認する。
- Worker entrypointは `src/index.ts`、Worker名は `cloudflare-webhook`、D1 bindingは `DB`、公開URLは `SITE_URL`、Cronは `0 23 * * *`（UTC、毎日08:00 JST）である。
- package/lockfileでWrangler `4.120.0` をexact固定する。Worker deployは `npx` および `bin/wrangler.js` を通さず、repository内の `node_modules/wrangler/wrangler-dist/cli.js` をNodeから直接一回だけ起動し、必ず `--config ./wrangler.toml` を渡す。
- deploy CLIはAccount・Git HEAD・repository root・固定Wrangler・tracked working treeを事前検証する。tokenは子process環境の `CLOUDFLARE_API_TOKEN` にのみ渡し、argv・監査値・例外・出力へ保存しない。retry、fallback、自動redeploy、`--yes` は禁止する。
- deploy監査では、**process result**（`failed_before_upload`、`failed_after_upload`、`signal_terminated`、`timeout`、`completed_with_version_marker`、`completed_without_version_marker`）と、**deployment outcome**（`succeeded`、`failed`、`unknown`、`not_attempted`）を分離する。Version ID marker、単一version、traffic 100%、PRE/POST version差を確認できた場合だけ outcome を `succeeded` とする。signal、timeout、marker欠落、upload後失敗、post-check不能、version不変、traffic不一致は fail-closed で `unknown` とする。
- deployの非0終了ではraw stdout/stderrを保存せず、許可リスト化した `error_classification`、`error_stage`、Cloudflare numeric error code、OS error name、固定 `error_summary` だけを出力できる。分類不能時も `unknown_preupload_error` / `preupload_unknown` / `unclassified_preupload_failure` として停止し、本文を出力しない。
- `unknown_preupload_error` の直接原因は確定済みである。Wrangler 4.120.0は親ディレクトリ `/Users/hashimotoyuma/wrangler.jsonc` を優先解決し、その `assets.directory = "."` によりホームディレクトリ全体をAsset manifestとして再帰走査してpreupload OOMを発生させた。`scripts/worker_deploy_wrapper.py` は `--config ./wrangler.toml` を明示し、通常bundle経路の `deploy --dry-run` がOOMなしで完走することを確認済みである。この修正はWorkerコード・binding・D1 schemaを変更しないためmigrationは不要である。commit `822425062a960286c094997534127f9548e8dcd4` は本番deploy済みで、PRE_DEPLOY_VERSION `723ce89c-81d0-4eb9-9825-769cd6bca66f` からWorker Version `1ef61585-c14d-4a24-ba02-2836acdea61b` への更新を確認した。続くカテゴリ内部リンクのcommit `5aff02d81c4abde1474424cab5da8bd1080680c3` は、PRE_DEPLOY_VERSION `1ef61585-c14d-4a24-ba02-2836acdea61b` から現行Worker Version `c269c6de-f5dc-46ec-b1aa-61595b904993` への更新、post-deploy verification、単一version 100% traffic、OOM非再発を確認済みである。

### D1 schema・監査・pipeline

- 本番D1は `zero-capital-insight-db`（ID `99ef2162-afd8-459a-87eb-d197127528e2`）であり、migration `0001`〜`0010` が適用済みである。`0010_seo_execution_transactions.sql`はExecution Attempt/Event/Post Verificationの専用table・index・append-only triggerだけを追加し、適用後にFK check 0、新規3 table空、authorization flag違反0を確認した。記事変更、Attempt開始、Approval消費、Worker/Cron/deployは行っていない。
- `0007_quality_gate_audits.sql` は `quality_gate_audits`、`quality_gate_audit_checks`、`quality_gate_audit_reasons` と4 indexを追加する。通常pipelineは品質監査の永続保存成功前に記事保存へ進まない。`fail` は記事保存・Discordを行わず、`needs_review` は公開経路へ進めない。
- `0008_production_executions.sql` は approved canary の single-use execution/event監査を追加する。`approved_canary` 以外のtrigger、状態逆行、`publication_authorized=1` は制約で拒否する。
- `0009_publication_boundary.sql` は `content_staging_drafts`、`publication_executions`、`publication_execution_events` を追加する。draftは `curation_logs` と別tableであり、QualityGateAudit PASS、Production Execution成功、PublicationApproval、fingerprint一致、single-use publication executionをすべて満たすまで公開しない。
- 通常pipelineは `running → saved → completed/failed`、通知は `pending → sending → sent/failed` を追跡する。`sending`、stale `running`、保存済み未通知は reconciliation の条件付き更新と人間確認で扱い、自動的な結果推測・重複通知は行わない。
- `PRAGMA foreign_key_check = 0`、新規5 table空、`running/sending/reconciliation/unresolved outcome = 0` は、最後の本番read-only preflightで確認済みの時点情報である。以後の本番状態は都度read-onlyで再確認する。

### SEO・公開・計測

- SEO article foundationは title/description/body/category/published/updated/seo status、canonical、OGP、Twitter Card、Article JSON-LD、pagination、category、related articles、sitemap、robots、Search Console verification tagを含む。
- 通常公開対象は `curation_logs` の公開可能な記事だけである。`content_staging_drafts` はトップ、category、pagination、sitemap、related articles、`/article/:id`、Discordに露出しない。
- Search Consoleのsync/page/query観測tableとaffiliate click event tableはD1 schemaに存在する。分析・投入・外部API実行はそれぞれ個別の承認境界を持ち、通常Cronや記事公開へ自動接続しない。
- Phase 2Aの改善候補抽出は、ready記事に紐付く`page_daily`を直近・前回の各7日でread-only比較し、十分性を満たす固定reason codeだけを人間確認用の候補一覧へ出力する。AI呼び出し、候補保存、記事変更、publicationは行わない。
- Phase 2A.5は、Phase 2A候補と既存のready記事metadataをread-onlyで結合し、`phase-2a-improvement-candidate-review-v1`の`pending_review` envelopeへ正規化する。`recommendation_type`は上位分類`seo_review`、詳細根拠は固定`reason_code`で表す。status変更・候補保存・AI呼び出し・記事変更・publicationは行わない。
- Phase 2A.6は、Phase 2A.5 envelopeから`seo-improvement-review-record-v1`のappend-only review recordを純粋関数で生成する。statusは`pending_review`、`accepted`、`rejected`、`deferred`のみで、acceptedは将来の改善案生成候補という人間判断に限る。D1保存、AI実行、記事変更、publication、deployの権限は与えない。
- Phase 2B-1は、accepted SEO reviewと一致するPhase 2A.5 envelopeから、provider非接続の`seo-improvement-proposal-input-v1`とmock検証用`seo-improvement-proposal-v1`を生成する。proposal IDはcandidate fingerprint、accepted review ID、proposal version、model version、proposal内容から決定的に導出する。proposalは常にhuman review必須かつAI実行・記事変更・publication・execution非許可である。
- Phase 2B-2は、Phase 2B-1 inputを固定OpenAI/Terra (`gpt-5.6-terra`) の単発Responses API adapterへ渡し、structured JSON出力を`seo-improvement-proposal-v1`として再構成・検証する。retry/fallback/toolsなし、`store=false`、timeoutとtoken上限を固定する。proposal保存、記事変更、publication、Worker接続は行わない。
- Phase 2B-3.1は、検証済み`seo-improvement-proposal-v1`を対象にcanonical proposal全体の完全SHA-256 fingerprintと`seo-improvement-proposal-review-record-v1`のappend-only review chainを純粋関数で扱う。statusは`pending_review`、`accepted`、`rejected`、`deferred`のみで、記事変更・publication・executionの権限は常にfalseである。
- Phase 2C-1は、最新statusがacceptedのproposal review chainと一致するproposalから、抽象的な`change_units`と固定のSearch Console検証計画だけを含む`seo-improvement-change-plan-v1`を生成する。planは`pending_review` snapshotであり、記事変更・publication・executionの権限は常にfalseである。
- Phase 2C-2.1は、検証済みChange Plan snapshotから`seo-improvement-change-plan-review-record-v1`のappend-only review chainを純粋関数で生成する。statusは`pending_review`、`accepted`、`rejected`、`deferred`のみで、acceptedは将来のChange Candidate作成候補という人間判断に限る。記事変更・publication・executionの権限は常にfalseである。
- Phase 2D-1は、最新statusがacceptedのChange Plan review chainとread-only article snapshotから、`snippet`のtitle/description候補だけを含む`seo-improvement-change-candidate-v1`を生成する。本文全文・body変更・SQL・D1 update・実行/公開権限は含めず、before snapshotの本文はSHA-256だけで表す。
- Phase 2D-2.1は、検証済みChange Candidate snapshotから`seo-improvement-change-candidate-review-record-v1`のappend-only review chainを純粋関数で生成する。statusは`pending_review`、`accepted`、`rejected`、`deferred`のみで、acceptedは将来のExecution Candidate作成候補という人間判断に限る。記事変更・publication・executionの権限は常にfalseである。
- Phase 2E-1は、最新statusがacceptedのChange Candidate review chainから、`snippet`のtitle/description差分だけを含む`seo-improvement-execution-candidate-v1`の実行前固定snapshotを純粋関数で生成する。before/after snapshotとexpected diffはcanonical SHA-256で固定し、最新read-only snapshotとの完全一致を要求する。Execution Approval、記事変更、D1 write、publication、executionの権限は含めない。
- Phase 2E-2.1は、検証済みSEO Execution Candidateから`seo-improvement-execution-approval-v1`のimmutable approval recordを純粋関数で生成する。承認は30分以内・single-use・全source identity一致・最新read-only snapshot一致を要求し、使用済みIDの検証は呼出側から渡された集合だけで行う。Approval自体は記事変更・publication・executionの権限を与えない。
- Phase 2F-1は、approved SEO Execution Approval、Execution Candidate、最新read-only snapshotから、`seo-improvement-execution-preflight-v1`のゼロ書込みpreflight snapshotを純粋関数で生成する。Approval/TTL/single-use/stale/final diffを完全照合し、`changed_db=false`、`rows_written=0`、`execution_authorized=false`を固定する。conditional UPDATE、D1保存、実行、publicationは行わない。
- Phase 2F-2.1は、検証済みSEO Execution Preflightから`seo-improvement-execution-attempt-v1`のimmutable attempt fact、post-verification schema、rollback candidateを純粋関数で生成する。状態遷移はforward-onlyで、実行結果不明は`outcome_unknown`として停止する。いずれもD1 transaction・conditional UPDATE・rollback execution・publicationを実装しない。
- Phase 2F-3.1は、`0010_seo_execution_transactions.sql`でSEO Attempt、append-only event、post-verificationの専用tableを追加し、ローカルSQLite専用repositoryでApproval reservation、CAS state transition、event保存、post-verification保存を検証する。conditional UPDATEはtitle/descriptionのSQL構成とRETURNING監査だけで、Worker/D1 transport・実記事更新・publication・deployには接続しない。
- Phase 2F-7は、production未接続のread adapter、fixed-SQL write builder、read-only preflight/dry-run、manual-only operator boundaryを追加する。すべて注入mock transportまたはpure inputだけを扱い、token source・D1 write transport・Worker/Cron入口・実記事更新を持たない。
- Phase 2F-8は、`0010`未適用状態のread-only migration preflight、target identity、fixed write-SQL whitelist、zero-write dry-run report、operator preflight orchestrationを追加する。production binding・migration apply・D1 write・Worker/Cron接続は含めない。
- Phase 2F-9は、`0010`のSHA-256、target identity、backup/bookmark/export証跡、FK/schema preflightを検証し、`dry_run_only=true`かつ`apply_authorized=false`固定のmigration apply checklistを生成する。migration apply・D1 write・Worker/Cron接続は含めない。
- Phase 2F-10では、承認済み`0010_seo_execution_transactions.sql`を本番D1へ一度だけ適用した。migration record ID 10、3 table、index、2 append-only trigger、FK check、新規table空、authorization flag違反0をread-only post-checkで確認した。Execution adapterは未接続であり、記事変更・Attempt・Approval消費・publication・Worker/Cron/deployは実施していない。
- Phase 2F-11は、適用済み`0010`、target identity、Candidate/Approval/Preflight/stale/expected diff、fixed SQL whitelistを確認するread-only first-execution dry-run runnerを追加する。reportは`changed_db=false`、`rows_written=0`、Approval未消費に固定し、D1 write・記事変更・Attempt INSERTを行わない。

### internal canary route

- `POST /internal/approved-canary` と `POST /internal/approved-canary/publication` は `OPERATIONS_API_TOKEN` のBearer認証、POST、JSON、16 KiB上限、未知field拒否、固定trigger、承認済みID群の完全性検証を要求する。制作入口では `pipeline_run_id` も正の安全整数として入口で検証する。
- runtime dependencyが未設定なら503でfail-closedする。deployだけでAI、Production Execution、staging、publication、`curation_logs` 追加、Discordを開始しない。現時点ではruntime未接続のため、approved canary/publicationは本番実行可能と扱わない。
- Cron `scheduled → runScheduledPipeline → runReliablePipeline`、手動pipeline、public GET routeとは完全に分離する。

## 4. 現在の事業モデル

### 4.1 第1号事業エンジン

テクノロジーとビジネストレンドを扱う自動メディアを運営し、コンテンツ生成、検索流入、Amazonアソシエイト等の収益導線を検証する。

このメディアの目的は、短期的な記事数の増加だけではない。将来の事業で再利用できる以下の能力を獲得することである。

- 複数LLMによる生成・レビュー工程
- 定期実行と公開
- SEOと検索エンジンへの発見
- コンテンツ・流入・収益の計測
- データに基づく改善
- 別テーマ・別市場への複製

### 4.2 現在の収益導線

- Amazonアソシエイト検索リンク
- 記事テーマからアフィリエイトキーワードを選択
- 一覧ページと個別記事ページに導線を配置

現時点では、収益導線は存在するが、クリック、成約、売上、記事別収益を結ぶ計測基盤は未完成である。したがって「収益化エンジン完成」とは扱わない。

### 4.3 初期収益目標と利益配分原則

第1段階では、**月間30〜40万円以上の利益**を初期経営目標の一つとする。

ここでいう利益は、売上ではなく、事業運営に直接必要な外部API、インフラ、ツール、外注その他の費用を控除した後の利益を基本とする。具体的な算定方法は、計測基盤の整備時に定義し、継続して同じ基準で比較できるようにする。

この目標は会社の成長方向を示すものであり、固定的な達成期限や変更不能な契約ではない。実データ、市場環境、事業の安全性、収益性、創業者の状況に応じて、創業者の承認により更新できる。

利益が安定して発生する段階では、初期原則として利益を次のように配分する。

- **約50%:** システム改善、成長施策、計測・品質・セキュリティ強化、新規事業への再投資
- **約50%:** 創業者の生活費その他の個人側配分

「安定して発生する段階」の判断には、単月の一時的な成果ではなく、一定期間の継続性、将来費用、税務・法務上の負担、資金余力、事業リスクを考慮する。この50%／50%は初期的な資本配分指針であり、固定契約ではない。会社と創業者の状況に応じて、創業者が比率または配分先を変更できる。重要な変更はDecision Logと変更履歴へ理由を記録する。

## 5. 現在の技術構成

### 5.1 実行基盤

- **Cloudflare Worker:** `cloudflare-webhook`
- **本番URL:** `https://cloudflare-webhook.tyansaku3325.workers.dev`
- **エントリーポイント:** `src/index.ts`
- **公開ベースURL:** `env.SITE_URL`（`wrangler.toml` の `[vars]` で管理）
- **D1 binding:** `env.DB`
- **D1 database:** `zero-capital-insight-db`
- **D1 database ID:** `99ef2162-afd8-459a-87eb-d197127528e2`
- **D1 schema管理:** Git管理された `migrations/*.sql` をSingle Source of Truthとし、運用・復旧手順は `docs/D1_OPERATIONS.md` で管理
- **Cron:** `0 23 * * *`（UTC。日本時間では毎日08:00）
- **Git:** `main` を `origin/main` と同期して運用

### 5.2 コンテンツ生成パイプライン

現在のコードは、概ね次の順序で記事を生成する。

1. Geminiで一次ドラフトを生成
2. Claudeで内容を推敲
3. OpenAIで定型構成に最終編集
4. D1の `curation_logs` に保存
5. Discordへ通知

外部API通信は明示timeout、bounded retry、`Retry-After`、response validationを共通方針とする。Geminiは45秒、ClaudeとOpenAIは60秒、Discordは10秒でtimeoutとし、LLMは最大2 attempts、Discordは最大3 attemptsに制限する。network error、timeout、408、429、5xxだけをretryし、client error、JSON parse失敗、response validation失敗はretryしない。

D1保存失敗は呼び出し元へ伝播し、保存に成功しない限りDiscordへ進まない。Cron pipelineの最終失敗はscheduled handlerへrejectとして伝播する。エラーはstage、provider、code、HTTP status、retryable、attemptだけを安全に記録し、Secret、Webhook URL、認証header、prompt、記事本文、外部response本文をログや外向けレスポンスへ含めない。

Step 2では、D1の `pipeline_runs` と一意なidempotency keyを用いて、Cronと手動実行を別namespaceで管理する。Cronは `scheduledTime`、手動実行は検証済み `Idempotency-Key` を基準とし、run取得をD1のUNIQUE制約で原子的に競合解決する。状態は `running`、`saved`、`completed`、`failed` とstageで追跡し、記事保存後のDiscord通知状態も別管理する。完了済みrunの同一Key再送は既存結果を返し、新しいLLM実行、記事保存、通知を開始しない。

pipeline全体の実行上限は8分とし、各外部通信には「stage固有timeout」と「pipeline全体の残り時間」の短い方を適用する。retry開始前にも残り時間を検査し、deadlineを越えるfetch、待機、retryを開始しない。AbortControllerで実通信とresponse本文読み取りを中断対象にし、Promise.raceだけに依存しない。

実行回数はD1への条件付きINSERTで原子的かつfail closedに制限する。手動実行は同時active 1件、直近1時間1件、UTC日次2件、CronはUTC日次1件、全trigger合計はUTC日次3件までとする。同一idempotency keyの既存runは従来どおり再利用し、UNIQUE制約も二重防御として維持する。予算確認または条件付きINSERTに失敗した場合、手動経路は503、Cronは失敗をscheduled handlerへ伝播し、LLM、記事保存、Discordへ進まない。

deadline超過が記事保存前ならrunを `failed` / `pipeline_deadline_exceeded` とし、Discordを送らない。記事保存後・Discord開始前なら記事を保持して `saved` / `discord` / `pending` とする。Discordのtimeoutまたはnetwork errorは配信結果が不明なため自動retryせず、`saved` / `discord` / `sending` のまま人間による照合対象とする。Discordの429・5xxだけは全体deadline内で最大3 attempts、LLMは最大2 attemptsとする。

Discordは外部Webhookであるため厳密なexactly-onceを保証しない。`notification_status=sending` のまま結果不明となった場合は自動再送せず、人間による照合・復旧判断の対象とする。

モデル名や外部API仕様は変更され得るため、稼働確認時には現在の公式仕様と実際の応答を再確認する。

### 5.3 Web・SEO機能

- `/`：記事一覧、5件単位のページネーション、アフィリエイト導線
- `/article/:id`：個別記事、存在しない記事の404
- `/sitemap.xml`：D1から個別記事URLを生成
- `/robots.txt`：クロール許可とsitemap指定
- トップページSEOメタ情報
- 個別記事のtitle、description、canonical、OGP、Twitter Card
- Article JSON-LD
- Google Search Console確認タグ
- トップページから個別記事への通常の内部リンク

### 5.4 運用・テスト用エンドポイント

運用・テスト用エンドポイントは、Cloudflare Workers Secret `OPERATIONS_API_TOKEN` を使用するBearer認証とHTTPメソッド制約で保護する。Secret値はコード、設定、Blueprint、Git履歴へ保存しない。

- `/test-multillm`：POSTかつBearer認証必須
- `/view-logs`：GETかつBearer認証必須
- `/test-discord`：POSTかつBearer認証必須
- `/test`：POSTかつBearer認証必須
- `/get-task`：本番無効化、常に404

認証失敗は401、HTTPメソッド不正は405、Secret未設定時は保護経路のみ503とする。認証はHTTP `fetch` ルート層に限定し、scheduled handlerとCronから直接利用する共通処理には適用しない。公開SEOページは認証なしで公開を維持する。

## 6. 履歴状態台帳（2026-08-10時点の証跡）

この節は当時の確認記録である。現行状態は「3.6 2026-08-20時点の正規状態」を使用する。

### 6.1 本番確認済み

- Worker `cloudflare-webhook` の本番稼働
- D1 `zero-capital-insight-db` のbinding
- Cron設定
- トップページ HTTP 200
- 個別記事 `/article/25` HTTP 200
- sitemap HTTP 200およびXML構文
- robots HTTP 200およびsitemap指定
- Google Search Console所有権確認タグ
- sitemap内の個別記事URL
- 個別記事SEOメタ情報とArticle JSON-LD
- トップページSEOメタ情報
- トップページから個別記事への内部リンク
- 内部リンクに不要な `nofollow` がないこと
- pagination/canonical整合性
  - 本番記事数9件、総2ページ
  - `/` HTTP 200、canonical `/`、`prev` なし、`next` `/?page=2`
  - `/?page=2` HTTP 200、canonical `/?page=2`、`prev` `/`、最終ページのため `next` なし
  - 範囲外の `/?page=3` HTTP 404
  - 2ページ目のtitle、description、OGP、Twitter情報へページ番号を反映
- pagination/canonical反映後も、Search Consoleタグ、内部リンク、Amazonリンク、個別記事、sitemap、robots、D1 binding、Cron設定が維持されたこと
- ベースURLの一元化
  - `SITE_URL` を `wrangler.toml` の `[vars]` で一元管理
  - 現在の `SITE_URL` は `https://cloudflare-webhook.tyansaku3325.workers.dev`
  - トップページのcanonical、prev/next、`og:url` を `SITE_URL` 基準へ統一
  - 個別記事のcanonical、`og:url`、Article JSON-LDのURLを `SITE_URL` 基準へ統一
  - sitemapのトップ・個別記事URLとrobotsのSitemap URLを `SITE_URL` 基準へ統一
  - `request.url.origin` を公開SEO URL生成元として使用しない構成へ変更
  - `/` HTTP 200、`/?page=2` HTTP 200、`/?page=3` HTTP 404
  - `/article/25`、`/sitemap.xml`、`/robots.txt` HTTP 200
  - 本番記事数9件、総2ページ、sitemap XML構文とrobots Content-Typeが正常
  - SITE_URL、D1 binding、Cron、Search Consoleタグ、内部リンク、Amazonリンクが維持されたこと
- 運用・テスト用エンドポイントの保護
  - Secret binding名は `OPERATIONS_API_TOKEN`。Secret値はコード、設定、Blueprint、Gitへ保存しない
  - `/test-multillm`、`/test-discord`、`/test` をPOSTかつBearer認証必須へ変更
  - `/view-logs` をGETかつBearer認証必須へ変更
  - `/get-task` を本番無効化し、HTTPメソッドや認証の有無にかかわらず404へ変更
  - 認証失敗は401、HTTPメソッド不正は405、Secret未設定は保護経路のみ503
  - 公開SEOページは認証なしで公開を維持し、CronはHTTP認証を通らず従来の共通処理を維持
  - Secret変更Version IDは `bfa842ca-b349-4a51-9741-065733486d66`
  - 本番Worker Version IDは `fca3b504-a671-4a13-acc9-7a3b6349824d`
  - `/` HTTP 200、`/?page=2` HTTP 200、`/?page=3` HTTP 404
  - `/article/25`、`/sitemap.xml`、`/robots.txt` HTTP 200
  - `/test-multillm`、`/test-discord`、`/test` はGET 405・未認証POST 401
  - `/view-logs` はPOST 405・未認証GET 401、`/get-task` は404
  - Search Consoleタグ、SITE_URL、canonical、OGP、Article JSON-LD、内部リンク、Amazonリンク、D1 binding、Cron設定が維持されたこと
  - 本番では正しいBearer tokenによる副作用成功テストを実行していない
  - Cronはローカルモック回帰テスト成功と本番設定維持を確認。認証導入後の自然な本番Cron実行は未確認
- D1 schema・migration・復旧基盤
  - `migrations/0001_baseline.sql` を本番へ適用し、`d1_migrations` のID 1として記録済み
  - 7業務テーブル、37列、4明示INDEX、2 UNIQUE autoindex、2 FOREIGN KEYを正式baselineとしてGit管理
  - 業務schema fingerprintは適用前後とも `63f49486d5c565925d13e4efdda5a7f8aa3b7ac9a0796f82e7ffa06742fd0298` で完全一致
  - baseline適用前後で業務schemaと業務データは不変。`curation_logs` は9件、ID 17〜25、日時範囲も不変で、他6業務テーブルの件数も不変
  - 適用直前のTime Travel bookmarkとschema＋data SQL exportを取得し、exportはGit管理外へ安全に保存
  - `docs/D1_OPERATIONS.md` を正式運用文書とし、forward-only migration、backup、復旧、承認・停止手順を定義
  - 適用済みmigrationは編集せず、新しいforward migrationで変更する。Worker rollbackとD1 restoreは別操作として扱う
  - restore、import、DROP、DELETEその他の破壊的操作は通常運用では行わず、創業者の個別承認を必須とする
- Cloudflare Workers Buildsの自動production deployを停止
  - GitHub `main` へのpushで自動production deployされる原因を、対象WorkerのGit repository連携と特定
  - `cloudflare-webhook` だけのGit repository接続を切断。GitHub repositoryとCloudflare GitHub App全体は維持
  - Git保存と本番デプロイを分離し、創業者承認後の手動Wranglerデプロイを正式方式とする
  - Workers Buildsを勝手に再接続しない
  - 切断後の実Git pushで新Versionが作成されず、Version 98が維持されたことを確認
- 保存失敗・外部API失敗対応 Step 1「通信・失敗処理安全化」
  - Gemini、Claude、OpenAI、Discordへ明示timeoutとbounded retryを導入
  - `Retry-After`の秒・HTTP-date形式、最大30秒、短いbackoff＋jitterに対応
  - LLMの不正JSON、必要構造欠損、空本文をnon-retryableな失敗とし、`No response`の記事保存を禁止
  - sanitized errorに統一し、Secret、Authorization、Webhook URL、prompt、記事本文、外部response本文の露出を防止
  - D1 binding不足・INSERT失敗を伝播し、D1保存失敗後はDiscordを呼ばない
  - Cron pipelineの失敗を最終的にthrowし、Cloudflare側へrejectを伝播できる構成へ変更
  - Discordの2xxだけを成功とし、`/test`、`/test-multillm`等の失敗レスポンスを汎用化
  - Node標準機能とmockだけを使うローカルテスト44件が成功。本物のLLM、Discord、本番D1は使用していない
  - Worker Version 99、Version ID `594cbfd3-e0c6-42a2-bd1f-86f343dac3e4`、Deployment ID `8b15a21c-eaf3-4a0e-a66f-f1df700d89c7` で手動Wranglerデプロイ成功
  - 公開6経路、SEO、管理経路の401・405・404、D1 binding、SITE_URL、Secret bindings、Cronを本番確認
  - Workers Builds切断を維持し、Step 1コードpushで追加Worker Versionが作成されないことを確認
- 保存失敗・外部API失敗・重複実行対応 Step 2「D1 idempotency・pipeline state」
  - `0002_pipeline_reliability.sql` を本番D1へ適用し、`d1_migrations` のID 2として記録済み
  - `pipeline_runs` を追加し、`curation_logs.pipeline_run_id` をnullable列として追加。既存9記事はNULLを維持した
  - `pipeline_run_id` は既存データとの互換性と段階導入を優先し、D1のテーブル再構築を避けるためFKを意図的に追加していない。一意部分INDEXで1 runと1記事の対応を保護する
  - 本番schemaは8業務テーブル、60列、INDEX・UNIQUE 12、FK 2。fingerprintは `a23ab033719d0dd1fe2ef6a0fc442954fe88bc15738534a22653a453d7f9f8d0`
  - manual `Idempotency-Key` とCron `scheduledTime` keyを別namespaceで管理し、UNIQUE制約によるatomic run acquisitionを実装
  - `running`、`saved`、`completed`、`failed`、stage、lease、Discord通知状態を永続管理。stale runは自動で再開せずreconciliation対象とする
  - Step 1のtimeout、bounded retry、sanitized errorを維持し、Step 1 44件・Step 2 28件、合計72件のローカルテストに成功
  - Step 2 WorkerをVersion 100として本番反映し、その後の`OPERATIONS_API_TOKEN`安全ローテーションに伴う現行Version IDは `9e0e5d18-033c-4820-be12-f6f19ccf469c`、Deployment IDは `20cef0df-93c5-4704-bf65-122e5080ab4c`、100% traffic
  - 本番正常系試験でGemini、Claude、OpenAI、D1保存、Discord通知を順に完走。pipelineRunId 1、articleId 26、status `completed`、stage `done`、notification_status `sent`、notification_attempt_count 1を確認
  - 同一Idempotency-Key再送でpipeline_runs 1→1、curation_logs 10→10、紐付け済み記事1→1、notification_attempt_count 1→1を確認。既存run 1・article 26を返し、状態・全時刻・attempt数は不変だった
  - 外部サービス側の通信履歴を直接観測したものではないが、完了済みrunのコード経路とD1の完全不変性から、新規LLM実行・記事・Discord再通知につながる状態変化がないことを確認
  - Step 2本番試験前のTime Travel bookmarkとschema＋data SQL exportをGit管理外に保持。Secret、記事本文、Idempotency-Key全文はBlueprintへ記録しない
  - 工程中にCloudflare D1 APIの7403が断続的に発生し、同一OAuth・Account・Database IDのまま正常化した。OAuth refresh境界との関連が有力だが未断定
  - 7403対策としてWranglerコマンドを並列実行せず、deploy・migration前にD1 readを確認し、7403発生時は書き込みを停止して正常化確認後に改めて承認工程へ戻る
  - `OPERATIONS_API_TOKEN` は本番試験前に安全ローテーション済み。値はコード、Git、文書へ保存しない
  - Workers BuildsのGit repository未接続を維持し、Step 2実装pushでも新しいWorker Versionが作成されないことを確認
- pipeline全体deadline・費用上限
  - pipeline全体を8分に制限し、各通信でstage timeoutとglobal remainingの短い方を使用。retry前にも残り時間を検査し、deadline後のfetch・待機・retryを禁止
  - AbortControllerで実通信を停止し、記事保存前のdeadline超過は `failed` / `pipeline_deadline_exceeded`、Discord非送信とする
  - 記事保存後・Discord開始前のdeadline超過は記事を保持して `saved` / `discord` / `pending`、Discordのtimeout・network errorは結果不明として `saved` / `discord` / `sending` を維持し自動再送しない
  - 手動実行はactive 1件、rolling hour 1件、UTC日次2件、CronはUTC日次1件、全trigger合計はUTC日次3件を上限とする
  - 同一Cron `scheduledTime` と同一manual keyは既存runを返す。異なるkeyの競合はD1の原子的な条件付きINSERTで制限し、既存UNIQUE制約も維持
  - 予算照会・条件付きINSERT失敗はfail closedとし、手動経路は503、Cronはscheduled handlerへ失敗を伝播
  - LLMは最大2 attempts、Discordは429・5xxのみ最大3 attempts。deadlineを越えるretryは開始しない
  - schema変更はなく、`0001_baseline.sql` と `0002_pipeline_reliability.sql` のみを維持。`0003`は作成していない
  - Step 1 44件、Step 2 40件のローカルテスト、構文、差分、Wrangler dry-runに成功
  - Worker Version 102、Version ID `84292c8f-b470-46a3-a2a9-b57322166dd5`、Deployment ID `58030c4e-5235-4255-8bb2-c50714a5df5d`、100% trafficで手動Wrangler本番反映・回帰確認に成功
  - 本番D1はmigration `0001`・`0002`、8業務テーブル、60列、INDEX・UNIQUE 12、FK 2、fingerprint `a23ab033719d0dd1fe2ef6a0fc442954fe88bc15738534a22653a453d7f9f8d0` を維持
  - 本番実測は `pipeline_runs` 2件、`curation_logs` 11件、紐付け済み記事2件。run 1はmanual・article 26、run 2は自然Cron・article 27で、いずれも `completed` / `done` / `sent`
  - run 2は2026-08-09 23:00:13 UTCの自然Cronから起動し、Gemini→Claude→OpenAI→D1→Discordを約72秒で完走。8分deadlineと日次上限内であることを確認
  - 本番反映前の復旧基準はTime Travel bookmark `000000ae-00000000-000050c3-15e794944ca3c56ca998d1a9267272d2` とGit管理外export `/Users/hashimotoyuma/D1_BACKUPS/zero-capital-insight-db_20260810-041208_pre-deadline-budget-deploy.sql`。サイズ56,310 bytes、SHA-256 `b54157fc2461b81826ae7562bb40b72b99d839d9fcd2ac6617fe27b77a7fc797`
  - Workers Builds切断を維持し、Git pushと本番デプロイを分離。Cloudflare D1 API 7403発生時は書き込み・deployへ進まず停止する安全方針も維持

最新の本番確認時Worker Version IDは `2677311e-07e7-43ec-bac4-be763effc418`（Traffic 100%）である。過去のVersion IDとDeployment IDは変更履歴上の確認値として維持する。

### 6.2 Gitで確定済み

- `main` → `origin/main` へpush済み
- pagination/canonical基準コミット: `8298277c10db036f5e579175e0b26502be2b7cff`
- ベースURL一元化基準コミット: `01192e5d12e76e1fae4749c2e786c961054cb999`
- 運用エンドポイント保護基準コミット: `d9ffd1e9e516594c6bc569031a4b797e48ca3471`
- 運用エンドポイント保護コードのコミットメッセージ: `Protect operations endpoints`
- D1 baseline・復旧基盤コミット: `e09780a`（`Add D1 baseline migration and recovery guide`）
- 通信・失敗処理安全化 Step 1コミット: `20799ab`（`Harden pipeline failure handling`）
- D1 idempotency・pipeline state Step 2コミット: `098e820`（`Add pipeline idempotency and reliability state`）
- pipeline全体deadline・費用上限コミット: `ab756f7`（`Add pipeline deadline and execution limits`）
- 上記時点で `main` と `origin/main` は 0 ahead / 0 behind

### 6.3 reconciliation実装済み・本番反映済み・安定確認済み

- stale runとDiscord結果不明通知を分類する認証済み`/pipeline-reconciliation` GET/POSTを実装
- GETは記事本文・Idempotency-Keyを返さず、状態変更もしない
- stale runは同一Keyの再呼び出しでも自動失敗化・自動再開せず、`reconciliation_required`で停止
- `sending`は自動再送せず、送達済み・確実に未送信を人間が確認できた場合だけ比較更新を許可
- `0003_pipeline_reconciliation_audit.sql`を本番D1へ適用し、監査イベントテーブルを追加。既存run・記事は変更していない
- 状態変更は固有`Reconciliation-Key`、根拠メモ、期待状態の一致を必須とし、競合は409で停止
- Step 1 44件、Step 2 40件、Step 3 reconciliationローカル統合テストに成功。Worker Version ID `2677311e-07e7-43ec-bac4-be763effc418`をTraffic 100%で本番稼働し、安定確認済み

### 6.4 意図的に保持している未追跡ファイル

- `src/index.ts.before-home-seo-2026-08-09`
- `src/index.ts.before-internal-links`
- `src/index.ts.before-sitemap-2026-08-09`

これらはバックアップであり、明示的な判断なしに編集、削除、ステージ、commit、pushしない。

### 6.5 未実装または未完成

- pipeline状態の安全な可観測性とCron自然実行の運用確認
- Markdownから安全なセマンティックHTMLへの変換
- OGP画像、author、publisher、image等の構造化データ強化
- 記事・流入・クリック・成約・売上を結ぶ計測
- KPIダッシュボード
- 実験、比較、ロールバックを備えた自動改善
- 複数事業への自動横展開
- 経営レベルのマルチエージェント協調

## 7. 目標アーキテクチャ

### 7.1 レイヤー構造

1. **方針・統制レイヤー**  
   会社目標、予算、禁止事項、承認条件、リスク許容度を管理する。

2. **事業オーケストレーションレイヤー**  
   事業ごとの目標をタスクへ分解し、担当エージェントへ割り当て、状態と成果を追跡する。

3. **専門エージェントレイヤー**  
   調査、コンテンツ、SEO、収益化、分析、技術、品質・セキュリティを担当する。

4. **実行基盤レイヤー**  
   Cloudflare Workers、D1、Cron、外部LLM、通知、将来の分析・決済・配信基盤を含む。

5. **データ・学習レイヤー**  
   コンテンツ、施策、費用、流入、行動、CV、売上、実験結果、失敗履歴を共通形式で保持する。

6. **監査・観測レイヤー**  
   ログ、アラート、KPI、変更履歴、承認履歴、障害復旧情報を管理する。

### 7.2 データループ

すべての施策は、可能な限り次の識別子で追跡可能にする。

- 事業ID
- コンテンツ／商品ID
- 施策ID
- 実験IDとvariant
- 使用モデル・プロンプト版
- 発生費用
- 公開日時
- 流入元
- クリック・CV・売上
- 判定したエージェントと根拠

これにより「何をした結果、どの数字がどう変わったか」を再現できるようにする。

## 8. マルチエージェント組織設計

### 8.1 現在の役割

- **ユーザー／創業者:** 最終意思決定、重要承認、事業目的の決定
- **Work/Codex:** リポジトリ調査、設計支援、実装、テスト、Git、検証
- **生成LLM群:** 記事のドラフト、レビュー、最終編集
- **Cloudflare基盤:** 定期実行、配信、データ保存

現在は人間と開発AIによる半自動運営であり、「自律的なマルチエージェント経営」は未完成である。

### 8.2 将来の専門エージェント

- **経営・計画:** KPI、予算、優先順位、停止判断
- **市場調査:** 市場、顧客課題、競合、需要、商機の探索
- **コンテンツ:** 企画、生成、編集、更新、品質管理
- **SEO・集客:** キーワード、内部構造、インデックス、流入改善
- **収益化:** オファー、導線、CV、単価、LTV、提携先の最適化
- **分析:** KPI集計、因果仮説、実験評価、異常検知
- **技術:** 実装、テスト、デプロイ、信頼性、コスト最適化
- **品質・セキュリティ:** 認証、権限、法令・規約、ブランド、安全性の監査

### 8.3 自律性の段階

- **Level 0:** 人間がすべて手動実行
- **Level 1:** AIが提案し、人間が実行
- **Level 2:** AIが安全な作業を実行し、重要操作のみ人間が承認
- **Level 3:** AIが定められた予算・方針内で施策を運用し、人間が監督
- **Level 4:** 複数事業を継続運営し、例外と戦略変更だけを人間へ上げる

現在は領域によりLevel 1〜2。Level 3以降へ進む条件は、計測、予算上限、認証、監査ログ、停止機構、ロールバックの完成である。

## 9. KPI設計

### 9.1 北極星指標

長期の北極星指標は、**自律運営される事業群の月次純利益と、その再現可能な成長率**とする。

短期はデータ量が少ないため、単一指標だけで最適化しない。

### 9.2 第1号事業の主要KPI

**供給・品質**

- 公開記事数と更新成功率
- 生成失敗率、保存失敗率、通知失敗率
- 記事の鮮度、独自性、事実確認、読了指標

**検索・集客**

- 有効インデックス数
- 検索表示回数、クリック数、CTR、平均掲載順位
- オーガニックセッション、記事別ランディング数

**収益**

- アフィリエイトクリック数・CTR
- CV数、CVR、売上、報酬、記事別収益
- API・運用費用
- 粗利益、純利益、投資回収期間

**改善能力**

- 実験数、勝率、改善幅
- 改善案から反映までの時間
- ロールバック率、障害件数

### 9.3 KPI運用ルール

- 数字の定義、期間、データ元を固定する
- 観測できないKPIを推測で報告しない
- vanity metricsより収益・継続性・品質を優先する
- 改善案は仮説、対象指標、期間、停止条件を持つ
- 少数データで自動的に大きな変更を行わない

## 10. セキュリティ・品質・ガバナンス

### 10.1 最優先リスク

- 運用Secretの安全な保管、ローテーション、最小権限
- 認証済み運用経路のレート制限、費用上限、重複実行防止
- 認証情報漏えい時の `/view-logs` 等からの情報露出
- D1 migration・backup・復旧手順の継続的な検証
- 外部API失敗時の不整合
- シークレット、費用、モデル仕様、外部規約への依存

### 10.2 必須制御

- 認証・認可と最小権限
- 状態変更処理のPOST限定
- レート制限、費用上限、重複実行防止
- 入力検証、出力エスケープ、安全なMarkdown変換
- セキュリティヘッダーとキャッシュ方針
- D1マイグレーション、バックアップ、復旧テスト
- 外部APIタイムアウト、再試行、冪等性、失敗通知
- 監査ログ、変更履歴、ロールバック手順
- Amazon、検索エンジン、LLM提供者等の規約順守

## 11. 開発・リリース標準

原則として、各変更は次の工程を通す。

> 調査 → 設計 → 実装 → 自動チェック → 差分確認 → dry-run → 人間承認 → 本番デプロイ → 本番検証 → Git保存 → 設計図・状態台帳更新

### 11.1 着手前

- 正しいプロジェクト、ブランチ、HEAD、origin同期状態を確認する
- 既存の変更と未追跡ファイルを確認する
- 変更対象、非対象、成功条件、停止条件を定める

### 11.2 実装中

- 目的外のコード・設定・D1データを変更しない
- 小さくレビュー可能な差分にする
- 既存の正常機能とセキュリティを後退させない
- バックアップファイルを勝手に追加・削除しない

### 11.3 リリース

- ルートの `./wrangler.toml` を明示する
- `.wrangler_deploy_safe` は使用しない
- dry-run成功後にのみ本番デプロイする
- 本番の読み取り確認を行い、D1書き込みを伴うテストを不用意に呼ばない
- 本番検証後に意図したファイルだけをcommit・pushする
- Git pushは本番デプロイではない。Workers BuildsのGit連携は切断状態を維持し、創業者承認後にWranglerで手動デプロイする
- force pushやGit履歴書き換えを行わない

## 12. ロードマップ

### Phase 0: 会社基準の確立（現在）

- Master Blueprint v1.0を制定
- 状態台帳、意思決定、変更履歴の更新方法を定着
- 未コミットのpagination/canonical変更をレビューして正式工程へ戻す

**完了条件:** 今後の作業が本設計図と状態台帳を基準に進む。

### Phase 1: 第1号メディアの安全な公開基盤

1. **完了:** pagination/canonical整合性を本番反映・検証・Git保存
2. **完了:** ベースURLを一元化
3. **完了:** 運用エンドポイントを認証し、状態変更をPOST限定
4. **完了:** D1スキーマ、migration、backup、復旧手順を追加
5. **完了:** 保存失敗、外部API失敗、重複実行への対応
   - **完了:** Step 1 通信・失敗処理安全化
   - **完了:** Step 2 D1 idempotency、pipeline state、重複実行防止、Discord通知状態管理
   - **完了:** pipeline全体8分deadline、手動・Cron・全体の実行回数上限、deadline時の安全な状態遷移
   - **本番反映済み・安定確認済み:** stale run・`sending`の人間照合、監査記録、比較更新による復旧
6. 最低限の自動テスト、型、デプロイ手順を整備

**完了条件:** 公開、生成、保存、通知を安全かつ再現可能に運用できる。

### Phase 2: コンテンツ品質と検索成長

1. Markdownを安全なセマンティックHTMLへ変換
2. 記事の一次情報・出典・更新・品質基準を設計
3. OGP画像と構造化データを強化
4. sitemapの日付検証、必要時の分割、キャッシュを整備
5. Search Consoleデータを定期取得・分析
6. キーワード、内部リンク、既存記事更新をデータ駆動化

**完了条件:** 検索流入と品質を記事単位で測定し、改善できる。

### Phase 3: 計測可能な収益化

1. アフィリエイトクリックを記事・配置・施策単位で計測
2. 成約・報酬データを可能な範囲で統合
3. 流入→閲覧→クリック→CV→収益のファネルを構築
4. 導線、オファー、テーマ、配置の実験基盤を整備
5. 費用と純利益を含むダッシュボードを作る

**完了条件:** 収益の発生源と改善余地を説明でき、第1号事業で実利益を確認できる。

### Phase 4: 分析と安全な自動改善

1. 分析エージェントがKPIと異常を評価
2. 改善案を仮説・期待値・リスク付きで生成
3. 低リスク施策を小規模実験として実行
4. 結果に基づき採用、棄却、ロールバック
5. 予算・変更範囲・停止条件を自動執行

**完了条件:** 人間が毎回指示しなくても、小さな改善ループが安全に回る。

### Phase 5: 事業横展開

1. 第1号事業の再利用可能部品をテンプレート化
2. 市場調査エージェントが新規候補を評価
3. 小規模な検証事業を低コストで立ち上げ
4. 継続、修正、撤退をKPIで判断
5. 利益を有望事業へ再配分

**完了条件:** 第2・第3の事業を、既存基盤を使って再現可能に立ち上げられる。

### Phase 6: マルチエージェント自律経営

1. 共通の目標・予算・データ・監査基盤を整備
2. 専門エージェント間の提案、レビュー、承認を標準化
3. 事業ポートフォリオの資源配分を支援
4. 例外、重大リスク、戦略変更のみ人間へエスカレーション

**完了条件:** 複数事業の運営・改善・小規模拡張が、定められた統制内で継続する。

## 13. 次の実行順序

reconciliation本番反映・安定確認完了後の優先作業は次のとおり。

1. Secretや記事本文を露出しないpipeline observabilityを拡張し、自然な本番Cron実行を継続監視する
2. 最低限の自動テスト実行方法、型チェック、デプロイ手順を標準化する
3. v1.9 SEO強化フェーズとして、記事の正規コンテンツ構造を整備する

## 14. 意思決定ルール

優先順位は原則として次の順で判断する。

1. 重大なセキュリティ、データ損失、課金暴走、法令・規約リスク
2. 本番の信頼性と復旧可能性
3. 計測可能性
4. ユーザー価値、集客、収益への寄与
5. 自動化と横展開への再利用性
6. 見た目や局所的な最適化

新しい機能は「作れるか」ではなく、次の問いで評価する。

- 最終ビジョンへ近づくか
- 誰にどんな価値を提供するか
- 成功をどの数字で判定するか
- 費用と最悪損失はいくらか
- 失敗時に停止・復元できるか
- 他事業へ再利用できるか

## 15. Decision Log／意思決定・凍結事項

Decision Logは、採用した方針だけでなく、重要な「採用しなかった案」「凍結した案」「方向転換」について、判断理由と再検討条件を残すための公式記録である。

凍結は永久禁止を意味しない。規約、安全性、収益性、技術環境、会社の資源等が変化し、再検討する合理的理由が生じた場合に限り、創業者の判断で再評価できる。凍結事項を再開する場合は、以前の判断理由がどのように解消されたか、新しいリスクと成功条件は何かを記録する。

### DL-001 — ローカルスマートフォン実機による自動巡回等の凍結

**状態:** 凍結  
**決定日:** 2026-08-09  
**対象:** ローカルスマートフォン実機を利用した自動巡回、スワイプその他のプラットフォーム操作自動化

**決定:**  
プラットフォーム側のアカウント停止・BANリスク、規約適合性、収益構造、保守負担および運用リスクを考慮し、現時点では実装・運用を凍結する。

**現在の優先方針:**  
Cloudflare等のクラウド基盤による自動メディア運営と、検索エンジンからの継続的なSEO流入の構築を優先する。

**再検討条件:**  
プラットフォーム規約、安全性、BANリスク、収益性、技術環境または公式に許可された連携手段に重要な変化があり、再検討する合理的理由が生じた場合のみ、創業者の判断で再評価する。

### DL-002 — Git pushと本番Workerデプロイの分離

**状態:** 採用
**決定日:** 2026-08-10
**対象:** `cloudflare-webhook` のCloudflare Workers Buildsと本番リリース方式

**決定:**
対象WorkerのGit repository接続を切断し、Git保存と本番デプロイを分離する。本番反映はdry-run、創業者承認、手動Wranglerデプロイ、本番検証の順で行う。

**理由:**
Workers BuildsがGitHub `main` へのpushを契機に、Blueprintだけの変更を含めて承認外のproduction Versionを作成し、正式なリリース標準と衝突したため。

**再検討条件:**
自動デプロイにも同等以上の承認ゲート、差分検証、環境分離、監査性を実装でき、創業者が明示承認した場合のみ再検討する。

### DL-003 — 初回remote migrations listを完全な読み取り専用とみなさない

**状態:** 採用
**決定日:** 2026-08-10
**対象:** Wranglerによる本番D1 migration管理の初回導入

**決定:**
Wrangler 4.120.0では、migration管理テーブルがない本番D1への最初の`migrations list --remote`が`d1_migrations`を暗黙に作成した。このため、初回または管理状態不明時のremote migrationコマンドは副作用を持ち得る操作として扱う。

**運用条件:**
事前にschema確認、Time Travel bookmark、Git管理外のschema＋data export、副作用範囲の確認、創業者承認を完了する。今回の`d1_migrations`は`id`、`name`、`applied_at`の3列で、適用前0件を確認後、承認済み`0001_baseline.sql`を正式適用した。

### Decision Log運用ルール

- 各記録に一意のID、日付、状態、対象、決定、理由、再検討条件を付ける
- 採用しなかった重要案、凍結案、方向転換を記録する
- 過去の記録を理由なく削除または書き換えない
- 判断が変わった場合は元の記録を残し、新しい記録から参照する
- 重要な凍結解除、方針転換、再採用は創業者の承認を必要とする

## 16. Master Blueprintの永続管理

### 16.1 Single Source of Truth

本設計図を会社の目的、原則、現在地、ロードマップ、重要な意思決定に関するSingle Source of Truthとして長期管理する。日常の実装詳細はコードや運用文書で管理できるが、それらが本設計図の重要方針と矛盾する場合は、矛盾を解消するまで重要な変更を進めない。

### 16.2 バージョン管理

- `v1.0`、`v1.1`、`v1.2`、`v2.0`等の明示的なバージョン履歴を維持する
- 誤字修正等を除く重要変更では、変更内容、理由、承認、日付を変更履歴へ残す
- 過去の意思決定、凍結事項、方針を理由なく削除しない
- 方針を撤回・置換する場合も旧記録を残し、新しい判断から参照できるようにする
- 将来的に正式な保存場所を定め、Git等により差分、作成者、日時、変更履歴を追跡できる状態にする
- 正式保存場所を変更する場合は、最新版、履歴、Decision Logを欠損させずに移行する

### 16.3 変更権限と創業者承認

Blueprintの文章改善や事実状態の更新であっても、最終ビジョン、資本配分、事業優先順位、リスク許容度、エージェント権限、凍結事項その他の重要な会社方針を変更する場合は、創業者の明示承認を必要とする。

AIまたは自動化システムは変更案、根拠、影響、代替案を提示できるが、重要方針を単独で正式変更してはならない。承認前の変更は「提案」または「草案」と明記し、正式方針と混同しない。

## 17. 文書運用

### 17.1 更新が必要な時

- 本番デプロイまたはロールバック
- 重要なGitコミット
- 技術構成、D1スキーマ、外部サービスの変更
- KPI、収益モデル、エージェント権限の変更
- フェーズの開始・完了
- 重大障害、セキュリティ問題、重要な学習

### 17.2 更新方法

- 変更理由と根拠を記録する
- 状態台帳の分類を更新する
- 実装済みと構想を再確認する
- ロードマップと「次の実行順序」を最新化する
- バージョンと変更履歴を追記する
- 過去の意思決定を削除せず、変更理由を残す

正式保存場所が確定するまでは、本ファイルを承認対象の原本として扱う。正式保存場所の決定後は、管理対象の原本を一つに定め、複製ファイルによる内容の分岐を防ぐ。

## 18. 変更履歴

### v2.0-A — 2026-08-15（本番canary待機）

- 本番D1のread-only観測値を用いる初回canaryの対象として記事 ID 25 を確認した。固定SELECT、`changed_db=false`、`rows_written=0` の条件は満たしたが、観測は1日、impressions 1、search clicks 0、affiliate click 0、前期間データなしであった
- v2.0-Aのルール層は `insufficient_data` / `observation_below_fixed_minimum` と判定し、`ai_eligible=false` とした。これは正常な安全停止である
- 本番canaryの固定最低条件は観測7日以上かつimpressions 10以上とし、条件を満たすまでTerra/OpenAIを呼び出さない。この安全基準を緩和しない
- recommendationのD1保存、記事変更、自動公開、Amazon導線変更、およびWorker、Cron、pipeline、Discordの変更は実施していない

### v1.9.1-B — 2026-08-14（ID 25 SEO保守backfill）

- v1.9.1の保守工程として記事 ID 25のみを承認済みmanifestに基づき `legacy` から `ready` へ移行した。categoryは `saas-cloud` とし、title、description、body_markdown、published_at、updated_at、seo_statusを承認済み値へ正規化した
- ID、既存`content`、pipeline、reconciliation、通知状態、Worker、Cron、Discord、Amazon導線、migrationは変更していない。`content` SHA-256は不変であり、`body_markdown` SHA-256との一致を確認した
- 条件付きUPDATEの正式監査基準を、`changed_db=true`、`changes=1`、`UPDATE ... RETURNING id`が対象IDを1件返すこと、直後のread-only事後検証に固定した。`rows_written`はINDEX更新を含む参考監査値であり、1行更新判定には使用しない
- 事後検証で、ID 25の承認済みSEO値、content不変、body_markdown/content SHA一致、`PRAGMA foreign_key_check=0`、既存pipeline、Search Console、affiliate状態の不変を確認した

### v1.9.2-A — 2026-08-11

- SEO内部構造強化を本番反映。Worker Version ID `7174dc3e-7851-4352-8d58-2f6079a48e4b` をTraffic 100%で稼働した
- `/category/ai-automation` と `/category/saas-cloud` の公開、カテゴリページのcanonicalとBreadcrumbList、記事ページのパンくず・Article JSON-LD・BreadcrumbListを確認した
- `/sitemap.xml` に公開カテゴリURLが追加され、対象カテゴリの掲載を確認した。既存記事URLと一覧抜粋表示を維持している
- 本番D1のSEO状態は `ready=4`、`legacy=8`、`needs_review=0`。`pipeline_runs=3`、最新Cron runのDiscord通知は `sent`、`pipeline_reconciliation_events=0` を確認した
- migration、Worker設定、本文、pipeline、reconciliationの変更は含めない

### v1.9.1-A — 2026-08-10

- SEO記事基盤（`0004_seo_article_foundation.sql`）を利用し、承認済みmanifestに限定して既存legacy記事 ID 17 / 20 / 26 を本番backfillした。3件を `ready` 化し、状態内訳は `ready=3`、`legacy=8`、`needs_review=0` とした
- 更新対象は `title`、`description`、`body_markdown`、`category`、`published_at`、`updated_at`、`seo_status` のみ。`content`、ID、pipeline、reconciliation、通知状態は変更していない
- 全対象で `body_markdown` SHA-256 と既存 `content` SHA-256 の一致を確認。backfill後も `pipeline_runs=2`、`curation_logs=11`、`notification_status=sending=0`、`pipeline_reconciliation_events=0` を維持した
- Worker deploy、migration、pipeline実行、Discord送信は実施していない。個別記事3件のcanonical、OGP、Twitter Card、JSON-LD、およびsitemapの固定`updated_at`由来lastmodを確認した
- 監査証跡はGit管理外の保護領域へ保存済み。Time Travel bookmark: `000000c2-00000000-000050c3-cb00fa8be896d50c58f2497c16a30c35`、pre-backfill export SHA-256: `14c95286c896826064c73d7b0004de8629eca26b65b85782586102fc54913bc6`、dry-run audit SHA-256: `348c53b9dcafdc015e1440c5949a2656eb12f94b55af6fd645c71588c1166454`

### v1.8 — 2026-08-10

- stale runを自動失敗化・自動再開せず、人間照合が必要な状態として返すよう安全側へ変更
- 認証済み`/pipeline-reconciliation`で、記事本文・Idempotency-Keyを露出しない分類一覧を追加
- `sending`は送達結果不明として自動再送禁止を維持し、送達済みまたは確実に未送信の証拠がある場合だけ人間が比較更新できる設計を実装
- 状態修復、送達確認、未送信確認はいずれも固有操作Key、根拠メモ、期待状態一致を必須化し、競合時はfail closed
- 永続監査に既存schemaだけでは不足することを確認し、additiveな`0003_pipeline_reconciliation_audit.sql`を追加。既存run・記事のデータ変更は含めない
- Step 1 44件、Step 2 40件、実SQLiteを用いたStep 3統合テストに成功。`0003_pipeline_reconciliation_audit.sql`を本番適用し、Worker Version ID `2677311e-07e7-43ec-bac4-be763effc418`をTraffic 100%で稼働、安定確認済み

### v1.7 — 2026-08-10

- pipeline全体8分deadlineを導入し、stage timeoutとglobal remainingの短い方をAbortControllerへ適用。deadline後のfetch、待機、retryを禁止
- deadline超過を保存前は `failed` / `pipeline_deadline_exceeded`、保存後は `saved` / `discord` / `pending`、Discord結果不明は `saved` / `discord` / `sending` として安全に保持
- 手動active 1件・rolling hour 1件・UTC日次2件、Cron UTC日次1件、全trigger UTC日次3件の上限をD1条件付きINSERTで原子的・fail closedに適用
- LLM最大2 attempts、Discord 429・5xx最大3 attemptsを維持し、deadlineを越えるretryを開始しない構成を確認
- migration追加なし。`0001`・`0002`、schema fingerprint、8テーブル・60列・INDEX/UNIQUE 12・FK 2を維持
- Step 1 44件・Step 2 40件、構文、差分、dry-runに成功し、Worker Version 102、Version ID `84292c8f-b470-46a3-a2a9-b57322166dd5`、Deployment ID `58030c4e-5235-4255-8bb2-c50714a5df5d`、100% trafficで本番反映
- 本番D1はpipeline_runs 2件、curation_logs 11件、紐付け2件。manual run 1/article 26と自然Cron run 2/article 27がともにcompleted・done・sent
- 自然Cron run 2は2026-08-09 23:00:13 UTCに起動し、全pipelineを約72秒で完走
- Time Travel bookmarkとGit管理外のschema＋data exportを復旧基準として確保し、Workers Builds切断、7403時の停止方針、Git pushと手動deployの分離を維持
- 実装・テストをコミット `ab756f7` としてGit保存し、pushで新しいWorker Versionが作成されないことを確認
- 次の正式作業をstale/sending reconciliation、pipeline observability、自然Cron継続監視、自動テスト・型・デプロイ標準化へ更新

### v1.6 — 2026-08-10

- Step 2「D1 idempotency・pipeline state・重複実行防止・Discord通知状態管理」を本番反映・Git正式保存
- `0002_pipeline_reliability.sql` を本番適用し、`pipeline_runs` とnullableな `curation_logs.pipeline_run_id` を追加。既存9記事はNULLを維持し、FKは互換性とforward-only運用のため意図的に追加しなかった
- 本番schemaを8業務テーブル、60列、INDEX・UNIQUE 12、FK 2、fingerprint `a23ab033719d0dd1fe2ef6a0fc442954fe88bc15738534a22653a453d7f9f8d0` として確定
- manual Idempotency-KeyとCron scheduledTime keyのnamespace分離、atomic run acquisition、run・stage・lease・通知状態管理を導入
- 本番正常系試験でpipelineRunId 1、articleId 26がGemini→Claude→OpenAI→D1→Discord→completedまで正常完走
- 同一Idempotency-Key再送でrun、記事、紐付け、通知attempt、全状態時刻が不変であり、既存run 1・article 26が返ることを確認
- Discordは外部Webhookのため厳密なexactly-onceを保証せず、`sending`で結果不明の場合は自動再送せず人間が照合する方針を維持
- Cloudflare D1 API 7403の断続発生を記録。OAuth refresh境界との関連を有力候補としつつ未断定とし、並列Wrangler禁止・事前D1 read・7403時の書き込み停止を運用標準化
- `OPERATIONS_API_TOKEN` を安全ローテーションし、値をコード、Git、Blueprintへ保存しないことを確認
- Step 2実装をコミット `098e820` としてGit保存。Workers Builds切断を維持し、pushによる自動Worker Version生成がないことを確認
- 現行Worker Version ID `9e0e5d18-033c-4820-be12-f6f19ccf469c`、Deployment ID `20cef0df-93c5-4704-bf65-122e5080ab4c`、100% trafficを確認
- 次の正式作業をpipeline全体deadline、stale/sending復旧運用、pipeline observability、Cron自然実行確認へ更新

### v1.5 — 2026-08-10

- 保存失敗・外部API失敗対応 Step 1「通信・失敗処理安全化」を正式完了
- Gemini 45秒、Claude・OpenAI 60秒、Discord 10秒のtimeoutを導入し、response本文読み取りまでAbortControllerの対象化
- retryableなnetwork、timeout、408、429、5xxだけをbounded retryし、`Retry-After`、backoff、jitterへ対応
- LLMのJSON・必要構造・非空本文validationを追加し、validation失敗をretry・D1保存しない構成へ変更
- sanitized error、汎用HTTPエラー、構造化ログによりSecret・Webhook URL・記事本文等の露出を防止
- D1保存失敗を伝播し、保存失敗後のDiscord送信を禁止。Cron最終失敗をCloudflareへrejectとして伝播
- Discordの2xx成功判定を統一し、`/test`の失敗伝播とレポート生成1回化を実施
- mockのみのローカルテスト44件、構文、差分、Wrangler dry-runに成功
- Step 1をコミット `20799ab` としてGit保存し、手動WranglerデプロイでVersion 99へ反映
- Version ID `594cbfd3-e0c6-42a2-bd1f-86f343dac3e4`、Deployment ID `8b15a21c-eaf3-4a0e-a66f-f1df700d89c7`、100% trafficを確認
- 公開SEO、管理経路、D1 binding、SITE_URL、Secret bindings、Cron、Workers Builds切断の維持を確認
- 正しいBearer token、本物のLLM、本番Discord、本番D1書き込みによる副作用テストは実行していない
- Step 2は未実装とし、次の正式工程をD1 idempotency、pipeline state、重複実行防止、Discord再送管理へ更新

### v1.4 — 2026-08-10

- Git管理された `migrations/0001_baseline.sql` を本番D1へ正式適用し、`d1_migrations` のID 1として記録
- 7業務テーブル、37列、4明示INDEX、2 UNIQUE autoindex、2 FOREIGN KEYをbaseline化し、schema fingerprintの適用前後完全一致を確認
- baseline適用前後で業務schema・業務データが不変であることを確認
- Time Travel bookmarkとGit管理外のschema＋data exportを適用前の復旧基準点として確保
- `docs/D1_OPERATIONS.md` にmigration、backup、restore、forward-fix、創業者承認・停止手順を正式化
- Wrangler 4.120.0の初回`migrations list --remote`が`d1_migrations`を暗黙作成した事実と安全ルールを記録
- GitHub `main` pushによる自動production deployの原因をWorkers BuildsのGit連携と特定し、対象Workerだけの接続を切断
- Git保存と本番デプロイを分離し、承認済みWrangler手動デプロイへ一本化
- Workers Builds切断後の実Git pushで、自動production deployが発生しないことを確認済み
- D1 baseline・復旧基盤をコミット `e09780a` としてGit保存
- Phase 1のD1 schema・migration・backup・復旧工程を完了扱いとし、次の正式作業を保存失敗・外部API失敗・重複実行への対応へ更新

### v1.3 — 2026-08-10

- Cloudflare Workers Secret `OPERATIONS_API_TOKEN` を導入。Secret値はコード、設定、Blueprint、Gitへ保存しない
- `/test-multillm`、`/test-discord`、`/test` にBearer認証とPOST限定を導入
- `/view-logs` をBearer認証必須のGETへ限定し、`/get-task` を本番404として無効化
- Secret変更Version ID `bfa842ca-b349-4a51-9741-065733486d66`、Worker Version ID `fca3b504-a671-4a13-acc9-7a3b6349824d` で本番反映に成功
- 公開SEOページ、保護経路の401・405・404、D1 binding、SITE_URL、Cron設定の維持を本番確認
- 正しいBearer tokenによる副作用成功テストは本番で実行せず、Cronはローカルモック回帰成功と本番設定維持までを確認
- 運用エンドポイント保護変更をコミット `d9ffd1e9e516594c6bc569031a4b797e48ca3471` としてGit保存
- Phase 1の運用エンドポイント保護を完了扱いとし、次の正式作業をD1スキーマ、マイグレーション、復旧手順へ更新

### v1.2 — 2026-08-10

- `wrangler.toml` の `[vars]` に `SITE_URL` を導入し、公開ベースURLを一元管理
- canonical、prev/next、`og:url`、Article JSON-LD、sitemap、robotsの公開URLを `SITE_URL` 基準へ統一
- Worker Version ID `243a91ff-85cb-492c-9f78-1b6e01068186` で本番デプロイと読み取り検証に成功
- `/`、`/?page=2`、範囲外ページ、個別記事、sitemap、robots、および既存機能の維持を本番確認
- ベースURL一元化変更をコミット `01192e5d12e76e1fae4749c2e786c961054cb999` としてGit保存
- Phase 1のベースURL一元化を完了扱いとし、次の正式作業を運用・テスト用エンドポイントの認証とPOST限定へ更新

### v1.1 — 2026-08-09

- pagination/canonical整合性を本番反映し、Worker Version ID `93642267-ebbe-4398-af90-979687f71f0a` で動作確認
- `/` と `/?page=2` のcanonical、prev/next、ページ別SEO情報、および範囲外ページの404を本番確認
- pagination/canonical変更をコミット `8298277c10db036f5e579175e0b26502be2b7cff` としてGit確定
- Phase 1のpagination/canonical工程を完了扱いに更新
- 次の正式作業をベースURLの一元化、その次を運用・テスト用エンドポイントの保護に更新

### v1.0 — 2026-08-09

- 会社の最終ビジョン、基本原則、事業モデルを正式化
- 現在のCloudflare Worker、D1、SEO、Git状態を記録
- 本番確認済み、未反映、未実装を分離
- マルチエージェント組織、KPI、安全方針を定義
- 第1号事業から自動改善・事業横展開までのロードマップを制定
- pagination/canonical変更を未コミット・未デプロイの進行中作業として記録
- 初期収益目標として月間30〜40万円以上の利益を追加
- 安定利益の初期配分原則として約50%再投資／約50%生活費等を追加
- Decision Logを新設し、ローカルスマートフォン実機自動化の凍結を記録
- Blueprintの永続管理、バージョン履歴、Git等による将来の追跡、重要方針変更時の創業者承認を追加

---

## 付記：現在地の解釈

過去の会話では、会社全体の完成度を概算で20〜25%と表現した。これは客観的な測定値ではなく、当時の説明用目安である。本設計図では固定の進捗率を正式KPIにしない。

現在の本質的な評価は次のとおりである。

- **生成 → 保存 → 公開 → 検索エンジンへの発見:** 基本系が稼働
- **安全な運用 → 計測 → 収益評価 → 自動改善:** 未完成
- **事業横展開 → マルチエージェント自律経営:** 構想・初期段階

会社の第1段階が完成したと判断する基準は、第1号事業で「生成、公開、集客、実収益、計測、分析、改善」の閉ループが、安全かつ継続的に回ることである。
