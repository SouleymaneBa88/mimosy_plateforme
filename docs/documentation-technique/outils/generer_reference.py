"""
Génère la partie « référence » de la documentation technique DIRECTEMENT
depuis le code de MIMOSY, pour qu'elle ne puisse jamais inventer une table,
un champ, une relation ou un endpoint :

    - 05-modeles-reference.md      : chaque modèle Django (registre _meta)
    - 08-api-reference.md          : chaque route (résolveur d'URL Django)
    - diagrammes/classes-complet.mmd et diagrammes/domaine-*.mmd : Mermaid

Lancement, depuis back_Mimosy/ :
    ./venv/bin/python docs/documentation-technique/outils/generer_reference.py

Le script ne modifie ni la base ni le code : il lit la structure déclarée.
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]  # back_Mimosy/
sys.path.insert(0, str(RACINE))
sys.argv = ["manage.py", "shell"]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import models  # noqa: E402
from django.db.models import NOT_PROVIDED  # noqa: E402
from django.urls import URLPattern, URLResolver, get_resolver  # noqa: E402

DOSSIER = Path(__file__).resolve().parents[1]
DIAGRAMMES = DOSSIER / "diagrammes"


# ─── Modèles ────────────────────────────────────────────────────────────────

def modeles_mimosy():
    return [
        m for app in apps.get_app_configs() if app.name.startswith("apps.")
        for m in app.get_models()
    ]


def champs_concrets(modele):
    """Champs réellement stockés (colonnes) ou relations déclarées sur ce modèle."""
    return [f for f in modele._meta.get_fields() if not (f.auto_created and not f.concrete)]


def valeur_defaut(champ):
    if champ.default is NOT_PROVIDED:
        return ""
    d = champ.default
    if callable(d):
        return f"`{getattr(d, '__name__', 'fonction')}()`"
    return f"`{d!r}`"


def cardinalite(champ):
    """Cardinalité vue depuis le modèle qui porte le champ."""
    if isinstance(champ, models.OneToOneField):
        return "1 ↔ 0..1" if not champ.null else "0..1 ↔ 0..1"
    if isinstance(champ, models.ForeignKey):
        return "N → 1" if not champ.null else "N → 0..1"
    if isinstance(champ, models.ManyToManyField):
        return "N ↔ N"
    return ""


def texte_contrainte(c):
    nom = getattr(c, "name", "")
    champs = ", ".join(getattr(c, "fields", ()) or [])
    condition = getattr(c, "condition", None)
    genre = type(c).__name__
    morceaux = [f"`{nom}`", genre]
    if champs:
        morceaux.append(f"champs : {champs}")
    if condition is not None:
        morceaux.append(f"condition : `{condition}`")
    return " — ".join(morceaux)


def generer_modeles(liste):
    lignes = [
        "# 05 — Modèles et base de données (référence générée depuis le code)",
        "",
        "> Généré par `outils/generer_reference.py` à partir du registre des modèles",
        "> Django (`Model._meta`). Aucune ligne n'est écrite à la main : si un champ",
        "> n'apparaît pas ici, il n'existe pas dans le code.",
        "",
        f"**{len(liste)} modèles** répartis dans **{len({m._meta.app_label for m in liste})} applications**.",
        "",
        "| Application | Modèle | Table PostgreSQL | Champs |",
        "|---|---|---|---|",
    ]
    for m in liste:
        lignes.append(f"| `{m._meta.app_label}` | [`{m.__name__}`](#{m.__name__.lower()}) | `{m._meta.db_table}` | {len(champs_concrets(m))} |")
    lignes.append("")

    for m in liste:
        meta = m._meta
        doc = (m.__doc__ or "").strip().split("\n")[0]
        if doc.startswith(m.__name__ + "("):  # docstring automatique de Django
            doc = ""
        fichier = Path(sys.modules[m.__module__].__file__).relative_to(RACINE)
        lignes += [
            f"## {m.__name__}",
            "",
            f"- **Application** : `{meta.app_label}` — fichier `{fichier}`",
            f"- **Table PostgreSQL** : `{meta.db_table}`",
            f"- **Hérite de** : {', '.join('`' + b.__name__ + '`' for b in m.__bases__)}"
            + (" (modèle utilisateur personnalisé, `AUTH_USER_MODEL`)" if m.__name__ == "User" else ""),
        ]
        if doc:
            lignes.append(f"- **Rôle (docstring)** : {doc}")
        if meta.ordering:
            lignes.append(f"- **Tri par défaut** : {', '.join('`' + o + '`' for o in meta.ordering)}")
        for c in meta.constraints:
            lignes.append(f"- **Contrainte** : {texte_contrainte(c)}")
        for i in meta.indexes:
            lignes.append(f"- **Index** : `{i.name}` sur ({', '.join(i.fields)})")
        lignes += ["", "| Champ | Type | null | blank | défaut | unique / index | choix / précisions |", "|---|---|---|---|---|---|---|"]
        for f in champs_concrets(m):
            if f.is_relation:
                continue
            precisions = []
            if f.choices:
                precisions.append(" / ".join(f"`{k}`" for k, _ in f.choices))
            if getattr(f, "max_length", None):
                precisions.append(f"max {f.max_length}")
            if getattr(f, "max_digits", None):
                precisions.append(f"{f.max_digits} chiffres, {f.decimal_places} décimales")
            if getattr(f, "auto_now_add", False):
                precisions.append("rempli à la création")
            if getattr(f, "auto_now", False):
                precisions.append("mis à jour à chaque enregistrement")
            if getattr(f, "upload_to", None):
                cible = f.upload_to if isinstance(f.upload_to, str) else f.upload_to.__name__ + "()"
                precisions.append(f"fichier → `{cible}`")
            unique = "clé primaire" if f.primary_key else ("unique" if f.unique else ("index" if f.db_index else ""))
            lignes.append(
                f"| `{f.name}` | {type(f).__name__} | {'oui' if f.null else 'non'} | {'oui' if f.blank else 'non'} "
                f"| {valeur_defaut(f)} | {unique} | {'; '.join(precisions)} |"
            )
        relations = [f for f in champs_concrets(m) if f.is_relation]
        if relations:
            lignes += ["", "**Relations**", "", "| Champ | Type | Vers | Cardinalité | on_delete | related_name | null |", "|---|---|---|---|---|---|---|"]
            for f in relations:
                rel = f.remote_field
                on_delete = getattr(getattr(rel, "on_delete", None), "__name__", "—")
                cible = f.related_model
                through = ""
                if isinstance(f, models.ManyToManyField):
                    t = rel.through
                    through = f" (table intermédiaire automatique `{t._meta.db_table}`)" if t._meta.auto_created else f" (through `{t.__name__}`)"
                lignes.append(
                    f"| `{f.name}` | {type(f).__name__}{through} | `{cible._meta.app_label}.{cible.__name__}` | {cardinalite(f)} "
                    f"| {on_delete} | `{rel.related_name or '(défaut)'}` | {'oui' if f.null else 'non'} |"
                )
        inverses = [f for f in meta.get_fields() if f.auto_created and not f.concrete and f.related_model and f.related_model._meta.app_label != "auth"]
        if inverses:
            lignes += ["", "**Relations inverses** (déclarées sur d'autres modèles) : " + ", ".join(
                f"`{f.get_accessor_name()}` ← `{f.related_model.__name__}.{f.field.name}`" for f in inverses)]
        methodes = [n for n, v in vars(m).items() if callable(v) and not n.startswith("_") and n not in ("Meta",) and not isinstance(v, type)]
        proprietes = [n for n, v in vars(m).items() if isinstance(v, property)]
        if methodes or proprietes:
            lignes += ["", "**Méthodes / propriétés propres** : " + ", ".join(f"`{n}()`" for n in methodes) + (", " if methodes and proprietes else "") + ", ".join(f"`{n}` (propriété)" for n in proprietes)]
        if "__str__" in vars(m):
            lignes.append("")
            lignes.append("`__str__()` redéfini (affichage lisible dans l'admin Django).")
        lignes.append("")
    (DOSSIER / "05-modeles-reference.md").write_text("\n".join(lignes), encoding="utf-8")
    return sum(1 for m in liste for f in champs_concrets(m) if f.is_relation)


# ─── Diagrammes de classes Mermaid ──────────────────────────────────────────

TYPES_COURTS = {
    "CharField": "str", "TextField": "text", "EmailField": "email", "BooleanField": "bool",
    "DecimalField": "decimal", "IntegerField": "int", "PositiveIntegerField": "int",
    "PositiveSmallIntegerField": "int", "FloatField": "float", "DateTimeField": "datetime",
    "DateField": "date", "TimeField": "time", "UUIDField": "uuid", "BigAutoField": "int",
    "FileField": "file", "ImageField": "image", "JSONField": "json", "SlugField": "slug",
    "URLField": "url",
}


def attributs(m, limite=None):
    champs = [f for f in champs_concrets(m) if not f.is_relation]
    if limite:
        champs = champs[:limite]
    return [f"    +{TYPES_COURTS.get(type(f).__name__, type(f).__name__)} {f.name}" for f in champs]


def relations_mermaid(m, inclure):
    lignes = []
    for f in champs_concrets(m):
        if not f.is_relation or f.related_model.__name__ not in inclure or f.related_model._meta.app_label == "auth":
            continue
        cible = f.related_model.__name__
        if isinstance(f, models.ManyToManyField):
            lignes.append(f'{m.__name__} "0..*" -- "0..*" {cible} : {f.name}')
        elif isinstance(f, models.OneToOneField):
            lignes.append(f'{m.__name__} "0..1" --> "{"0..1" if f.null else "1"}" {cible} : {f.name}')
        else:
            lignes.append(f'{m.__name__} "0..*" --> "{"0..1" if f.null else "1"}" {cible} : {f.name}')
    return lignes


def diagramme(titre, modeles_complets, references=(), limite=None):
    noms = {m.__name__ for m in modeles_complets} | {m.__name__ for m in references}
    lignes = ["---", f"title: {titre}", "---", "classDiagram", "    direction LR"]
    for m in modeles_complets:
        lignes.append(f"    class {m.__name__} {{")
        if m.__name__ == "User":
            lignes.append("        <<AUTH_USER_MODEL>>")
        lignes += ["    " + a for a in attributs(m, limite)]
        lignes.append("    }")
    for m in references:
        lignes.append(f"    class {m.__name__} {{\n        <<autre domaine>>\n    }}")
    if any(m.__name__ == "User" for m in modeles_complets):
        lignes.append("    class AbstractUser {\n        <<Django>>\n    }")
        lignes.append("    AbstractUser <|-- User")
    for m in modeles_complets:
        lignes += ["    " + r for r in relations_mermaid(m, noms)]
    return "\n".join(lignes) + "\n"


def generer_diagrammes(liste):
    par_nom = {m.__name__: m for m in liste}
    DIAGRAMMES.mkdir(exist_ok=True)
    (DIAGRAMMES / "classes-complet.mmd").write_text(
        diagramme("MIMOSY — modèles Django (complet, généré depuis le code)", liste), encoding="utf-8")

    domaines = {
        "comptes-profils": ("Comptes et profils", ["User", "ProfilPrestataire", "Localisation"], ["Competence"]),
        "marketplace": ("Catalogue, demandes, devis, rendez-vous",
                        ["Categorie", "Service", "Competence", "PrestataireService", "DemandePrestation",
                         "DemandeDevis", "ReponseDevis", "Disponibilite", "RendezVous"], ["User", "ProfilPrestataire"]),
        "paiement": ("Paiement et wallet", ["Payment", "Wallet", "Transaction", "Withdrawal"],
                     ["User", "ProfilPrestataire", "DemandePrestation"]),
        "verification": ("Vérification d'identité", ["DocumentIdentite"], ["User", "ProfilPrestataire"]),
        "litiges": ("Litiges", ["Litige", "PreuveLitige"], ["User", "ProfilPrestataire", "DemandePrestation"]),
        "communication": ("Communication, avis et signalements", ["Message", "Notification", "Avis", "Signalement"],
                          ["User", "ProfilPrestataire", "DemandePrestation"]),
        "localisation": ("Localisation", ["Localisation"], ["User"]),
    }
    for fichier, (titre, complets, refs) in domaines.items():
        manquants = [n for n in complets + refs if n not in par_nom]
        if manquants:
            raise SystemExit(f"Modèle absent du code : {manquants}")
        (DIAGRAMMES / f"domaine-{fichier}.mmd").write_text(
            diagramme(f"MIMOSY — {titre}", [par_nom[n] for n in complets], [par_nom[n] for n in refs]), encoding="utf-8")
    return len(domaines)


# ─── Routes de l'API ────────────────────────────────────────────────────────

def parcourir(motifs, prefixe=""):
    for m in motifs:
        if isinstance(m, URLResolver):
            yield from parcourir(m.url_patterns, prefixe + str(m.pattern))
        elif isinstance(m, URLPattern):
            yield prefixe + str(m.pattern), m


def generer_routes():
    routes = []
    for chemin, motif in parcourir(get_resolver().url_patterns):
        cb = motif.callback
        classe = getattr(cb, "cls", None) or getattr(cb, "view_class", None)
        if classe is None or classe.__name__ in ("APIRootView",) or "format" in chemin or chemin.startswith("admin/"):
            continue
        actions = getattr(cb, "actions", None)
        if actions:
            methodes = [f"{k.upper()} → {v}" for k, v in actions.items()]
        else:
            methodes = [k.upper() for k in ("get", "post", "put", "patch", "delete") if hasattr(classe, k)]
        lisible = "/" + re.sub(r"\(\?P<(\w+)>[^)]+\)", r"<\1>", chemin).replace("^", "").replace("$", "").replace("\\.", ".")
        perms = ", ".join(p.__name__ for p in getattr(classe, "permission_classes", [])) or "—"
        serializer = getattr(getattr(classe, "serializer_class", None), "__name__", "") or "—"
        app = classe.__module__.split(".")[1] if classe.__module__.startswith("apps.") else classe.__module__.split(".")[0]
        routes.append((app, lisible, "<br>".join(methodes), classe.__name__, perms, serializer))

    lignes = [
        "# 08 — API REST (référence générée depuis le code)",
        "",
        "> Généré par `outils/generer_reference.py` depuis le résolveur d'URL Django.",
        "> « Permissions » = `permission_classes` déclarées sur la vue ; certaines",
        "> vues affinent l'accès dans `get_permissions()`, `get_queryset()` ou",
        "> directement dans l'action (voir 09-authentification-permissions-securite.md).",
        "",
        f"**{len(routes)} routes** (hors racines des routeurs DRF et admin Django).",
        "",
    ]
    par_app = defaultdict(list)
    for r in routes:
        par_app[r[0]].append(r)
    for app in sorted(par_app):
        lignes += [f"## {app}", "", "| Chemin | Méthode → action | Vue | Permissions | Serializer |", "|---|---|---|---|---|"]
        for _, chemin, methodes, vue, perms, serializer in par_app[app]:
            lignes.append(f"| `{chemin}` | {methodes} | `{vue}` | {perms} | {serializer} |")
        lignes.append("")
    (DOSSIER / "08-api-reference.md").write_text("\n".join(lignes), encoding="utf-8")
    return len(routes), len({r[3] for r in routes})


# ─── Inventaire fichier par fichier (analyse statique du code source) ───────

def inventaire_applications():
    """Classes et fonctions de chaque fichier Python des applications (module ast)."""
    import ast

    lignes = [
        "# 04 — Applications Django : inventaire fichier par fichier (généré)",
        "",
        "> Généré par `outils/generer_reference.py` par lecture du code source (module",
        "> `ast`) : pour chaque fichier, ses classes (avec leur classe parente) et ses",
        "> fonctions de premier niveau, avec la première ligne de leur docstring.",
        "> Les méthodes listées sont celles définies dans la classe (hors méthodes privées `_…`,",
        "> sauf les méthodes internes importantes des vues, préfixées `_`).",
        "",
    ]
    total_fichiers = 0
    for dossier in sorted((RACINE / "apps").iterdir()):
        if not dossier.is_dir() or dossier.name.startswith("__"):
            continue
        fichiers = sorted(p for p in dossier.rglob("*.py") if "migrations" not in p.parts and "__pycache__" not in p.parts and p.name != "__init__.py")
        if not fichiers:
            continue
        lignes += [f"## apps/{dossier.name}/", ""]
        for fichier in fichiers:
            total_fichiers += 1
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            doc_module = (ast.get_docstring(arbre) or "").strip().split("\n")[0]
            relatif = fichier.relative_to(RACINE)
            nb = len(fichier.read_text(encoding="utf-8").splitlines())
            lignes.append(f"### `{relatif}` ({nb} lignes)")
            if doc_module:
                lignes.append(f"_{doc_module}_")
            lignes.append("")
            for noeud in arbre.body:
                if isinstance(noeud, ast.ClassDef):
                    bases = ", ".join(ast.unparse(b) for b in noeud.bases) or "object"
                    doc = (ast.get_docstring(noeud) or "").strip().split("\n")[0]
                    lignes.append(f"- **classe `{noeud.name}`** ({bases}){' — ' + doc if doc else ''}")
                    for m in noeud.body:
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not m.name.startswith("__") or m.name in ("__call__",)):
                            dm = (ast.get_docstring(m) or "").strip().split("\n")[0]
                            deco = [ast.unparse(d).split("(")[0] for d in m.decorator_list]
                            marque = " `@action`" if any("action" in d for d in deco) else ""
                            lignes.append(f"    - `{m.name}()`{marque}{' — ' + dm if dm else ''}")
                elif isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = (ast.get_docstring(noeud) or "").strip().split("\n")[0]
                    lignes.append(f"- fonction `{noeud.name}()`{' — ' + doc if doc else ''}")
            lignes.append("")
    (DOSSIER / "04-applications-reference.md").write_text("\n".join(lignes), encoding="utf-8")
    return total_fichiers


def page_diagrammes():
    """Rassemble tous les fichiers .mmd (générés et écrits à la main) dans une page."""
    ordre = ["architecture", "classes-simplifie", "classes-complet"]
    fichiers = sorted(DIAGRAMMES.glob("*.mmd"), key=lambda p: (ordre.index(p.stem) if p.stem in ordre else 9, p.stem))
    lignes = [
        "# 06-07 — Diagrammes Mermaid",
        "",
        "Chaque diagramme existe aussi comme fichier séparé dans `diagrammes/`, à coller",
        "tel quel dans Mermaid Live Editor (https://mermaid.live). Les diagrammes de",
        "classes `classes-complet` et `domaine-*` sont **générés depuis les modèles",
        "Django** ; les autres (architecture, simplifié, séquences) sont écrits à la main",
        "à partir du code, et ne contiennent que des éléments qui y existent.",
        "",
        "Lecture des cardinalités (vue depuis la classe qui porte la clé étrangère) :",
        "`A \"0..*\" --> \"1\" B : champ` = plusieurs A pointent vers un même B (clé étrangère",
        "obligatoire) ; `\"0..1\"` côté B = clé étrangère facultative (`null=True`) ;",
        "`--` avec `0..*` des deux côtés = relation ManyToMany.",
        "",
    ]
    for f in fichiers:
        lignes += [f"## `{f.name}`", "", "```mermaid", f.read_text(encoding="utf-8").rstrip(), "```", ""]
    (DOSSIER / "06-diagrammes.md").write_text("\n".join(lignes), encoding="utf-8")
    return len(fichiers)


if __name__ == "__main__":
    liste = modeles_mimosy()
    nb_relations = generer_modeles(liste)
    nb_domaines = generer_diagrammes(liste)
    nb_routes, nb_vues = generer_routes()
    nb_fichiers = inventaire_applications()
    nb_diagrammes = page_diagrammes()
    print(f"{nb_fichiers} fichiers backend inventoriés, {nb_diagrammes} diagrammes rassemblés")
    print(f"{len(liste)} modèles, {nb_relations} champs relationnels, {nb_domaines} diagrammes de domaine, "
          f"{nb_routes} routes, {nb_vues} vues")
