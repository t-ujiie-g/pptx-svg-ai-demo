"""File bridge tools - Allow agents to access user-attached files.

ファイルデータはモジュールレベルの dict に保持し、tool_context.session.id で
リクエストを識別する。ファイルはマルチターン（A2UI等）で使い回すため、
ターン終了時にはクリアせず、Pythonプロセス再起動時に自然消滅する。
"""

import base64
import logging
import uuid

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

# モジュールレベルのファイルストア: {session_id: {file_id: file_meta}}
_file_store: dict[str, dict[str, dict]] = {}

# テキスト系MIMEタイプ（UTF-8デコードで返す）
_TEXT_MIME_TYPES = {
    "text/plain",
    "text/html",
    "text/csv",
    "application/json",
    "application/xml",
}

# read_attached_file_content の最大サイズ (1MB)
_MAX_READ_SIZE = 1 * 1024 * 1024


def store_attached_files(files: list[dict]) -> dict[str, dict]:
    """リクエスト解析時にファイルをブリッジ用の形式に変換する。

    LLMから呼ばれるツールではなく、chat.py から直接呼ばれるヘルパー関数。

    Args:
        files: [{file_name, mime_type, data_bytes}] のリスト。
               data_bytes は bytes 型。

    Returns:
        {file_id: {file_name, mime_type, size_bytes, data_base64}} の辞書。
    """
    result: dict[str, dict] = {}
    for f in files:
        file_id = str(uuid.uuid4())[:8]
        data_bytes: bytes = f["data_bytes"]
        result[file_id] = {
            "file_name": f["file_name"],
            "mime_type": f["mime_type"],
            "size_bytes": len(data_bytes),
            "data_base64": base64.b64encode(data_bytes).decode("ascii"),
        }
    return result


def store_generated_file(
    session_id: str,
    file_name: str,
    mime_type: str,
    data_bytes: bytes,
) -> str:
    """生成ファイルを file_store に追加し file_id を返す。

    スライド等のツールが生成したファイルを file_bridge に格納して、
    後続ターンで再利用（修正依頼など）できるようにする。

    Args:
        session_id: ADK セッション ID。
        file_name: ファイル名。
        mime_type: MIME タイプ。
        data_bytes: ファイルのバイトデータ。

    Returns:
        新規発行された file_id。
    """
    file_id = str(uuid.uuid4())[:8]
    meta = {
        "file_name": file_name,
        "mime_type": mime_type,
        "size_bytes": len(data_bytes),
        "data_base64": base64.b64encode(data_bytes).decode("ascii"),
    }
    existing = _file_store.get(session_id, {})
    existing[file_id] = meta
    _file_store[session_id] = existing
    logger.info(
        "Stored generated file '%s' (file_id=%s) for session %s",
        file_name, file_id, session_id,
    )
    return file_id


def set_request_files(session_id: str, files: dict[str, dict]) -> None:
    """セッションにファイルデータを紐付ける（chat.py から呼ばれる）。"""
    _file_store[session_id] = files
    logger.debug(
        "Stored %d attached file(s) for session %s", len(files), session_id
    )


def get_request_files(session_id: str) -> dict[str, dict]:
    """セッションに紐付くファイルデータを取得する。"""
    return _file_store.get(session_id, {})


def list_attached_files(tool_context: ToolContext) -> dict:
    """ユーザーが添付したファイルの一覧を返す（メタデータのみ）。

    Args:
        tool_context: ADK ToolContext。

    Returns:
        {"files": [{file_id, file_name, mime_type, size_bytes}]} 形式の辞書。
        添付ファイルがない場合は空リストを返す。
    """
    session_id = tool_context.session.id
    attached = get_request_files(session_id)
    files = [
        {
            "file_id": file_id,
            "file_name": meta["file_name"],
            "mime_type": meta["mime_type"],
            "size_bytes": meta["size_bytes"],
        }
        for file_id, meta in attached.items()
    ]
    return {"files": files}


def read_attached_file_content(tool_context: ToolContext, file_id: str) -> dict:
    """添付ファイルの内容を返す。

    テキスト系ファイル: UTF-8デコードして文字列で返す。
    バイナリファイル: base64文字列を返す（1MB以下のみ）。

    Args:
        tool_context: ADK ToolContext。
        file_id: list_attached_files で取得したファイルID。

    Returns:
        {"file_name": str, "mime_type": str, "content": str, "encoding": "text"|"base64"}
        または {"error": str}。
    """
    session_id = tool_context.session.id
    file_meta = get_request_files(session_id).get(file_id)
    if not file_meta:
        return {"error": f"ファイルが見つかりません: {file_id}"}

    if file_meta["size_bytes"] > _MAX_READ_SIZE:
        return {
            "error": f"ファイルサイズが上限(1MB)を超えています: "
            f"{file_meta['file_name']} ({file_meta['size_bytes']} bytes)"
        }

    data_base64: str = file_meta["data_base64"]
    mime_type: str = file_meta["mime_type"]

    if mime_type in _TEXT_MIME_TYPES:
        try:
            text_content = base64.b64decode(data_base64).decode("utf-8")
            return {
                "file_name": file_meta["file_name"],
                "mime_type": mime_type,
                "content": text_content,
                "encoding": "text",
            }
        except UnicodeDecodeError:
            logger.warning(
                "Failed to decode %s as UTF-8, falling back to base64",
                file_meta["file_name"],
            )

    return {
        "file_name": file_meta["file_name"],
        "mime_type": mime_type,
        "content": data_base64,
        "encoding": "base64",
    }
