"""What the drafter and the reviewer are told about a product's questionnaire's product (plan 031, D-026).

Moved out of `src.graph.nodes`, which calls these two and is otherwise as it was.
"""

from __future__ import annotations

from src import products
from src.graph.state import QuestionState
from src.product_prompts import product_answering, product_review


def about(state: QuestionState) -> tuple[str, str, list[str]]:
    """The product's name, its description, and the team's other products.

    Empty for General, and for a product the team no longer has: that one's
    questionnaire is kept read-only (plan 027), and its sources keep the mark
    they had before plan 031.
    """
    product_id = state.get("product_id", "")
    listed = products.list_products(state.get("team_id") or "") if product_id else []
    mine = next((product for product in listed if product.id == product_id), None)
    if mine is None:
        return "", "", []
    return mine.name, mine.description, [product.name for product in listed if product.id != product_id]


def for_the_drafter(state: QuestionState, short_name: str) -> tuple[str, str]:
    """The product's name, and what to add to the drafter's system prompt; both "" for General."""
    product, description, others = about(state)
    return product, product_answering(product, description, short_name, others) if product else ""


def for_the_reviewer(state: QuestionState) -> tuple[str, str]:
    """The product's name, and what to add to the reviewer's system prompt; both "" for General."""
    product = about(state)[0]
    return product, product_review(product) if product else ""
