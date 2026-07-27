from django import template

register = template.Library()


TEAM_ABBREVIATIONS = {
    # Ecuador
    "Barcelona SC": "BSC",
    "Barcelona Sporting Club": "BSC",

    "Club Sport Emelec": "EME",
    "Emelec": "EME",

    "Liga Deportiva Universitaria": "LDU",
    "LDU Quito": "LDU",
    "Liga de Quito": "LDU",

    "Independiente del Valle": "IDV",

    "Universidad Católica": "CATO",
    "Universidad Católica del Ecuador": "CATO",

    "El Nacional": "NAC",
    "CD El Nacional": "NAC",

    "Deportivo Cuenca": "CUE",
    "Club Deportivo Cuenca": "CUE",

    "Aucas": "AUC",
    "Sociedad Deportiva Aucas": "AUC",

    "Mushuc Runa": "MUR",

    "Macará": "MAC",
    "Técnico Universitario": "TEC",

    "Delfín": "DEL",
    "Delfín SC": "DEL",

    "Orense": "ORE",
    "Orense SC": "ORE",

    "Libertad": "LIB",
    "Libertad FC": "LIB",

    "Manta": "MAN",
    "Manta FC": "MAN",
    
    "Leones": "LEO",
    
    "Guayaquil City": "GYE",
}


# Ermöglicht die Erkennung unabhängig von Groß- und Kleinschreibung.
TEAM_ABBREVIATIONS_NORMALIZED = {
    team_name.strip().casefold(): abbreviation
    for team_name, abbreviation in TEAM_ABBREVIATIONS.items()
}


@register.filter(name="team_abbr")
def team_abbr(team_name):
    """
    Gibt die festgelegte Abkürzung eines Vereins zurück.

    Ist ein Verein nicht in der Liste enthalten, werden automatisch
    die ersten drei Buchstaben verwendet.
    """
    if not team_name:
        return "—"

    normalized_name = str(team_name).strip()
    lookup_key = normalized_name.casefold()

    abbreviation = TEAM_ABBREVIATIONS_NORMALIZED.get(
        lookup_key
    )

    if abbreviation:
        return abbreviation

    # Fallback für noch nicht eingetragene Vereine
    return normalized_name[:3].upper()