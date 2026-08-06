from typing import Any


def group_page_classifications(
    page_classifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(
        page_classifications,
        key=lambda item: item.get("page_number") or 0,
    )
    groups: list[dict[str, Any]] = []

    for classification in ordered:
        page_number = classification.get("page_number")
        document_type = classification.get("document_type")
        if not isinstance(page_number, int) or not document_type:
            continue

        confidence = classification.get("confidence")
        reason = classification.get("reason")
        current_group = groups[-1] if groups else None

        if (
            current_group
            and current_group["document_type"] == document_type
            and current_group["end_page"] == page_number - 1
        ):
            current_group["pages"].append(page_number)
            current_group["end_page"] = page_number
            current_group["confidence"] = min(
                current_group["confidence"],
                confidence if isinstance(confidence, (int, float)) else 0,
            )
            if reason:
                current_group["reasons"].append(reason)
            continue

        groups.append(
            {
                "document_type": document_type,
                "start_page": page_number,
                "end_page": page_number,
                "pages": [page_number],
                "confidence": confidence if isinstance(confidence, (int, float)) else 0,
                "reasons": [reason] if reason else [],
            }
        )

    return groups

