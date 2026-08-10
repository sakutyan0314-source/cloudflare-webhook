# D1 schema・migration・復旧運用手順

## 1. 目的と適用範囲

この文書は、D1のschema変更、migration、backup、復旧を、データ損失や本番停止を避けながら再現可能に運用するための手順書である。

対象は次の本番D1である。

- Database: `zero-capital-insight-db`
- Binding: `env.DB`
- Wrangler config: `./wrangler.toml`

コマンドの危険度を次の3段階で表す。

- **LOCAL**: 一時的なローカルD1だけを変更する。本番には影響しない。
- **REMOTE READ-ONLY**: 本番D1を読み取る。DDL・DMLは含めない。
- **REMOTE DESTRUCTIVE**: 本番のschema・データ・復元状態を変更する。**創業者の明示承認なしに実行禁止。**

コマンド実行前には、必ずプロジェクトルートが`/Users/hashimotoyuma/cloudflare-webhook`であることと、`./wrangler.toml`を使用していることを確認する。

## 2. schemaのSingle Source of Truth

Git管理された`migrations/*.sql`をschema変更履歴のSingle Source of Truthとする。

`migrations/0001_baseline.sql`は、2026-08-10に読み取った既存本番D1の状態を採用したbaselineである。DB作成当時のmigration履歴を再現したものではない。

対象業務テーブルは次の7件である。

- `curation_logs`
- `articles`
- `sources`
- `insights`
- `notifications_log`
- `sent_reports`
- `tasks`

`_cf_KV`、`sqlite_sequence`、`d1_migrations`などのD1・SQLite・Wrangler内部テーブルは、業務migrationで手動作成しない。

適用済みmigrationを編集、改名、削除してはならない。変更が必要な場合は、新しいforward migrationを追加する。

## 3. migration命名規則

ファイル名は4桁の連番と短いsnake_case名を使用する。

```text
0001_baseline.sql
0002_add_example_column.sql
0003_add_example_index.sql
```

- 番号を再利用しない。
- 適用順序が分かるよう連番を維持する。
- 1ファイルの目的を小さく保つ。
- destructiveな操作と無関係なadditive変更を同じファイルへ混在させない。
- migration冒頭に目的、前提、rollbackまたはforward-fix方針を書く。

## 4. migration作成とローカル適用

### 4.1 新規migrationの作成

**LOCAL**

```bash
npx wrangler d1 migrations create zero-capital-insight-db <migration_name> --config ./wrangler.toml
```

生成されたSQLをレビューし、対象テーブル、既存データ、Workerの新旧Versionとの互換性を確認する。

### 4.2 ローカルD1への適用

一時ディレクトリを永続化先として使用し、本番と混同しない。

**LOCAL**

```bash
npx wrangler d1 migrations list zero-capital-insight-db --local --persist-to <temporary-directory> --config ./wrangler.toml
npx wrangler d1 migrations apply zero-capital-insight-db --local --persist-to <temporary-directory> --config ./wrangler.toml
```

適用後、同じ`migrations apply --local`を再度実行し、適用済みmigrationが再実行されず、未適用migrationがないことを確認する。

## 5. 0001 baselineの特別ルール

`CREATE TABLE IF NOT EXISTS`と`CREATE INDEX IF NOT EXISTS`は、既存本番へ安全にmigration管理を導入するための衝突回避である。

**IF NOT EXISTSをschema一致確認の代わりにしてはならない。**

既存本番へ`0001_baseline.sql`を適用する前に、`sqlite_master`とPRAGMAによる完全一致確認が必須である。テーブル、列、型、NOT NULL、DEFAULT、PRIMARY KEY、AUTOINCREMENT、UNIQUE、INDEX、INDEX列順・降順、FOREIGN KEYのいずれかに差異があれば、baselineを適用せず停止して創業者へ報告する。

## 6. schema完全一致確認とfingerprint

### 6.1 取得するメタデータ

次をローカルmigration適用後DBと本番DBの両方から取得する。

1. `sqlite_master`の業務テーブルと明示INDEXのCREATE SQL
2. 各テーブルの`PRAGMA table_info`
3. 各テーブルの`PRAGMA index_list`
4. 各INDEXの`PRAGMA index_info`
5. 降順を含む詳細確認用の`PRAGMA index_xinfo`
6. 各テーブルの`PRAGMA foreign_key_list`

