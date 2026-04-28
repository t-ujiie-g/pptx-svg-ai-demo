# Editing Presentations (python-pptx)

## Overview

既存 PPTX の編集は `scripts/edit_pptx.py` で行います（`run_skill_script` 経由）。
Python の python-pptx ライブラリを使って **1 回のツール呼び出しでバッチ適用** します。

「編集」には次のすべてが含まれます:
- 既存シェイプのテキスト / 色 / 位置サイズ変更
- **新しい情報を調べてスライドを追加する**
- スライドの複製・削除・並べ替え

---

## 入力情報の見方

ユーザーメッセージには、各スライドの **PNG 画像** と **全シェイプの構造情報** が
最初から添付されています（サーバー側が `pptx_inspect.js` で生成）。

構造情報の見方:

```
--- スライド 0 ---
  shape[0] type=autoshape pos=(914400,914400) size=(7315200,914400) rot=0
    text[p0,r0]: 'タイトルテキスト'
  shape[1] type=autoshape pos=(914400,2743200) size=(2743200,914400) rot=0 fill=#4472C4
  shape[2] type=graphicFrame pos=(914400,3657600) size=(7315200,1828800) rot=0
    table rows=2 cols=3
      cell[0,0] fill=#1E2761: '項目'
      cell[0,1]: '値'
      cell[0,2]: '備考'
      cell[1,0]: 'A'
      cell[1,1]: '1'
      cell[1,2]: ''
```

各シェイプの情報:
- `shape[N]` の `N`: シェイプインデックス（ops の `shape` に指定）
- `type`: `autoshape`(図形), `pic`(画像), `graphicFrame`(表/グラフ) 等
- `pos=(x,y)` / `size=(cx,cy)`: 位置とサイズ（EMU 単位。1 インチ = 914400 EMU）
- `rot`: 回転（60000 分の 1 度単位。90 度 = 5400000）
- `fill=#...`: 塗りつぶし色（6 桁 hex）
- `text[p{pi},r{ri}]`: テキスト内容
  - `pi`: 段落（paragraph）インデックス
  - `ri`: ラン（テキスト区間）インデックス
- `table rows=R cols=C` + `cell[r,c]`: テーブル（`graphicFrame` の中身）
  - `r`/`c` を ops の `row`/`col` に指定して編集

---

## 編集ツール

### run_skill_script 経由で edit_pptx.py を実行

```python
run_skill_script(
    skill_name="pptx",
    script_path="scripts/edit_pptx.py",
    script_args={
        "artifact_id": "abc-123",
        "ops": '[{"type":"text","slide":0,"shape":0,"para":0,"run":0,"text":"新タイトル"}]',
        "output_filename": "updated.pptx",
    },
)
```

**`ops` は JSON 文字列** として渡します（配列をそのまま渡さず JSON エンコード）。
ops は先頭から順に適用されるので、スライド追加/削除後は更新後のインデックスで
参照してください。

### Op 種類

#### テキスト変更

```json
{"type":"text", "slide":0, "shape":2, "para":0, "run":0, "text":"新しいタイトル"}
```

- `para` / `run` は構造情報の `text[p*,r*]` に対応
- 既存のラン内容を置換します（新しい段落/ランの追加はできません）

#### 塗りつぶし色変更

```json
{"type":"fill", "slide":0, "shape":2, "r":68, "g":114, "b":196}
```

RGB 値（0-255）で指定。

#### 位置・サイズ・回転変更

```json
{"type":"transform", "slide":0, "shape":2,
 "x":914400, "y":914400, "cx":7315200, "cy":914400, "rot":0}
```

#### スライド複製（スライド追加の推奨方法）

```json
{"type":"duplicate_slide", "source":3, "insert_after":3}
```

- `source`: 複製元スライドのインデックス
- `insert_after`: 挿入位置。省略時は末尾。`insert_after:3` の場合、新スライドは
  index 4 に配置される（元の 4 以降は 1 つずつ後ろにずれる）
- 既存デッキのレイアウト・配色・フォントがそのまま継承される

#### スライド削除

```json
{"type":"delete_slide", "slide":4}
```

#### テーブル編集

セル単位で操作。`row`/`col` は構造情報の `cell[r,c]` に対応:

```json
{"type":"table_cell_text",      "slide":0, "shape":2, "row":1, "col":0, "text":"AAA"}
{"type":"table_cell_fill",      "slide":0, "shape":2, "row":0, "col":0, "r":30, "g":39, "b":97}
{"type":"table_cell_fill_none", "slide":0, "shape":2, "row":0, "col":0}
{"type":"table_cell_style",     "slide":0, "shape":2, "row":0, "col":0,
 "bold":true, "italic":false, "font_size":14, "font_name":"Arial",
 "color_r":255, "color_g":255, "color_b":255, "align":"center"}
```

テーブル新規追加（`data` で初期セル値を指定可。省略時は空セル）:

```json
{"type":"add_table", "slide":0, "rows":3, "cols":2,
 "x":914400, "y":3657600, "cx":7315200, "cy":1828800,
 "data":[["項目","値"],["A","1"],["B","2"]]}
```

行の追加・削除:

```json
{"type":"add_table_row",    "slide":0, "shape":2, "after":1}
{"type":"delete_table_row", "slide":0, "shape":2, "row":2}
```

