"""Domain adapter registry. Add a domain = add one module and list it here."""
from __future__ import annotations

from .adapters import accessibility, cybersecurity, education, environment, finance, forensics, healthcare, public_safety, smart_city
from .base import DomainAdapter

_ADAPTERS: dict[str, DomainAdapter] = {
    m.ADAPTER.id: m.ADAPTER
    for m in (cybersecurity, forensics, smart_city, healthcare, education, finance, public_safety, environment, accessibility)
}
DEFAULT_DOMAIN = "cybersecurity"


def get_domain(domain_id: str) -> DomainAdapter | None:
    return _ADAPTERS.get(domain_id)


def all_domains() -> list[DomainAdapter]:
    return list(_ADAPTERS.values())