**REMOTE READ-ONLY**

```bash
npx wrangler d1 execute zero-capital-insight-db --remote --config ./wrangler.toml --command "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY type, name;" --json
npx wrangler d1 execute zero-capital-insight-db --remote --config ./wrangler.toml --command "PRAGMA table_info('curation_logs');" --json
npx wrangler d1 execute zero-capital-insight-db --remote --config ./wrangler.toml --command "PRAGMA index_list('curation_logs');" --json
npx wrangler d1 execute zero-capital-insight-db --remote --config ./wrangler.toml --command "PRAGMA foreign_key_list('curation_logs');" --json
```

上記PRAGMAは7業務テーブルすべてに対して行い、INDEXがある場合は`index_info`と`index_xinfo`も取得する。

### 6.2 正規化fingerprint

比較用データは次のように正規化し、安定したJSON配列として並べる。

- `_cf_KV`、ローカルD1の`_cf_METADATA`など名前が`_cf_`で始まる内部テーブル、`sqlite_sequence`、`d1_migrations`を除外する。
- テーブルを名前順に並べる。
- 列を`cid`順にし、`name`、大文字化した`type`、`notnull`、正規化した`dflt_value`、`pk`を記録する。
- 明示INDEXは名前、UNIQUE、origin、列順、DESC情報を記録する。
- `sqlite_autoindex_*`の可変な名前自体には依存せず、UNIQUE制約のoriginと対象列を記録する。
- 外部キーは参照元テーブル、ID、seq、参照先、from、to、更新・削除action、matchを記録する。
- AUTOINCREMENTとテーブル制約確認のため、`sqlite_master.sql`は空白と大小文字の表記差を正規化して記録する。
- 正規化JSONをUTF-8でSHA-256化する。

本番とローカルでhashが一致し、さらに人間が差分ゼロを確認した場合だけ「完全一致」と判定する。初回本番baseline適用前は、一時的な検証コードで比較してよいが、出力に記事本文やSecretを含めない。繰り返し必要になった場合のみ、専用検証スクリプトのGit追加を別工程として検討する。

## 7. 本番適用前チェックリスト

以下が1つでも満たせなければ本番migrationを適用しない。

- 正しいプロジェクト、`main`、承認済みHEADである。
- `main`と`origin/main`のahead/behindが確認済みである。
- 想定外の追跡差分、ステージ差分、未追跡ファイルがない。
- migration SQLがレビュー済みである。
- 空ローカルDBへの全migration適用が成功している。
- 既存schema相当ローカルDBへの適用が成功している。
- migration再実行で未適用なしになる。
- Workerのローカル・モック回帰テストが成功している。
- 本番schemaとbaselineのfingerprintが完全一致している。
- 本番の行数、MIN/MAX ID、MIN/MAX日時を記録した。
- 最新Time Travel bookmarkを取得した。
- schema＋data exportを取得し、安全な保管場所へ保存した。
- exportファイルがGit管理外であることを確認した。
- remote migration listで適用予定が承認対象だけである。
- 創業者が具体的なmigration名と本番操作を明示承認した。

## 8. 本番schemaと集計の読み取り

**REMOTE READ-ONLY**

```bash
npx wrangler d1 execute zero-capital-insight-db --remote --config ./wrangler.toml --command "SELECT COUNT(*) AS row_count, MIN(id) AS min_id, MAX(id) AS max_id, MIN(created_at) AS min_created_at, MAX(created_at) AS max_created_at FROM curation_logs;" --json
```

記事本文は取得しない。必要最小限の件数・ID・日時・NULL件数に限定する。

## 9. Time Travel bookmark

Time TravelはDB全体のポイントインタイム復旧であり、restoreとは別にbookmark取得だけを行える。

**REMOTE READ-ONLY**

```bash
npx wrangler d1 time-travel info zero-capital-insight-db --config ./wrangler.toml --json
```

本番migration適用直前に最新bookmarkを取得し、実行日時、対象DB、migration名とともに安全な運用記録へ残す。bookmark取得だけではDBを変更しない。

## 10. SQL exportと安全な保管

