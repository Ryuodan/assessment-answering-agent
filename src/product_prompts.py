"""What a product's questionnaire tells the drafter and the reviewer (plan 031, D-026).

Kept apart from `src.prompts`, which uses `SHARED` and `product_sources_line` to
mark a product's sources, so that the shared prompts read as they did for General.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import Evidence


SHARED = "SHARED"
"""The mark on a source that is not the product's own, in a product's questionnaire (plan 031)."""


PRODUCT_ANSWERING = """

THE PRODUCT THIS QUESTIONNAIRE IS ABOUT
This questionnaire is about {product}, one of our products.{description} Every question in it is about {product}: "the system", "the solution", "the service", "the application" and "you" mean {product} as we provide it.

Each source is marked with what it covers, and the mark decides what it can support:
- FOR {product}: written for {product} itself, from its own documents or from what we answered in its own earlier assessments. Only these support a statement about {product} in particular: where it is hosted and where its data is kept, how it is built, the systems, tools and integrations it uses, its figures and dates, its test results and its configuration.
- SHARED: material that is not about {product} in particular.
  - A shared POLICY is the organisation's, and it binds every product, {product} included. State what it requires as our organisation-wide policy ("Our access control policy requires ...", "Across {short_name}, ..."). Do not present it as a description of how {product} is built, hosted or tested.
  - A shared PREVIOUS ANSWER was given in an earlier assessment, often about another of our products. Use it only for what is true of the whole organisation: its policies, its processes, its certifications. Never take a product-specific fact from it, such as a hosting location, a system or tool name, a figure, a date or a test result, and state it about {product}: it may describe another product.{others}
- When only SHARED sources bear on a question about {product} itself, answer from the organisation's policy, say that it is the policy covering all our products, and say plainly that the {product} documentation available does not state the product-specific detail. Never fill that gap with a detail from another product, and never word an organisation-wide policy as though it were a fact about {product}'s own setup.
- Where a source FOR {product} and a SHARED one disagree, the one FOR {product} applies: it is how this product differs, not a contradiction to report."""
"""Added to the drafter's system prompt for a product's questionnaire (plan 031), and never for General.

Before it, the drafter was told only that some sources were "FOR THIS PRODUCT",
never which product, and nothing about the rest. It wrote the organisation's
shared policies, and earlier answers given about other products, as facts about
the product being assessed (the user's finding, plan 031).
"""

PRODUCT_OTHERS = " Our other products are {names}: a source about one of them describes that product, not {product}."

PRODUCT_REVIEW = """

THIS QUESTIONNAIRE IS ABOUT {product}, one of our products. Each source is marked FOR {product} (written for {product} itself) or SHARED (the organisation's policies, or an earlier answer that may be about another product). Also set `grounded` to false when the answer states something about {product} in particular -- where it is hosted or its data kept, how it is built, a system, tool or integration it uses, a figure, a date, a test result -- that only a SHARED source supports. Every product is bound by the organisation's policies, so an organisation-wide policy stated as the organisation's policy is grounded, and so is saying that it applies to {product} or covers all our products, {product} included; the same requirement stated as a fact about {product}'s own setup is not."""
"""Added to the reviewer's system prompt for a product's questionnaire (plan 031), and never for General."""


def product_answering(product: str, description: str, short_name: str, others: list[str]) -> str:
    """The drafter's product block (plan 031): who the questionnaire is about, and what each mark supports."""
    named = PRODUCT_OTHERS.format(names=", ".join(others), product=product) if others else ""
    told = f" {description.strip()}" if description.strip() else ""
    return PRODUCT_ANSWERING.format(product=product, description=told, short_name=short_name, others=named)


def product_review(product: str) -> str:
    """The reviewer's product block (plan 031)."""
    return PRODUCT_REVIEW.format(product=product)


def product_sources_line(sources: list["Evidence"], product: str) -> str:
    """Which of this question's sources are the product's own, said above them (plan 031).

    Counted rather than left to the marks: told only the rule in the system
    prompt, the drafter still wrote "Ole5 is hosted in Saudi Arabia" from shared
    sources alone, and the reviewer passed it.
    """
    own = [str(index) for index, item in enumerate(sources, start=1) if getattr(item, "product_id", "")]
    if not own:
        return (
            f"None of these sources is FOR {product}: they are all SHARED. They can support what the "
            f"organisation's policy requires of every product, and nothing about {product}'s own hosting, "
            "data location, build, systems, tools, figures, dates or test results."
        )
    which = "Source " + own[0] + " is" if len(own) == 1 else "Sources " + ", ".join(own) + " are"
    return f"{which} FOR {product}; the others are SHARED."
