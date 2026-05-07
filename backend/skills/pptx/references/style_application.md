# Applying Extracted StyleSpec (Phase 2)

ユーザーメッセージに含まれる **StyleSpec ブロック** を PptxGenJS / python-pptx
の生成・編集に反映させる方法のリファレンス。

ブロックは次の形式で来ます:

```
【スタイル仕様 (target|style_ref) — artifact_id: ...】
palette: primary=#1E2761, secondary=#CADCFC, accent=#F96167, ...
typography: header_font='Cambria', body_font='Calibri', title_pt=40, ...
geometry: margin_emu=457200, block_gap_emu=274320, slide=12192000x6858000 EMU
decoration: motif=rounded-cards, accent_lines=False, dark_title=True
tone_tags: ['executive','calm']
templates:
  - kind=cover, src_slide=0, shapes=[title, subtitle, decoration]
  - kind=closing, src_slide=14, shapes=[title, body, decoration]
```

## Layer A の使い方 (generate_pptx.py)

### 1. palette を直接 PptxGenJS の color に流す

```javascript
const PALETTE = {
  primary:   '1E2761',  // PptxGenJS は '#' 無し
  secondary: 'CADCFC',
  accent:    'F96167',
  bgLight:   'FFFFFF',
  bgDark:    '0E1330',
  textMain:  '212121',
  textSub:   '5A6478',
};

slide.addText('タイトル', {
  x: 0.5, y: 0.3, w: 9, h: 1,
  fontSize: 40, fontFace: 'Cambria',
  color: PALETTE.textMain, bold: true,
});

slide.addShape(pptx.ShapeType.rect, {
  x: 0, y: 0, w: 13.33, h: 0.6,
  fill: { color: PALETTE.primary },
  line: { type: 'none' },
});
```

ベタ書きの色 (`'#1E88E5'` など) は使わず、必ず palette 経由で参照してください。

### 2. typography を分離して使う

```javascript
const FONT_HEADER = 'Cambria';   // typography.header_font
const FONT_BODY   = 'Calibri';   // typography.body_font
const SIZE = { title: 40, section: 22, body: 15, caption: 11 };

slide.addText('章タイトル', { fontFace: FONT_HEADER, fontSize: SIZE.section, bold: true });
slide.addText('本文', { fontFace: FONT_BODY, fontSize: SIZE.body });
```

### 3. geometry の余白を尊重する

`margin_emu = 457200` (= 0.5インチ) なら `x: 0.5` 開始、`block_gap_emu` を
EMU/914400 でインチ換算してブロック間隔に使う。

### 4. decoration.motif を再現する

| motif | 実装パターン |
|---|---|
| `rounded-cards` | `addShape(roundRect, {rectRadius: 0.1, fill, ...})` で角丸カード |
| `side-bar` | スライド左端に細い帯 (`addShape(rect, {x:0,y:0,w:0.4,h:7.5,fill:primary})`) |
| `icon-circles` | アイコンを丸で囲む (`addShape(ellipse, {fill:accent})` + アイコン) |
| `thick-borders` | 各コンテンツ枠に太い1辺ボーダー |
| `gradient-bg` | 背景にグラデ shape |
| `minimal` | 装飾shape禁止、余白で表現 |
| `none` | 何もしない |

### 5. uses_accent_lines が false の場合

タイトル下にアクセント線を**絶対に入れない**でください。AI生成スライドの
典型悪パターンとして検出される対象です（SKILL.md "Avoid" 参照）。

## Layer B の使い方 — テンプレートの再利用

### ★ 推奨: コピー方式 (`copy_slide_from_artifact`)

最も忠実に再現するなら、style_ref のスライドを **そのままコピー** して
テキストだけ差し替える方式を使ってください。Layer B 座標から PptxGenJS で
再描画するより精度が高いです (フォント・装飾・微妙な位置が完全一致)。

ワークフロー:

```python
# Step 1: 本文スライドだけ generate_pptx.py で生成
run_skill_script(
    skill_name="pptx",
    script_path="scripts/generate_pptx.py",
    script_args={"code": "<本文4-10枚分の PptxGenJS コード>", "output_filename": "body.pptx"},
)
# → __PPTX_ARTIFACT__ で artifact_id_A が返る

# Step 2: edit_pptx.py で cover 等をコピー + プレースホルダ置換を一発適用
run_skill_script(
    skill_name="pptx",
    script_path="scripts/edit_pptx.py",
    script_args={
        "artifact_id": "<artifact_id_A>",
        "ops": json.dumps([
            # cover を style_ref から先頭にコピー
            {"type": "copy_slide_from_artifact",
             "source_artifact_id": "<style_ref_artifact_id>",
             "src_slide": 0,        # Layer B kind=cover の source_slide_idx
             "insert_at": 0},
            # closing を末尾にコピー (任意)
            {"type": "copy_slide_from_artifact",
             "source_artifact_id": "<style_ref_artifact_id>",
             "src_slide": 14,       # Layer B kind=closing の source_slide_idx
             "insert_at": 9999},     # 末尾
            # cover の "<<TITLE>>" 文字列を実テキストに置換
            # (text op の slide=0 は copy_slide_from_artifact 適用後のindex)
            {"type": "text", "slide": 0, "shape": 1, "para": 0, "run": 0,
             "text": "ユーザーが求めるタイトル"},
            {"type": "text", "slide": 0, "shape": 2, "para": 0, "run": 0,
             "text": "サブタイトル"},
        ]),
        "output_filename": "deck.pptx",
    },
)
```

戻り値の `applied[].result.skipped_pictures > 0` の時は元スライドに画像が
あり、画像だけは転送されていません。必要なら次の op で `add_image` で
補完してください。

### 代替: PptxGenJS で再描画 (copy ができない時)

cover (表紙)

`templates: kind=cover, src_slide=0, shapes=[title, subtitle, decoration]` が
あれば、表紙スライドはこの shape 配置をそのまま PptxGenJS で再現:

```javascript
const cover = pres.addSlide();
// 抽出された shape の x/y/cx/cy を EMU/914400 でインチ換算
// title shape (例: x=914400, y=2057400, cx=10363200, cy=914400 EMU)
cover.addText(USER_TITLE, {
  x: 1.0, y: 2.25, w: 11.33, h: 1.0,
  fontFace: FONT_HEADER, fontSize: SIZE.title, bold: true,
  color: PALETTE.textMain,
});
// subtitle shape, decoration shape ...
```

text_template の `<<TITLE>>` を実テキストに、`<<SUBTITLE>>` をユーザーが
求めるサブタイトルに差し替えれば、表紙のレイアウトは元PPTXと一致した
ままタイトルだけ自前のものになります。

### closing / section_divider / agenda

同じ要領で template の shape 配置を踏襲。プレースホルダ命名規則:

| placeholder | 用途 |
|---|---|
| `<<TITLE>>` / `<<SUBTITLE>>` | タイトル類 |
| `<<BODY_1>>`, `<<BODY_2>>`, ... | 本文段落 |
| `<<BULLET_1>>`, `<<BULLET_2>>`, ... | 箇条書き行 |
| `<<STAT_NUMBER>>` / `<<STAT_LABEL>>` | 統計数字 + ラベル |
| `<<CAPTION>>` | キャプション |
| `<<TEXT_1>>`, `<<TEXT_2>>`, ... | その他テキスト |

### content_* テンプレート

`content_two_col` / `content_grid` / `content_one_col` は本文ページの
代表的レイアウト。複数あれば1つを採用、または交互に使ってリズムを作る。

### is_decoration=true な shape

text を持たない装飾図形。`fill_role` を見て palette から色を引く:

```javascript
// shape: {role: 'decoration', is_decoration: true, fill_role: 'accent', ...}
slide.addShape(pptx.ShapeType.rect, {
  x: ..., y: ..., w: ..., h: ...,
  fill: { color: PALETTE.accent },
  line: { type: 'none' },
});
```

## intent との組み合わせ

| intent | StyleSpec の扱い |
|---|---|
| `tweak` | 触らない。指定箇所のテキスト/色のみ変更。 |
| `polish` | palette/typography は保ったままレイアウト整形。Layer B のテンプレは存在しても**踏襲は任意**。 |
| `restructure` | Layer A/B を強く反映して再構成。元の文章は保持。 |
| `from-scratch` | Layer A は必ず適用。Layer B のテンプレは表紙・章扉・エンディングで優先採用。 |

## 抽出失敗時 (style_extracted: status=failed)

StyleSpec ブロックがメッセージに無ければ、抽出は失敗または不要です。
SKILL.md の Design Ideas (palette / typography / motif の標準集) から
適切なものを選んで自前で組み立ててください。