本番migration直前にschema＋data exportを取得する。export中はDBリクエストをブロックする可能性があるため、低アクセス時間帯に行う。

**REMOTE READ-ONLY（本番負荷とデータ持ち出しを伴うため、創業者承認後のみ）**

```bash
npx wrangler d1 export zero-capital-insight-db --remote --config ./wrangler.toml --output=<secure-path>/zero-capital-insight-db_<UTC-timestamp>_pre-migration.sql
```

exportファイルには記事本文その他の業務データが含まれる可能性がある。

- Gitへcommitしない。
- GitHubへpushしない。
- `migrations/`へ置かない。
- `docs/`へ置かない。
- プロジェクト内へ一時保存しない。
- Secretと同様にアクセスを制限する。
- ファイル名にDB識別情報、UTC取得日時、目的を含める。
- hash、サイズ、取得日時、復元テスト結果を別の運用記録へ残す。
- 復旧確認後の保持期間と安全な削除日を創業者が決める。

プロジェクト内にexport保管ディレクトリを設ける場合は、専用ディレクトリだけを`.gitignore`へ追加する。`*.sql`を一括ignoreしてはならない。

## 11. remote migration適用

最初に適用予定だけを確認する。

**REMOTE — 初回は管理schemaを変更する可能性があるため、創業者の明示承認後に実行**

```bash
npx wrangler d1 migrations list zero-capital-insight-db --remote --config ./wrangler.toml
```

### 11.1 Wrangler 4.120.0で確認した初回listの副作用

Wrangler 4.120.0において、migration管理テーブルが存在しない本番D1へ最初の`migrations list --remote`を実行したところ、Wranglerが`d1_migrations`を暗黙に作成した。したがって、このプロジェクトではコマンド名が`list`であることだけを理由に、完全な読み取り専用操作とはみなさない。

初回のmigration管理導入時、または管理状態が不明なD1へmigration系Wranglerコマンドを実行する前には、次を完了し、創業者の明示承認を得る。

1. 現在のschemaと`d1_migrations`の存在状態を確認する。
2. 最新のTime Travel bookmarkを取得する。
3. schemaとdataを含むSQL exportをGit管理外へ保存し、サイズとSHA-256を確認する。
4. 管理テーブル作成を含む副作用と影響範囲を確認する。
5. 実行対象DB、予定migration、停止条件を明示する。

今回の本番導入では、暗黙に作成された`d1_migrations`が`id`、`name`、`applied_at`の3列で、適用前の記録が0件、想定外migrationがないことを確認した。その後、創業者の明示承認を得て`0001_baseline.sql`を正式適用し、業務schemaのfingerprintと業務データが適用前後で不変であることを確認した。

次のコマンドは本番D1を書き換える。

**REMOTE DESTRUCTIVE — 創業者の明示承認なしに実行禁止**

```bash
npx wrangler d1 migrations apply zero-capital-insight-db --remote --config ./wrangler.toml
```

`migrations list`は適用予定を確認する操作だが、上記のとおり初回に管理schemaを初期化する可能性がある。また、直後に適用コマンドが続くため、対象DBと適用予定ファイルを二者確認する。初回baselineでは適用予定が`0001_baseline.sql`だけでなければ停止する。

## 12. 適用後確認

適用直後は追加の書き込み処理を呼ばず、次を読み取り確認する。

1. `d1_migrations`に`0001_baseline.sql`が1件だけ記録された。
2. schema fingerprintが適用前と一致する。
3. 7業務テーブルが維持された。
4. INDEX、UNIQUE、FOREIGN KEYが維持された。
5. `curation_logs`の行数、MIN/MAX ID、MIN/MAX日時が不変である。
6. `/`、ページネーション、記事、sitemap、robotsが正常である。
7. D1 binding、SITE_URL、Cron設定が維持された。
8. 本番でLLM、Discord、Cronの強制実行を行わない。

## 13. Workerとの互換性

schema変更は次の組み合わせをローカルで確認する。

- 旧Worker＋旧schema
- 旧Worker＋新schema
- 新Worker＋旧schema
- 新Worker＋新schema

原則としてexpand/contractを使用する。

1. nullable列や新テーブルを追加する。
2. 新旧コードが共存できる期間を設ける。
3. 必要なら承認済みbackfillを行う。
4. 新コードへ切り替える。
5. 十分な確認後、別migrationで古い構造を整理する。

