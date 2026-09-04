from types import SimpleNamespace
from uuid import uuid4

from stormcloud.pipeline import _distinct_graph_peers


def test_graph_peers_exclude_self_and_duplicate_subjects() -> None:
    source_id = uuid4()
    peer_id = uuid4()
    other_id = uuid4()
    self_embedding = SimpleNamespace(subject_id=source_id, marker="self")
    newest_peer = SimpleNamespace(subject_id=peer_id, marker="newest")
    older_peer = SimpleNamespace(subject_id=peer_id, marker="older")
    other_peer = SimpleNamespace(subject_id=other_id, marker="other")

    result = _distinct_graph_peers(
        source_id,
        [self_embedding, newest_peer, older_peer, other_peer],
    )

    assert [peer.marker for peer in result] == ["newest", "other"]
    assert all(peer.subject_id != source_id for peer in result)

