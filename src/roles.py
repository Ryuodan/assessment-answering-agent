"""The roles a person can have, and what each may do beyond answering.

    member   everything a person needs to answer questionnaires for their team
    lead     a member who also manages the team's products (plan 020)
    admin    manages people, teams and access codes, and any team's products

Stored as the text in `users.role`. One module, so the identity code, the
routes and the pages agree on the names.
"""

from __future__ import annotations

MEMBER = "member"
LEAD = "lead"
ADMIN = "admin"
ROLES = (MEMBER, LEAD, ADMIN)

LABELS = {MEMBER: "Member", LEAD: "Team lead", ADMIN: "Administrator"}
"""How a role is shown on the pages."""


def manages_products(role: str, own_team: str, team: str) -> bool:
    """Whether someone may add, change or delete `team`'s products.

    An administrator may, for any team; a team lead, for their own team only.
    """
    return role == ADMIN or (role == LEAD and own_team == team)
