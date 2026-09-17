"""Canonical lineage receipts for route-independent assurance snapshots."""

from uuid import UUID

from app.models.provenance import LineageEdge


def lineage_payload(edges: list[LineageEdge], child_id: UUID) -> list[dict[str, str]]:
    """Seal every stored relationship, including non-derivation annotations."""
    return sorted(
        [
            {
                "id": str(edge.id),
                "parent_record_id": str(edge.parent_record_id),
                "child_record_id": str(edge.child_record_id),
                "relationship": edge.relationship,
            }
            for edge in edges
            if edge.child_record_id == child_id
        ],
        key=lambda item: (item["parent_record_id"], item["relationship"], item["id"]),
    )
