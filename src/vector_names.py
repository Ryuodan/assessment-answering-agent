"""What the vector store calls things, and how it scores them.

Moved out of `src/knowledge.py` (plan 021), where they had been since teams got
collections of their own; a product's collection is named here too.
"""

from __future__ import annotations

import hashlib
import re

from src.config import settings

_SQRT2 = 2.0**0.5


def cosine_from_relevance(relevance: float, space: str) -> float:
    """Recover the cosine similarity from LangChain's relevance figure.

    The number LangChain hands back is not the similarity it appears to be,
    and the discrepancy is large enough to mislead a reader badly. Chroma's
    `l2` space returns the *squared* euclidean distance, while LangChain's
    `_euclidean_relevance_score_fn` computes `1 - distance / sqrt(2)` on the
    assumption that the distance is an unsquared norm. For the unit-length
    vectors BGE-M3 produces, the squared distance is `2 - 2 * cos`, so what
    comes out is

        reported = 1 - (2 - 2 cos) / sqrt(2) = sqrt(2) * cos - (sqrt(2) - 1)

    — an affine squash of the cosine. Ranking is unaffected, because the
    transform is strictly increasing, and no code in this project ever
    compared a score against a fixed threshold. What it did affect was every
    human reading the number: a chunk matching at cosine 0.72 was displayed as
    0.60, which reads like a poor match rather than a good one. It also dips
    below zero past cosine 0.293, and `order_evidence` seeds its group maximum
    at 0.0, so a negative score would silently collapse into a tie.

    Only the `l2` case needs undoing. A collection created with `cosine` or
    `ip` is already reported as a similarity, and converting again would be a
    second bug on top of the first — hence the space is passed in rather than
    assumed.
    """
    if space != "l2":
        return relevance
    return 1.0 - (1.0 - relevance) * _SQRT2 / 2.0


def collection_for(team_id: str, product_id: str = "") -> str:
    """The Chroma collection a team's knowledge lives in.

    The default team keeps the collection that existed before teams had their
    own, so the corpus already indexed is still its corpus. Any other team gets
    a name derived from its id: readable where the id allows, and always within
    Chroma's rules (3-63 characters, letters, digits, dot, dash and underscore,
    starting and ending with a letter or digit), with a hash so two ids that
    tidy to the same letters cannot share a collection.
    """
    if product_id:
        # A product's own collection (plan 021): the team and the product hashed
        # together, so it fits Chroma's 63 characters whatever the names, and
        # cannot meet a team's collection, whose names never contain "-p-".
        digest = hashlib.sha256(f"{team_id}/{product_id}".encode("utf-8")).hexdigest()[:16]
        return f"{settings.collection_name[:20].rstrip('-_.')}-p-{digest}"
    if team_id == settings.default_team:
        return settings.collection_name
    slug = re.sub(r"[^a-z0-9]+", "-", team_id.lower()).strip("-")[:24] or "team"
    digest = hashlib.sha256(team_id.encode("utf-8")).hexdigest()[:10]
    return f"{settings.collection_name[:20].rstrip('-_.')}-{slug}-{digest}"