## 14. rollbackとforward migration

- 適用済みmigrationを編集しない。
- additiveな不具合は新しいforward migrationで修正する。
- INDEXの問題も新しいmigrationで修正する。
- schema・データを破壊した場合だけTime Travel restoreを検討する。
- Worker rollbackとDB restoreは別操作である。
- Workerを戻してもD1 schema・データは戻らない。
- DB restore前に旧Workerとのschema互換性を確認する。

## 15. migration失敗時

Wranglerがmigration失敗を報告した場合、追加migration、手動SQL、再実行をその場で行わない。

1. エラー全文、対象DB、migration名、時刻を記録する。
2. `d1_migrations`とschemaを読み取る。
3. データ集計値を読み取る。
4. WorkerとCronの状態を確認する。
5. ローカルで原因を再現する。
6. 新しいforward migrationまたは再リリース案をレビューする。
7. 創業者の再承認を得る。

## 16. Time Travel restore

restoreは本番DB全体を過去時点へ上書きし、復元時点以降の正常な書き込みも失わせる。実行中のクエリ・transactionもキャンセルされる。

**REMOTE DESTRUCTIVE — 創業者の明示承認なしに実行禁止**

```bash
npx wrangler d1 time-travel restore zero-capital-insight-db --bookmark=<approved-bookmark> --config ./wrangler.toml
```

restore前に必ず現在状態をexportし、失われる時間範囲と書き込み件数を確認する。restore結果が返す復元前bookmarkを保存し、取り消し可能性を維持する。

## 17. SQL exportからの復旧

既存DBへのimportはデータ重複や衝突を起こし得るため、原則として新しい空DBへ復旧する。

1. exportのhashと取得日時を確認する。
2. ローカルD1へimportしてschema・件数を検証する。
3. 創業者承認後、新しい本番D1を作成する。
4. export SQLを新DBへimportする。
5. schema fingerprintと集計を確認する。
6. `wrangler.toml`のbinding先変更をレビューする。
7. Workerをデプロイする。
8. 公開ページを検証する。
9. 旧DBは即時削除せず、復旧確認まで保持する。

新DB作成、remote import、binding変更、デプロイ、旧DB削除はすべて**REMOTE DESTRUCTIVE**であり、個別の創業者承認を必要とする。

## 18. 緊急時の停止順序

1. 運用POST経路の利用と手動処理を止める。
2. 必要なら創業者承認後にCronを止める。
3. 本番デプロイとmigrationを止める。
4. 発生時刻、Worker Version、migration、bookmarkを記録する。
5. 現在のschemaと最小集計を読み取る。
6. 現在状態をexportする。
7. Worker rollbackだけで安全に復旧できるか判断する。
8. forward migrationで直せるか判断する。
9. 最後の手段としてTime Travel restoreを承認する。
10. 復旧後に公開ページ、D1、Cron設定を確認する。

## 19. destructive operationの承認ルール

次はAIが準備・レビュー・ローカル検証まで行える。

- additive migrationの作成
- ローカルD1への適用
- schema比較
- 復旧案の作成
- 本番の読み取り確認

次は常に創業者の明示承認を必要とする。

- remote migration apply
- CREATE、ALTER、DROP
- INSERT、UPDATE、DELETE、backfill
- Time Travel restore
- SQL import
- 新DB作成・DB削除
- binding変更
- Cron変更
- export取得と保管場所の決定

特にDROP、DELETE、データ変換、restoreでは、対象、件数、復元点、最悪損失、停止条件を承認前に明示する。

## 20. 定期backup方針

- Time Travelが利用可能であることを定期確認する。
- Workers Freeを前提に保持期間を7日として保守的に扱う。契約プランが確認できた場合だけ30日へ読み替える。
- 少なくとも週1回、schema＋data exportを検討する。
- schema変更、データ変換、大規模デプロイの直前には必ずexportする。
- exportは低アクセス時間帯に取得する。
- 定期的にGit管理されたmigrationだけで空ローカルDBを再構築する。
- exportからローカルDBへの復元テストを定期実施する。
- 復元テストに成功していないexportを、唯一の復旧手段とみなさない。

## 21. 初回baseline本番適用の確定順序

