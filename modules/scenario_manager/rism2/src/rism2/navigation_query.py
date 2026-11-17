"""
Actions コレクションを直接参照するためのヘルパー（navigation の検索、動作の状態）

pyindy の ActionManager は col / robot_name、ローカルの ActionManager は
collection / actor を持つため、両方に対応する。
"""
from typing import Any, Dict, Iterable, Optional, Tuple

from pymongo.collection import Collection

# v1.0 は command、v2.0 は name フィールドにアクション種別が入る
NAVIGATION_COMMAND_FILTER = {"$or": [{"command": "navigation"}, {"name": "navigation"}]}


def get_collection_and_actor(manager: Any) -> Tuple[Optional[Any], Optional[str]]:
    """
    マネージャーから Actions コレクションとアクター名を取得

    Args:
        manager: pyindy またはローカルの ActionManager

    Returns:
        (collection, actor)。取得できない場合は None を含む
    """
    if manager is None:
        return None, None
    # pymongo の Collection は真偽値評価できないため is None で判定する
    collection = getattr(manager, "collection", None)
    if collection is None:
        collection = getattr(manager, "col", None)
    actor = getattr(manager, "actor", None)
    if actor is None:
        actor = getattr(manager, "robot_name", None)
    return collection, actor


def get_action_status(manager: Any, action_id: Any) -> Any:
    """
    動作の状態（status）。ないときは pyindy と同じく "unknown entry_id"

    pyindy の get_status は件数を数えてから読むので2回問い合わせる。完了待ちでは 0.1 秒ごとに呼ぶので、
    状態だけを1回で読む。MongoDB のコレクションを持たないマネージャー（テストの代わりなど）は get_status を使う。
    """
    collection, _ = get_collection_and_actor(manager)
    if not isinstance(collection, Collection):
        return manager.get_status(action_id)
    doc = collection.find_one({"_id": action_id}, {"status": 1})
    return doc.get("status") if doc else "unknown entry_id"


def navigation_query(actor: str, statuses: Iterable[str]) -> Dict[str, Any]:
    """
    指定アクター・ステータスの navigation アクションを検索するクエリを作成

    Args:
        actor: アクター名
        statuses: 対象ステータス（例: ["is_playing", "waiting"]）

    Returns:
        MongoDB クエリ
    """
    return {"actor": actor, "status": {"$in": list(statuses)}, **NAVIGATION_COMMAND_FILTER}
