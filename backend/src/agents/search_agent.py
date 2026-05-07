"""Dedicated search sub-agent that wraps Gemini's built-in Google Search.

GoogleSearchTool is a Gemini-side **built-in** tool — when invoked, the
model handles the search internally rather than ADK dispatching a Python
function. With Gemini 3.x, mixing this built-in tool with regular
FunctionTools on the same agent breaks the dispatch ("Tool 'google_search:
google_search' not found"), so we isolate it on a sub-agent that has *only*
this tool. The root agent delegates web-search queries to this agent.
"""

from google.adk.agents import LlmAgent
from google.adk.tools.google_search_tool import GoogleSearchTool

from src.config import settings


def build_search_agent() -> LlmAgent:
    return LlmAgent(
        name="search_agent",
        model=settings.genai_model,  # root と同じ tier (mid 推奨)
        description=(
            "Google検索によるウェブからの最新情報取得を担当。"
            "ニュース・時事情報・技術トレンド・統計など最新性が必要な調査に使う。"
        ),
        instruction=_SEARCH_AGENT_INSTRUCTION,
        # 重要: builtin GoogleSearchTool 単独。他の FunctionTool と混在させると
        # Gemini 3 の builtin-tool 呼び出しが ADK 関数ディスパッチと衝突する。
        tools=[GoogleSearchTool()],
    )


_SEARCH_AGENT_INSTRUCTION = """\
あなたは Google 検索の専門エージェントです。

役割:
- 渡された調査クエリに対して google_search を実行
- 結果を整理して、出典付きの簡潔な日本語まとめを返す

出力ルール:
- 箇条書きで主要ファクト 3〜10 個
- 各項目に出典 (URL or サイト名) を [1] [2] のように番号付与
- 末尾に「出典」セクションで [1] URL の形でリスト化
- 長文の引用は禁止 (要約のみ)
- 不確実 / 情報不足の場合はその旨を明示

PPTX生成・編集には関与しない (それは pptx_agent の責務)。
"""