- `add_table_row`: `after` 行をコピーして直後に挿入（書式は引き継ぎ、テキストは空）。`after` を省略すると末尾に追加
- 列の追加・削除は未対応（必要なら新しいテーブルを `add_table` してください）

#### スライド背景色

```json
{"type":"slide_background", "slide":0, "r":248, "g":249, "b":252}
{"type":"slide_background", "slide":0, "fill_none": true}
```

`fill_none:true` で背景指定を削除し、レイアウト/マスターの背景に戻ります。

#### 箇条書き / インデントレベル

`add_paragraph` または `paragraph_bullet` で設定:

```json
{"type":"add_paragraph",    "slide":0, "shape":1, "text":"トップレベル", "level":0, "bullet":"dot"}
{"type":"add_paragraph",    "slide":0, "shape":1, "text":"サブ項目",     "level":1, "bullet":"dot"}
{"type":"add_paragraph",    "slide":0, "shape":1, "text":"番号付き",     "bullet":"number"}
{"type":"paragraph_bullet", "slide":0, "shape":1, "para":0, "bullet":"none"}
{"type":"paragraph_bullet", "slide":0, "shape":1, "para":1, "bullet":"dot",
 "char":"▶", "color_r":30, "color_g":39, "color_b":97}
```

`bullet` 指定値:
- `"none"`: 箇条書きを外す
- `"dot"`: ● （`char` で別の文字に変更可、例: `"▶"`, `"–"`, `"・"`）
- `"number"` / `"arabicPeriod"` / `"alphaUcPeriod"` / `"romanLcPeriod"` 等: 自動採番
- 上記以外の文字列: その文字を箇条書き記号として使用

`level` は 0〜8 のインデントレベル。テンプレートのレベル別スタイル（フォント・色）が適用されます。

EMU 換算表:

| 単位 | EMU |
|------|-----|
| 1 インチ | 914400 |
| 1 cm | 360000 |
| 1 pt | 12700 |

スライドサイズ（標準 16:9）: 12192000 x 6858000 EMU

---

## 編集例

### タイトルとサブタイトルの変更

```python
run_skill_script(
    skill_name="pptx",
    script_path="scripts/edit_pptx.py",
    script_args={
        "artifact_id": "abc-123",
        "ops": json.dumps([
            {"type":"text","slide":0,"shape":0,"para":0,"run":0,"text":"2026年AI最新動向"},
            {"type":"text","slide":0,"shape":1,"para":0,"run":0,"text":"主要AIモデルの比較と展望"},
        ]),
        "output_filename": "AI_Trends_Updated.pptx",
    },
)
```

### 複数スライドの色を統一

```python
ops = [{"type":"fill","slide":s,"shape":0,"r":30,"g":39,"b":97} for s in [0, 1, 2, 3]]
run_skill_script(
    skill_name="pptx",
    script_path="scripts/edit_pptx.py",
    script_args={
        "artifact_id": "abc-123",
        "ops": json.dumps(ops),
        "output_filename": "recolored.pptx",
    },
)
```

### 既存スライドをコピーして新メンバーのページを追加

山本選手のスライド（index=3）を複製して佐々木選手のスライドを追加する例:

```python
ops = [
    {"type":"duplicate_slide","source":3,"insert_after":3},
    # 新スライドは index 4 になる
    {"type":"text","slide":4,"shape":0,"para":0,"run":0,"text":"佐々木選手"},
    {"type":"text","slide":4,"shape":1,"para":0,"run":0,"text":"日本代表MF"},
    {"type":"text","slide":4,"shape":2,"para":0,"run":0,"text":"2001年生まれ"},
]
run_skill_script(
    skill_name="pptx",
    script_path="scripts/edit_pptx.py",
    script_args={
        "artifact_id": "abc-123",
        "ops": json.dumps(ops),
        "output_filename": "roster_updated.pptx",
    },
)
```

**ポイント**:
- `duplicate_slide` の直後、新スライドは `insert_after+1` の位置にある
- テキストの `shape`/`para`/`run` は複製元スライドの構造情報と同じ
- 既存デッキのデザイン（配色・フォント・レイアウト）がそのまま保たれる

---

## 戻り値の確認

`edit_pptx.py` の stdout 出力:

```
{"applied":[{"index":0,"ok":true,"type":"duplicate_slide"},{"index":1,"ok":true,"type":"text"}]}
__PPTX_ARTIFACT__ {"artifact_id":"...","filename":"...","size_bytes":...,"download_url":"/artifacts/..."}
```

- `applied`: 各 op の成否 — 失敗があれば修正して再実行
- `__PPTX_ARTIFACT__` マーカー行はサーバー側が検知して自動的にユーザーにダウンロード提供

視覚的な最終確認は次のターンで、ユーザーメッセージに最新 PNG が再添付されます。

---

## 注意事項

- **artifact_id がある場合は必ず `edit_pptx.py` 経由**。`generate_pptx.py` で新規作成すると編集内容が失われます
- `ops` 内で `slide` インデックスを指定するときは **それまでに適用された ops 後の状態** を前提にすること
  （例: `duplicate_slide` の後は全体のスライド数が 1 増え、挿入位置以降のインデックスがずれる）
- テキスト変更は既存のラン内容を置換します。新しい段落やランの追加はできません
- `duplicate_slide` は画像やハイパーリンクの relationships も複製しますが、スピーカーノートは複製されません
