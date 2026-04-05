---
name: pptx
description: "Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even if the extracted content will be used elsewhere, like in an email or summary); editing, modifying, or updating existing presentations; combining or splitting slide files; working with templates, layouts, speaker notes, or comments. Trigger whenever the user mentions \"deck,\" \"slides,\" \"presentation,\" or references a .pptx filename, regardless of what they plan to do with the content afterward. If a .pptx file needs to be opened, created, or touched, use this skill."
license: Proprietary. LICENSE.txt has complete terms
---

# PPTX Skill

## Quick Reference

| Task | Method |
|------|--------|
| Read/analyze content | ユーザーメッセージの PNG + 構造情報 を直接見る |
| Edit existing PPTX | `run_skill_script(skill_name="pptx", script_path="scripts/edit_pptx.py", ...)` — [editing.md](references/editing.md) |
| Create from scratch | `run_skill_script(skill_name="pptx", script_path="scripts/generate_pptx.py", ...)` — [pptxgenjs.md](references/pptxgenjs.md) |

---

## 重要: 編集 vs 新規作成の判断

### 既存PPTXの編集（artifact_id がある場合）

ユーザーのメッセージに `artifact_id` が含まれている場合、**必ず edit_pptx.py を使用**:

ユーザーメッセージには各スライドの PNG 画像と全シェイプの構造情報
（テキスト・位置・色）が最初から含まれています。

1. PNG と構造情報を見て、何を変える・追加すべきか判断
2. `run_skill_script` 経由で `scripts/edit_pptx.py` を実行し、ops をまとめて適用

**「編集」には次がすべて含まれます:**
- 既存シェイプのテキスト・色・位置サイズ変更
- 新しい情報を調べてスライドを追加（`duplicate_slide` + text ops）
- スライドの複製・削除・並べ替え

**⚠️ artifact_id がある場合に generate_pptx.py で新規作成してはいけません。** ユーザーの編集内容が失われます。

### 新規作成（artifact_id がない場合）

テンプレートや既存ファイルがない場合のみ generate_pptx.py を使用。

---

## Reading Content

ユーザーメッセージに添付された **各スライドの PNG 画像** と **シェイプ構造 JSON**
が最優先の情報源です。ユーザーがローカルで編集した直後でも、サーバー側の最新
artifact が自動的に解析されて添付されます。

---

## Editing Workflow (python-pptx)

**Read [references/editing.md](references/editing.md) for full details.**

`edit_pptx.py` に ops を JSON 文字列で渡すだけで一括編集:
- テキスト変更: `{"type":"text", "slide":..., "shape":..., "para":..., "run":..., "text":"..."}`
- 色変更: `{"type":"fill", "slide":..., "shape":..., "r":..., "g":..., "b":...}`
- 位置/サイズ変更: `{"type":"transform", "slide":..., "shape":..., "x":..., "y":..., "cx":..., "cy":..., "rot":...}`
- **スライド複製**: `{"type":"duplicate_slide", "source":..., "insert_after":...}`
- スライド削除: `{"type":"delete_slide", "slide":...}`

---

## Creating from Scratch

**Read [references/pptxgenjs.md](references/pptxgenjs.md) for full details.**

`scripts/generate_pptx.py` に PptxGenJS の JavaScript コードを `code` 引数として渡すと、
Node.js で実行して PPTX を生成し、アーティファクトストアに保存します。

```python
run_skill_script(
    skill_name="pptx",
    script_path="scripts/generate_pptx.py",
    script_args={
        "code": "(async () => { const pptxgen = require('pptxgenjs'); ... })();",
        "output_filename": "deck.pptx",
    },
)
```

要件:
- JS 全体を `(async () => { ... })();` で包む
- 出力は `await pres.writeFile({ fileName: process.env.PPTX_OUTPUT_PATH })`
- pptxgenjs, react, react-dom, react-icons, sharp はグローバルインストール済み

Use when no template or reference presentation is available.

---

## Design Ideas

**Don't create boring slides.** Plain bullets on a white background won't impress anyone. Consider ideas from this list for each slide.

### Before Starting

- **Pick a bold, content-informed color palette**: The palette should feel designed for THIS topic. If swapping your colors into a completely different presentation would still "work," you haven't made specific enough choices.
- **Dominance over equality**: One color should dominate (60-70% visual weight), with 1-2 supporting tones and one sharp accent. Never give all colors equal weight.
- **Dark/light contrast**: Dark backgrounds for title + conclusion slides, light for content ("sandwich" structure). Or commit to dark throughout for a premium feel.
- **Commit to a visual motif**: Pick ONE distinctive element and repeat it — rounded image frames, icons in colored circles, thick single-side borders. Carry it across every slide.

### Color Palettes

Choose colors that match your topic — don't default to generic blue. Use these palettes as inspiration:

| Theme | Primary | Secondary | Accent |
|-------|---------|-----------|--------|
| **Midnight Executive** | `1E2761` (navy) | `CADCFC` (ice blue) | `FFFFFF` (white) |
| **Forest & Moss** | `2C5F2D` (forest) | `97BC62` (moss) | `F5F5F5` (cream) |
| **Coral Energy** | `F96167` (coral) | `F9E795` (gold) | `2F3C7E` (navy) |
| **Warm Terracotta** | `B85042` (terracotta) | `E7E8D1` (sand) | `A7BEAE` (sage) |
| **Ocean Gradient** | `065A82` (deep blue) | `1C7293` (teal) | `21295C` (midnight) |
| **Charcoal Minimal** | `36454F` (charcoal) | `F2F2F2` (off-white) | `212121` (black) |
| **Teal Trust** | `028090` (teal) | `00A896` (seafoam) | `02C39A` (mint) |
| **Berry & Cream** | `6D2E46` (berry) | `A26769` (dusty rose) | `ECE2D0` (cream) |
| **Sage Calm** | `84B59F` (sage) | `69A297` (eucalyptus) | `50808E` (slate) |
| **Cherry Bold** | `990011` (cherry) | `FCF6F5` (off-white) | `2F3C7E` (navy) |

### For Each Slide

**Every slide needs a visual element** — image, chart, icon, or shape. Text-only slides are forgettable.

**Layout options:**
- Two-column (text left, illustration on right)
- Icon + text rows (icon in colored circle, bold header, description below)
- 2x2 or 2x3 grid (image on one side, grid of content blocks on other)
- Half-bleed image (full left or right side) with content overlay

**Data display:**
- Large stat callouts (big numbers 60-72pt with small labels below)
- Comparison columns (before/after, pros/cons, side-by-side options)
- Timeline or process flow (numbered steps, arrows)

**Visual polish:**
- Icons in small colored circles next to section headers
- Italic accent text for key stats or taglines

### Typography

**Choose an interesting font pairing** — don't default to Arial. Pick a header font with personality and pair it with a clean body font.

| Header Font | Body Font |
|-------------|-----------|
| Georgia | Calibri |
| Arial Black | Arial |
| Calibri | Calibri Light |
| Cambria | Calibri |
| Trebuchet MS | Calibri |
| Impact | Arial |
| Palatino | Garamond |
| Consolas | Calibri |

| Element | Size |
|---------|------|
| Slide title | 36-44pt bold |
| Section header | 20-24pt bold |
| Body text | 14-16pt |
| Captions | 10-12pt muted |

### Spacing

- 0.5" minimum margins
- 0.3-0.5" between content blocks
- Leave breathing room—don't fill every inch

### Avoid (Common Mistakes)

- **Don't repeat the same layout** — vary columns, cards, and callouts across slides
- **Don't center body text** — left-align paragraphs and lists; center only titles
- **Don't skimp on size contrast** — titles need 36pt+ to stand out from 14-16pt body
- **Don't default to blue** — pick colors that reflect the specific topic
- **Don't mix spacing randomly** — choose 0.3" or 0.5" gaps and use consistently
- **Don't style one slide and leave the rest plain** — commit fully or keep it simple throughout
- **Don't create text-only slides** — add images, icons, charts, or visual elements; avoid plain title + bullets
- **Don't forget text box padding** — when aligning lines or shapes with text edges, set `margin: 0` on the text box or offset the shape to account for padding
- **Don't use low-contrast elements** — icons AND text need strong contrast against the background; avoid light text on light backgrounds or dark text on dark backgrounds
- **NEVER use accent lines under titles** — these are a hallmark of AI-generated slides; use whitespace or background color instead

---

## QA (Required)

**Assume there are problems. Your job is to find them.**

### Content QA

ユーザーメッセージの PNG 画像と構造情報で大部分の QA は完了します。
編集後は次のターンで最新 PNG が自動的に再添付されます（サーバーが artifact を再解析）。

Check for missing content, typos, wrong order.

### Visual QA

edit_pptx.py の stdout に含まれる `applied` で各 op の成否を確認。
視覚的な最終確認は次のターンで（ユーザーの再依頼時に最新 PNG が添付されます）。

Look for:
- Overlapping elements (text through shapes)
- Text overflow or cut off at edges
- Elements too close or unevenly spaced
- Low-contrast text or icons
- Leftover placeholder content

### Verification Loop

1. PNG + 構造を見て問題を特定
2. **List issues found** (if none found, look again more critically)
3. `edit_pptx.py` で ops をまとめて適用
4. stdout の `applied` で成否確認
5. 失敗があれば修正して再実行

---

## Dependencies

- `python-pptx` (Python) — PPTX 編集（テキスト/色/位置/スライド追加・削除）
- `pptx-svg` (npm, グローバルインストール済み) — PNGレンダリング（サーバー側・フロント側）
- `jsdom` (npm) — SVG解析（inspect 用）
- `pptxgenjs` (npm, グローバルインストール済み) — 新規作成用
- `react`, `react-dom`, `react-icons`, `sharp` (npm) — アイコン生成用
