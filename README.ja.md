# SkillSeam

[English](README.md) | [简体中文](README.zh-CN.md) | **日本語** | [한국어](README.ko.md) | [Español](README.es.md) | [Deutsch](README.de.md)

<p align="center">
  <img src="assets/banner.svg" alt="SkillSeam" width="720">
</p>

エージェントがスキルを実際に選ぶ様子をシミュレートし、どのスキルが誰のタスクを奪っているのかを公開します。ユーザーが気づく前に。

## 問題

Claude Code や Codex などのエージェントランタイムは、スキルを読み込むときに description の数行だけを見ます。タスクが来ると、最もそれらしいスキルが選ばれます。

説明が重ならない限りそれで動きます。私たちの病院デモでは、予約スキルの description に「視力レポートの問い合わせも対応」と書かれていました。本当の担当はレポート解読スキルです。患者がレポートの解読を頼むと、予約スキルが答え、そしてでたらめを作ります。エラーも出ず、ログも残りません。患者からのクレームで初めて発覚しました。

SkillSeam は、出荷前にその選択プロセスを再生します。6 スキル・40 タスクのデモで、仕込んだ 4 件の競合をすべて検出し（票の一貫性 5/5）、クリーンなタスクは全て通過しました。各レポートには、横取りの原因となった description 内のキーワードが特定して表示されます。

## クイックスタート（Web、インストール不要）

[https://snow7-g.github.io/SkillSeam/](https://snow7-g.github.io/SkillSeam/) を開き、デモボタンを押すと 10 秒でヒートマップが表示されます。自分のスキルを貼り付けて、API キーを追加し（キーはブラウザ内のみ、リクエストはプロバイダーへ直通）、「実行」を押すだけです。

SKILL.md として保存している場合は、貼り付け用に出力できます:

```bash
python3 skill_seam.py export ~/.agents/skills
```

## CLI（ローカルディレクトリ、CI ゲート）

```bash
git clone https://github.com/Snow7-G/SkillSeam && cd SkillSeam
echo '{"base_url": "https://.../v1", "api_key": "sk-...", "model": "..."}' > .atlasrc.json
python3 skill_seam.py ~/.agents/skills
open output/report.html
```

終了コード: 0 は競合なし、1 は競合あり、2 は設定ミス。CI への組み込みは一行です:

```bash
python3 skill_seam.py ./skills --tasks ci-tasks.json || echo "conflicts found, blocking merge"
```

## 本物の問い合わせは生成より強い

最初に正直な限界を: LLM が生成するテストタスクには偏りがあります。生成するモデルはどちらのスキルが勝つべきかを知っているので、簡単に通ってしまうのです。デモでは、生成タスクは競合 0 件、本物のユーザーの問い合わせは 4 件でした。同じスキル、同じモデルです。

そこで本ツールには、本物の問い合わせを集める方法が 3 つ組み込まれています:

```bash
# 一度だけ設定: Claude Code に送るプロンプトが静かにローカル記録されます
python3 skill_seam.py capture --install-claude

# エージェントの誤選択を見つけた瞬間、永久に保管
python3 skill_seam.py mark "フォローアップ時に会員ポイントを確認して" followup-reminder

# 記録されたプロンプト（または Codex セッションログ）からラベル付きドラフトを生成
python3 skill_seam.py harvest ./skills --codex --label --out tasks-draft.json
```

ドラフトを確認し、想定スキルを埋めて実行。実災害 10 件は、どの生成器より良いタスクセットになります。

生成タスクはスモークテストとして使えます。ただし、緑だから競合がない証明にはなりません。

## 仕組み

1. スキルディレクトリを走査し、SKILL.md のフロントマターを解析して形式を検査します。
2. タスクセットを構築: 各スキルの明確な質問に加え、2 つのスキルが重なる境界にわざと曖昧な質問を配置します。
3. 選択を再生: モデルには name と description だけを、エージェントと同じ形式で渡し、タスクごとに 1 スキルを選ばせます。各タスク 5 回、temperature 0.7。
4. 多数決で集計。5 回中 4 回以上同じ誤選択で一致した場合のみ競合と数えます。それ未満は不安定としてマークし、レポートを汚しません。

レポートは自己完結した単一 HTML で、混同行列のヒートマップ付き。競合がある場合は description の改訂案（修正前後の対比）も生成します。

## 類似ツールとの比較

| ツール | 検査対象 | 粒度 |
|---|---|---|
| agnix | 形式規則（フロントマター、命名） | 単一ファイル |
| skilltest | 単一スキルが単独で発火するか | 単一スキル |
| SkillSpector (NVIDIA) | セキュリティ（インジェクション、外部送信） | 単一スキル |
| **SkillSeam** | 組み合わせ後の選択挙動: 誰が誰のタスクを奪うか | スキルセット全体 |

競合ではなく補完です。スキルごとに lint とセキュリティスキャンを実行した上で、セット全体に SkillSeam を実行してください。

## 注意点

シミュレーションは注入形式に忠実ですが、実際のエージェントプロセスを駆動するものではありません。ランタイム間の違い（Codex と Claude で選択が変わるか）はロードマップ上です。Codex セッション解析は寛容な抽出器のため、ツール出力が収集候補に混入することがあります。Web UI は現在中国語です。

## 名前の由来

競合はスキルの中には住んでいません。2 つのスキルの縫い目に住んでいて、誰かが引っ張るとほどけます。SkillSeam は縫い目を検査します。

検出レポートは Sirens Report（セイレーン報告）と呼びます。ハイネの言葉が最も良い:

> Ich weiß nicht, was soll es bedeuten,
> dass ich so traurig bin.

乙女はそこに座り、黄金の髪を梳きながら歌います。船頭は歌を聞いて、岩が見えなくなります。

すべての description は歌っています。その歌が、あなたのタスクを岩へ誘うことがあるのです。

## 開発

```bash
python3 tests/test_atlas.py   # 58 テスト、標準ライブラリのみ
node tests/web_smoke.cjs      # 19 web アサーション、node >= 18
```

CI は Python 3.10 / 3.12 / 3.13 で両方を実行します。PR の前に CONTRIBUTING.md をご覧ください。

## ライセンス

MIT
