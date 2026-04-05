# Editing Presentations (pptx-svg)

## Overview

既存PPTXの編集には **pptx-svg ブリッジ** を使用します。
これはNode.jsベースのPPTX編集エンジンで、シェイプ単位のテキスト・色・位置の変更とPPTXエクスポートが可能です。

LibreOffice や unpack/pack は **不要** です。

---

## 編集フロー

### 1. PPTXをロード

```
load_pptx(artifact_id="<artifact-id>")
```

返り値にはスライドごとのシェイプ一覧が含まれます:

```
slides[0]:
  shape[0] type=sp pos=(457200,274638) size=(8229600,1143000)
    text[p0,r0]: "タイトルテキスト"
  shape[1] type=sp pos=(457200,1600200) size=(8229600,4525963)
    text[p0,r0]: "本文テキスト"
    fill=#4472C4
```

各シェイプの情報:
- `idx`: シェイプインデックス（編集時に使用）
- `shape_type`: `sp`(図形), `pic`(画像), `graphicFrame`(表/グラフ)等
- `x, y, cx, cy`: 位置とサイズ（EMU単位。1インチ = 914400 EMU）
- `rot`: 回転（60000分の1度単位）
- `fill_hex`: 塗りつぶし色（6桁hex）
- `text_runs`: テキスト内容 `[{pi, ri, text}]`
  - `pi`: 段落インデックス
  - `ri`: ラン（テキスト区間）インデックス

### 2. スライド情報の確認

特定スライドの詳細を取得:

```
get_slide_shapes(slide_idx=0)
```

### 3. 編集操作

#### テキスト変更

```
edit_shape_text(
    slide_idx=0,
    shape_idx=2,
    para_idx=0,
    run_idx=0,
    new_text="新しいタイトル"
)
```

- `para_idx` / `run_idx` は `text_runs` の `pi` / `ri` に対応
- 1つのシェイプ内で複数の段落・ランがある場合、それぞれ個別に変更

#### 色変更

```
edit_shape_fill(
    slide_idx=0,
    shape_idx=2,
    r=68, g=114, b=196
)
```

- RGB値（0-255）で指定

#### 位置・サイズ変更

```
edit_shape_transform(
    slide_idx=0,
    shape_idx=2,
    x=457200,    # X位置 (EMU)
    y=274638,    # Y位置 (EMU)
    cx=8229600,  # 幅 (EMU)
    cy=1143000,  # 高さ (EMU)
    rot=0        # 回転 (60000分の1度)
)
```

EMU換算表:
| 単位 | EMU |
|------|-----|
| 1インチ | 914400 |
| 1cm | 360000 |
| 1pt | 12700 |

スライドサイズ（標準 16:9）: 12192000 x 6858000 EMU

### 4. 保存

```
save_edited_pptx(output_filename="updated_presentation.pptx")
```

---

## 編集例

### タイトルとサブタイトルの変更

```
load_pptx(artifact_id="abc-123")

# タイトルを変更
edit_shape_text(slide_idx=0, shape_idx=0, para_idx=0, run_idx=0,
    new_text="2026年AI最新動向")

# サブタイトルを変更
edit_shape_text(slide_idx=0, shape_idx=1, para_idx=0, run_idx=0,
    new_text="主要AIモデルの比較と展望")

save_edited_pptx("AI_Trends_Updated.pptx")
```

### 複数スライドの色変更

```
load_pptx(artifact_id="abc-123")

# スライド0〜3の背景シェイプの色を統一
for slide_idx in [0, 1, 2, 3]:
    edit_shape_fill(slide_idx=slide_idx, shape_idx=0, r=30, g=39, b=97)

save_edited_pptx("recolored.pptx")
```

### レイアウト調整

```
load_pptx(artifact_id="abc-123")

# シェイプを右に移動して幅を広げる
edit_shape_transform(
    slide_idx=1, shape_idx=3,
    x=914400,     # 1インチ右
    y=1828800,    # 2インチ下
    cx=10363200,  # 幅を広げる
    cy=4114800,   # 高さ
)

save_edited_pptx("adjusted.pptx")
```

---

## 視覚的QA

編集後のスライドを確認するには `render_slide_svg` ツールを使用:

```
render_slide_svg(slide_idx=0)
```

SVGが返されるので、レイアウトや内容を視覚的に検証できます。

---

## 注意事項

- **既存PPTXの編集には必ず pptx-svg ブリッジを使用** してください
- unpack/pack や LibreOffice は使用しません
- PptxGenJS は **新規作成のみ** に使用します
- 編集ツールはシェイプ単位の操作です。スライドの追加・削除・並べ替えには対応していません
- テキスト変更は既存のラン（text run）の内容を置換します。新しい段落やランの追加はできません