1. Git・Worker・ブランチ・差分状態を確認する。
2. 本番schemaを再取得し、ローカルbaselineとのfingerprint完全一致を確認する。
3. 本番`curation_logs`の行数、MIN/MAX ID、MIN/MAX日時を記録する。
4. 最新Time Travel bookmarkを取得する。
5. schema＋data exportを取得する。
6. exportの安全な保管場所、hash、サイズを確認する。
7. `migrations list --remote`を実行する。
8. 適用予定が`0001_baseline.sql`だけであることを確認する。
9. 上記証拠を提示し、創業者からremote applyの明示承認を得る。
10. `0001_baseline.sql`をremote applyする。
11. `d1_migrations`に1件だけ記録されたことを確認する。
12. schema fingerprintを再確認する。
13. 行数、MIN/MAX ID、MIN/MAX日時が不変であることを確認する。
14. 公開ページ、記事、sitemap、robotsを読み取り確認する。
15. D1 binding、SITE_URL、Cron設定を確認する。Cronは手動実行しない。
16. 意図したファイルだけをGitへ保存する。
17. Master Blueprintの状態台帳と変更履歴を更新する。

この順序の途中で差異、失敗、想定外のmigration、データ変化を検出した場合は、追加修正やrestoreを行わず停止する。

## 22. stale run・Discord結果不明の照合と復旧

### 22.1 絶対ルール

- `notification_status='sending'` は送達結果不明であり、自動再送しない。
- Discord上で送達済みか未送信かを判別できない場合、状態を変更せず人間判断待ちを維持する。
- 記事本文、Idempotency-Key、Webhook URL、Secretを照合一覧や監査メモへ記録しない。
- GETは分類だけを行い、pipeline状態を変更しない。
- 復旧POSTはBearer認証、固有の`Reconciliation-Key`、10〜240文字の根拠メモを必須とする。
- 同じ`Reconciliation-Key`の再実行は同じrun・actionに限り既存結果を返し、二重変更しない。

### 22.2 読み取りと分類

`GET /pipeline-reconciliation`を認証付きで呼び出す。最大100件の安全なメタデータだけを返し、記事本文とIdempotency-Keyは返さない。

- `delivery_unknown_human_review`: Discord送達結果不明。自動操作禁止。
- `stale_without_article_can_fail`: lease期限切れ、記事なし。ログで実行停止を確認後に失敗確定可能。
- `saved_state_repair_available`: runはrunningだが紐付け記事あり。通知を送らずsaved境界へ修復可能。
- `saved_unsent_manual_resume_required`: 記事保存済み・通知attempt前。別途、明示的な同一Key手動実行を行うまで送信しない。
- `notification_failed_manual_review`: Discordが明確な失敗を返した状態。原因確認後だけ手動再実行を検討する。

### 22.3 許可する状態変更

`POST /pipeline-reconciliation`へ`runId`、`action`、`evidence`を送る。すべて比較更新であり、確認時から状態が変わっていれば409で停止する。

- `mark_stale_failed`: `running/pending`、lease期限切れ、記事なしだけを`failed/pending`へ変更する。
- `repair_saved_state`: `running/pending`かつ記事ありだけを`saved/pending`へ変更する。Discord送信は行わない。
- `confirm_notification_delivered`: Discord上の送達を確認できた`saved/sending`だけを`completed/sent`へ変更する。
- `confirm_notification_not_delivered`: Discord側の証拠で未送信を確定できた`saved/sending`だけを`saved/failed`へ変更する。この操作自体は再送しない。

判断内容は`pipeline_reconciliation_events`へ永続記録する。`sending`のまま判別不能、対象記事不一致、証拠不足、409競合、DB応答不明の場合は追加操作を行わず、最新状態を再読込する。

### 22.4 本番反映順序

`0003_pipeline_reconciliation_audit.sql`は監査テーブルとINDEXだけを追加するadditive migrationである。既存runと記事は変更しない。ただしremote applyは本番変更のため、既存の事前read、bookmark、export、fingerprint、創業者承認をすべて完了してから行う。migration適用前のWorkerへ新コードをdeployしてはならない。適用後も状態変更POSTを本番確認目的で実行せず、まず認証・405・読み取り一覧・公開経路を確認する。
