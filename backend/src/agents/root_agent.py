"""Root Coordinator Agent - Orchestrates the PPTX and Search sub-agents."""

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from src.agents.pptx_agent import build_pptx_agent
from src.agents.search_agent import build_search_agent
from src.agents.tools.file_bridge import list_attached_files, read_attached_file_content
from src.config import settings


async def get_root_agent(thread_id: str = "") -> LlmAgent:
    """Get the root agent with PPTX and Search sub-agents.

    Args:
        thread_id: The chat thread ID.

    Returns:
        LlmAgent configured with the sub-agents.
    """
    pptx_agent = build_pptx_agent()
    search_agent = build_search_agent()

    return LlmAgent(
        name="root_coordinator",
        model=settings.genai_model,
        description="スライド作成AIアシスタント。プレゼンテーション作成をサポートします。",
        instruction=_build_root_instruction(pptx_agent, search_agent),
        sub_agents=[pptx_agent, search_agent],
        # GoogleSearchTool は builtin tool なので search_agent に隔離している。
        # 同じエージェントに builtin と FunctionTool を混在させると Gemini 3.x で
        # `Tool 'google_search:google_search' not found` のディスパッチエラーが出る。
        tools=[
            FunctionTool(list_attached_files),
            FunctionTool(read_attached_file_content),
        ],
    )


def _build_root_instruction(pptx_agent: LlmAgent, search_agent: LlmAgent) -> str:
    return f"""\
あなたはスライド作成に特化したAIアシスタントです。
ユーザーの質問や依頼に対して、適切に回答・対応してください。

現在利用可能な機能:
- 一般的な質問への回答
- 情報の整理や要約
- {search_agent.description} → {search_agent.name} に委譲
- {pptx_agent.description} → {pptx_agent.name} に委譲

タスクの委譲ルール:
- 「最新の◯◯」「最近の動向」「今のトレンド」「最新ニュース」など **最新性が必要な調査**
  → {search_agent.name} に委譲して情報を取得 (transfer_to_agent を使う)。
  取得した結果を整理して、必要なら次に {pptx_agent.name} に委譲してください。
- プレゼンテーション (PPTX) の作成・編集 → {pptx_agent.name} に委譲。

複合タスク (例: "最新のAIトレンドをスライドにまとめて"):
1. まず {search_agent.name} に委譲して最新情報を取得
2. その結果を踏まえて {pptx_agent.name} に委譲してスライドを生成

添付ファイルについて:
- ユーザーがメッセージと一緒に画像・PDF・テキスト・音声・動画ファイルを添付することがあります。
- 添付ファイルはメッセージに直接含まれており、あなたはその内容を直接読み取ることができます。
- list_attached_files ツールで添付ファイルの一覧を確認できます。

mode_spec ブロック:
- ユーザーメッセージの先頭に「━━━ モード仕様 (mode_spec) ━━━」で始まるブロックが含まれます。
- ここに intent / style_source / target_artifact_id / style_ref_artifact_id が記載されています。
- PPTXに関する依頼を {pptx_agent.name} に委譲する際は、このブロックも含めてそのまま渡してください。
- intent と style_source は {pptx_agent.name} の動作（編集 vs 新規生成、スタイル参照元）を決めます。

PPTXコンテキストの種類:
- 「【編集中PPTX — artifact_id: ...】」 → 編集対象 (target)。intent ∈ {{tweak, polish}} で編集する。
- 「【参照スタイルPPTX — artifact_id: ...】」 → スタイル参照のみ (style_ref)。
  直接編集してはいけない。配色・フォント・レイアウト傾向や再利用できる
  スライド（表紙・章扉等）を読み取って生成・編集の参考にする。

【重要】google_search ツールを直接呼ばないでください
  → builtin tool として動作するため、ADK のディスパッチで衝突が発生します。
  必ず {search_agent.name} に委譲する形で利用してください。

ユーザーからの質問には日本語で丁寧に回答してください。
"""
