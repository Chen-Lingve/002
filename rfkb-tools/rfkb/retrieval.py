"""Bounded literal search alternatives for the local engineering vocabulary."""
import re
import unicodedata
from itertools import product


ALIASES = (("图纸审阅", "图纸审查"), ("焊锡丝", "焊丝"), ("三维建模", "3D建模", "3D 建模"))
TERM = re.compile("|".join(re.escape(term) for group in ALIASES for term in group), re.IGNORECASE)
ALTERNATIVES = {term.casefold(): group for group in ALIASES for term in group}
MODEL = re.compile(r"\b(SMPM|MMCX|SMA|MCX|BNC|SMP)[ _‐‑–—−-]+(?=[A-Z0-9]*[0-9])", re.I)
FAMILY_DELIMITER = re.compile(r"[/,;、]+")


def query_variants(query):
    query = query.strip()
    terms = TERM.split(query)
    matches = list(TERM.finditer(query))
    # Bound alias expansion for bulk or adversarial search strings.
    alias_variants = [query]
    if 0 < len(matches) <= 3:
        alias_variants.extend("".join(part + alias for part, alias in zip(terms, (*choices, "")))
                              for choices in product(*(ALTERNATIVES[m[0].casefold()] for m in matches)))
    variants = dict.fromkeys(alias_variants)
    for value in alias_variants:
        normalized = unicodedata.normalize("NFKC", value)
        if not MODEL.search(normalized):
            continue
        for separator in ("-", " ", "_", "－", "‐", "‑", "–", "—", "−"):
            variants[MODEL.sub(lambda match: match[1] + separator, normalized)] = None
    return list(variants)


def family_matches(stored, query):
    def normalize(value):
        return unicodedata.normalize("NFKC", value).strip().casefold()

    stored, query = normalize(stored), normalize(query)
    return bool(query) and (query == stored or query in
                            {item.strip() for item in FAMILY_DELIMITER.split(stored)})
