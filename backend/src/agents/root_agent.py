"""Root Coordinator Agent - Orchestrates the PPTX sub-agent."""

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.tools.google_search_tool import GoogleSearchTool

from src.agents.pptx_agent import build_pptx_agent
from src.agents.tools.file_bridge import list_attached_files, read_attached_file_content
from src.config import settings


async def get_root_agent(thread_id: str = "") -> LlmAgent:
    """Get the root agent with the PPTX sub-agent.

    Args:
        thread_id: The chat thread ID.

    Returns:
        LlmAgent configured with the PPTX sub-agent.
    """
    pptx_agent = build_pptx_agent()

    return LlmAgent(
        name="root_coordinator",
        model=settings.genai_model,
        description="スライド作成AIアシスタント。プレゼンテーション作成をサポートします。",
        instruction=_build_root_instruction(pptx_agent),
        sub_agents=[pptx_agent],
        tools=[
            GoogleSearchTool(bypass_multi_tools_limit=True),
            FunctionTool(list_attached_files),
            FunctionTool(read_attached_file_content),
        ],
    )


def _build_root_instruction(pptx_agent: LlmAgent) -> str:
    return f"""\
あなたはスライド作成に特化したAIアシスタントです。
ユーザーの質問や依頼に対して、適切に回答・対応してください。

現在利用可能な機能:
- 一般的な質問への回答
- 情報の整理や要約
- Google検索によるウェブからの最新情報取得（google_search ツールを使用）
- {pptx_agent.description} → {pptx_agent.name} に委譲

タスクの委譲:
- プレゼンテーション（PPTX）の作成・編集に関連する依頼は {pptx_agent.name} に委譲してください。

添付ファイルについて:
- ユーザーがメッセージと一緒に画像・PDF・テキスト・音声・動画ファイルを添付することがあります。
- 添付ファイルはメッセージに直接含まれており、あなたはその内容を直接読み取ることができます。
- list_attached_files ツールで添付ファイルの一覧を確認できます。

Google検索について:
- 最新のニュース、時事情報、技術情報などを求められた場合は google_search ツールを使用してください。
- 検索結果に基づいて回答する場合は、情報の出典を明示してください。

ユーザーからの質問には日本語で丁寧に回答してください。
"""
