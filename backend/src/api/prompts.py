"""Prompt template generation API endpoint."""

import logging

from fastapi import APIRouter
from google import genai
from google.genai import types
from pydantic import BaseModel

from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])


class MessageItem(BaseModel):
    """A single message in the conversation."""

    role: str
    content: str


class GenerateTemplateRequest(BaseModel):
    """Request body for template generation."""

    messages: list[MessageItem]


class TemplateVariable(BaseModel):
    """A variable placeholder in the template."""

    name: str
    label: str
    description: str
    default_value: str
    type: str = "text"  # "text" or "file"


class GenerateTemplateResponse(BaseModel):
    """Response body for template generation."""

    name: str
    content: str
    variables: list[TemplateVariable]
    summary: str


SYSTEM_PROMPT = """\
あなたはプロンプトテンプレート生成の専門家です。
ユーザーとAIの会話履歴を分析し、その会話の最終的な成果を再現できる
最適化されたシングルショットプロンプトテンプレートを生成してください。

## ルール

1. 会話全体を分析し、ユーザーが最終的に求めた成果物・結果を特定する
2. その成果を一発で再現できるプロンプトを作成する
3. 会話中で変動しうる具体的な値（ファイル名、日付、人名、プロジェクト名など）を
   `{{variable_name}}` 形式のプレースホルダーに置換する
4. 変数名はスネークケース（英語）で、意味が分かりやすいものにする
5. 各変数にはlabel（日本語表示名）、description（入力ヒント）、default_value（デフォルト値）を付与する
6. テンプレート名は日本語で、内容を端的に表すものにする
7. summaryは日本語で、テンプレートの用途を1-2文で説明する

## ファイル添付の扱い

会話中にユーザーがファイルを添付している場合（「[添付ファイル: ...]」表記）:
- ファイルの内容をテンプレート本文の `{{variable}}` に含めないこと
- 代わりに、type="file" の変数として生成すること
- テンプレート本文では「添付されたファイルを参照してください」のように記述する
- ファイル変数はテンプレート本文の `{{}}` には含めず、variables配列にのみ含める

## 変数のtype

- `type: "text"` — テキスト入力変数。テンプレート本文内に `{{variable_name}}` として配置
- `type: "file"` — ファイル添付変数。テンプレート本文には含めず、実行時にファイルを添付

## 出力JSON形式

{
  "name": "テンプレート名",
  "content": "テンプレート本文（テキスト変数のみ {{variable}} を含む）",
  "variables": [
    {
      "name": "variable_name",
      "label": "表示ラベル",
      "description": "この変数の説明・入力ヒント",
      "default_value": "デフォルト値（なければ空文字）",
      "type": "text"
    },
    {
      "name": "file_variable",
      "label": "添付ファイル",
      "description": "添付するファイルの説明",
      "default_value": "",
      "type": "file"
    }
  ],
  "summary": "テンプレートの用途説明"
}
"""


@router.post("/generate-template")
async def generate_template(request: GenerateTemplateRequest) -> GenerateTemplateResponse:
    """Generate a reusable prompt template from conversation history.

    Args:
        request: The conversation messages to analyze.

    Returns:
        Generated template with variables and metadata.
    """
    conversation = "\n".join(
        f"{'ユーザー' if m.role == 'user' else 'AI'}: {m.content}"
        for m in request.messages
    )

    client = genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )

    response = await client.aio.models.generate_content(
        model=settings.genai_model,
        contents=conversation,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=GenerateTemplateResponse,
        ),
    )

    import json

    result = json.loads(response.text)
    return GenerateTemplateResponse(**result)
