"""
Diagnostic léger d'un besoin client exprimé en langage naturel.

Ceci n'est pas un système d'IA générative : c'est une couche de mise en
forme, au-dessus de l'interprétation déjà réalisée par
apps.services.nlp.interpreter_requete (reconnaissance de motifs contre
le catalogue réel, aucun modèle de langage entraîné). Ce module ne
duplique jamais cette logique : il l'appelle et l'habille dans le
contrat de données structuré utilisé par le reste du module admin
(voir apps.disputes.services et apps.verification.services pour le
même contrat "status/confidence/findings/warnings/requires_human_review").

Ce diagnostic n'affirme jamais un problème technique précis (voir la
mise en garde de sécurité ci-dessous, section 20 du cahier des
charges) : il aide seulement à identifier le type de professionnel à
contacter, à partir des mêmes catégories/services/compétences déjà
utilisés par RechercheIntelligenteView.
"""

# Permet d'utiliser les annotations de type modernes même sur d'anciennes versions de Python.
from __future__ import annotations

# On importe la fonction d'interprétation déjà existante et validée.
from apps.services.nlp import interpreter_requete

# Le message de mise en garde systématiquement renvoyé : ce diagnostic
# oriente vers un métier, il ne remplace jamais un avis technique.
AVERTISSEMENT_SECURITE = (
    "Ce diagnostic aide seulement à identifier le type de professionnel "
    "à contacter. Il ne constitue pas un diagnostic technique définitif : "
    "seul un professionnel qualifié peut évaluer précisément la situation."
)


# Cette fonction construit un diagnostic structuré à partir d'une description en langage naturel.
def diagnostiquer(texte: str) -> dict:
    """
    Diagnostic structuré d'une description client, jamais un verdict
    technique. `requires_human_review` est toujours True : le
    professionnel contacté reste seul juge de la situation réelle.
    """

    interpretation = interpreter_requete(texte)

    findings = []
    if interpretation["categorie"]:
        findings.append(f"Domaine identifié : {interpretation['categorie']}.")
    if interpretation["service"]:
        findings.append(f"Type de besoin identifié : {interpretation['service']}.")
    if interpretation["competence"]:
        findings.append(f"Compétence recommandée : {interpretation['competence']}.")

    criticite = "Élevée" if interpretation["urgence"] else "Normale"
    findings.append(f"Criticité estimée : {criticite}.")

    warnings = [AVERTISSEMENT_SECURITE]
    identifie = bool(interpretation["categorie"] or interpretation["service"] or interpretation["competence"])
    if not identifie:
        warnings.append(
            "Aucun domaine ou service précis n'a pu être identifié à partir de cette description."
        )

    # Confiance = proportion de champs métier réellement identifiés,
    # jamais une probabilité de diagnostic médical/technique correct.
    champs_cles = ("categorie", "service", "competence")
    confidence = round(
        sum(1 for champ in champs_cles if interpretation[champ]) / len(champs_cles),
        2,
    )

    return {
        "status": "identifie" if identifie else "non_identifie",
        "confidence": confidence,
        "criticite": criticite,
        "domaine": interpretation["categorie"],
        "service_recommande": interpretation["service"],
        "competence_recommandee": interpretation["competence"],
        "findings": findings,
        "warnings": warnings,
        "requires_human_review": True,
    }
