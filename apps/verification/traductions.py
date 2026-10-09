"""
Textes fixes d'Aby et de Fassa dans chaque langue de communication.

Les textes sont traduits À L'AVANCE (pas à chaque message) : ils restent
stables, ne coûtent aucun appel IA et leur voix est mise en cache une fois.
Le français est la référence ; une clé absente dans une langue retombe sur
le français. Les valeurs entre accolades ({domaine}...) sont remplies au
moment de l'affichage.

Les noms du catalogue (domaines, services) restent en français dans toutes
les langues : ce sont les données de référence de MIMOSY.

    en : relu.
    wo : premier jet produit avec Gemini puis corrigé à la main (salutations,
         « client », vouvoiement « ngeen/seen », caractères = « araf »).
         À FAIRE VALIDER PAR UN LOCUTEUR NATIF avant la production (voir
         TRADUCTIONS_A_VALIDER).
"""

TRADUCTIONS_A_VALIDER = {"wo"}

TEXTES = {
    # ------------------------------------------------------------ langue
    "langue.question": {
        "fr": "Comment souhaitez-vous communiquer avec moi ?",
        "en": "How would you like to talk with me?",
        "wo": "Ban làkk ngeen bëgg ñu waxtaane?",
    },
    "langue.confirmee": {
        "fr": "Très bien, nous continuons en {nom_langue}.",
        "en": "Very well, we will continue in {nom_langue}.",
        "wo": "Baax na, nu ngi kontine ci {nom_langue}.",
    },
    # ------------------------------------------------------------ Aby
    "aby.accueil": {
        "fr": (
            "Bonjour, je m'appelle Aby. Je suis l'assistante IA de MIMOSY. Je vais vous accompagner pour "
            "compléter vos premières informations professionnelles. Cela prendra seulement quelques minutes. "
            "Vous pouvez me répondre à la voix ou par écrit."
        ),
        "en": (
            "Hello, my name is Aby. I am MIMOSY's AI assistant. I will help you complete your first "
            "professional details. It will only take a few minutes. You can answer me by voice or in writing."
        ),
        "wo": (
            "Salaamaalekum, maa ngi tudd Aby. Man laa assistante IA bu MIMOSY. Dinaa leen dimbali ngir "
            "mottali seeni xibaar yu njëkk ci seen liggéey. Du yàgg, ay minit rekk. Mën ngeen ma tontu ci "
            "kàddu walla ci bind."
        ),
    },
    "aby.fin": {
        "fr": (
            "Merci, votre profil professionnel est complet. Vous pouvez encore modifier chaque information "
            "dans le résumé. Étape suivante : votre pièce d'identité."
        ),
        "en": (
            "Thank you, your professional profile is complete. You can still change any information in the "
            "summary. Next step: your ID document."
        ),
        "wo": (
            "Jërëjëf, seen profil professionnel mat na. Mën ngeen soppi xibaar bu nekk ci résumé bi. "
            "Li ci topp : seen pièce d'identité."
        ),
    },
    "q.metier.texte": {"fr": "Quel est votre métier ?", "en": "What is your trade?", "wo": "Lan mooy seen métier?"},
    "q.metier.pourquoi": {
        "fr": "C'est la première chose que les clients verront sur votre profil.",
        "en": "It is the first thing clients will see on your profile.",
        "wo": "Mooy li client yi di njëkk a gis ci seen profil.",
    },
    "q.metier.exemple": {
        "fr": "Électricien, plombier, femme de ménage...",
        "en": "Electrician, plumber, cleaner...",
        "wo": "Électricien, plombier, femme de ménage...",
    },
    "q.domaine.texte": {
        "fr": "Dans quel domaine exercez-vous ?",
        "en": "Which field do you work in?",
        "wo": "Ci ban domaine ngeen di liggéey?",
    },
    "q.domaine.pourquoi": {
        "fr": "Le domaine permet aux clients de vous trouver dans la bonne catégorie.",
        "en": "Your field helps clients find you in the right category.",
        "wo": "Domaine bi dafay tax client yi gis leen ci catégorie bu baax bi.",
    },
    "q.services.texte": {
        "fr": "Quels types de travaux réalisez-vous principalement ?",
        "en": "What kinds of work do you mainly do?",
        "wo": "Ban xeetu liggéey ngeen gën di def?",
    },
    "q.services.pourquoi": {
        "fr": "Vous pourrez fixer vos tarifs pour chacun d'eux une fois votre profil validé.",
        "en": "You will be able to set your prices for each of them once your profile is approved.",
        "wo": "Bu seen profil validé, mën ngeen tëral tarif bu nekk ci ñoom.",
    },
    "q.experience.texte": {
        "fr": "Depuis combien d'années exercez-vous ce métier ?",
        "en": "How many years have you been doing this work?",
        "wo": "Ñaata at ngeen def métier bii?",
    },
    "q.experience.pourquoi": {
        "fr": "Votre expérience rassure les clients ; indiquez 0 si vous débutez.",
        "en": "Your experience reassures clients; say 0 if you are just starting.",
        "wo": "Seen expérience dafay dëgëral kóolute client yi; wax leen 0 su fekkee yéena ngi tàmbali.",
    },
    "q.zone_intervention.texte": {
        "fr": "Dans quelles villes ou quels quartiers intervenez-vous ?",
        "en": "In which towns or neighbourhoods do you work?",
        "wo": "Ci ban dëkk walla ban quartier ngeen di liggéey?",
    },
    "q.zone_intervention.pourquoi": {
        "fr": "MIMOSY vous propose ainsi des demandes proches de chez vous.",
        "en": "This way, MIMOSY offers you requests close to where you are.",
        "wo": "Noonu, MIMOSY dina leen yónnee demande yu jege seen kër.",
    },
    "q.zone_intervention.exemple": {
        "fr": "Dakar Plateau, Médina, Parcelles Assainies...",
        "en": "Dakar Plateau, Médina, Parcelles Assainies...",
        "wo": "Dakar Plateau, Médina, Parcelles Assainies...",
    },
    "q.disponibilites.texte": {
        "fr": "Quand êtes-vous généralement disponible ?",
        "en": "When are you usually available?",
        "wo": "Ban fan ak ban waxtu ngeen di liggéey?",
    },
    "q.disponibilites.pourquoi": {
        "fr": "Les clients savent ainsi quand ils peuvent vous solliciter.",
        "en": "Clients then know when they can call on you.",
        "wo": "Noonu client yi dinañu xam kañ lañu leen mën a woo.",
    },
    "q.disponibilites.exemple": {
        "fr": "Du lundi au samedi, de 8 h à 18 h",
        "en": "Monday to Saturday, 8 am to 6 pm",
        "wo": "Altine ba Gaawu, 8 h ba 18 h",
    },
    "q.description.texte": {
        "fr": "Décrivez votre activité en quelques phrases.",
        "en": "Describe your work in a few sentences.",
        "wo": "Wone leen seen liggéey ci ay kàddu yu gàtt.",
    },
    "q.description.pourquoi": {
        "fr": "Cette présentation apparaîtra sur votre profil public.",
        "en": "This description will appear on your public profile.",
        "wo": "Li ngeen bind dina feeñ ci seen profil public.",
    },
    "aby.prerempli_services": {
        "fr": (
            "J'ai rattaché votre métier au domaine « {domaine} » et noté : {services}. "
            "Vous pourrez corriger ces choix dans le résumé."
        ),
        "en": "I linked your trade to the « {domaine} » field and noted: {services}. You can correct these choices in the summary.",
        "wo": "Boole naa seen métier ak domaine « {domaine} », te bind naa : {services}. Mën ngeen ko soppi ci résumé bi.",
    },
    "aby.prerempli_domaine": {
        "fr": "J'ai rattaché votre métier au domaine « {domaine} ». Vous pourrez le corriger dans le résumé.",
        "en": "I linked your trade to the « {domaine} » field. You can correct it in the summary.",
        "wo": "Boole naa seen métier ak domaine « {domaine} ». Mën ngeen ko soppi ci résumé bi.",
    },
    "aby.aussi_note": {"fr": "J'ai aussi noté : {notes}.", "en": "I also noted: {notes}.", "wo": "Bind naa itam : {notes}."},
    "aby.note_experience": {
        "fr": "{annees} an{pluriel} d'expérience",
        "en": "{annees} year{pluriel_en} of experience",
        "wo": "{annees} at ci liggéey bi",
    },
    "aby.note_zone": {"fr": "zone : {valeur}", "en": "area: {valeur}", "wo": "quartier : {valeur}"},
    "aby.note_disponibilites": {
        "fr": "disponibilités : {valeur}",
        "en": "availability: {valeur}",
        "wo": "waxtu liggéey : {valeur}",
    },
    # ------------------------------------------------------------ réponses refusées (Aby)
    "err.champ_inconnu": {
        "fr": "Cette information n'est pas demandée par Aby.",
        "en": "Aby does not ask for this information.",
        "wo": "Aby laajul xibaar boobu.",
    },
    "err.langue": {
        "fr": "Choisissez une langue parmi les propositions.",
        "en": "Please choose one of the languages offered.",
        "wo": "Tànn leen benn làkk ci yi ñu leen jox.",
    },
    "err.pas_compris": {
        "fr": "Je n'ai pas bien compris votre réponse. Pouvez-vous la reformuler, ou l'écrire ?",
        "en": "I did not quite understand your answer. Could you rephrase it, or write it?",
        "wo": "Dégguma bu baax seen tontu. Mën ngeen ko waxaat, walla ngeen bind ko?",
    },
    "err.metier": {
        "fr": "Indiquez votre métier en quelques mots (par exemple « électricien »).",
        "en": "Tell me your trade in a few words (for example « electrician »).",
        "wo": "Wax leen seen métier ci ay baat (ci misaal « électricien »).",
    },
    "err.domaine": {
        "fr": "Je n'ai pas reconnu ce domaine dans le catalogue MIMOSY. Choisissez-le parmi les suggestions.",
        "en": "I did not find this field in the MIMOSY catalogue. Please choose it from the suggestions.",
        "wo": "Gisuma domaine boobu ci catalogue MIMOSY. Tànn leen ko ci li ñu leen jox.",
    },
    "err.domaine_dabord": {
        "fr": "Choisissez d'abord votre domaine.",
        "en": "Please choose your field first.",
        "wo": "Tànn leen seen domaine bala nuy dem.",
    },
    "err.services": {
        "fr": (
            "Je n'ai pas reconnu ces travaux parmi les services du catalogue. "
            "Choisissez-les parmi les suggestions."
        ),
        "en": "I did not find this work among the catalogue services. Please choose them from the suggestions.",
        "wo": "Gisuma liggéey yooyu ci services yu catalogue bi. Tànn leen leen ci li ñu leen jox.",
    },
    "err.experience": {
        "fr": "Indiquez un nombre d'années, par exemple « 5 » (0 si vous débutez).",
        "en": "Give a number of years, for example « 5 » (0 if you are just starting).",
        "wo": "Wax leen ñaata at, ci misaal « 5 » (0 su fekkee yéena ngi tàmbali).",
    },
    "err.zone": {
        "fr": "Indiquez au moins une ville ou un quartier.",
        "en": "Give at least one town or neighbourhood.",
        "wo": "Wax leen lu mu néew néew benn dëkk walla benn quartier.",
    },
    "err.disponibilites": {
        "fr": "Indiquez vos jours ou horaires habituels.",
        "en": "Give your usual days or working hours.",
        "wo": "Wax leen fan yi walla waxtu yi ngeen di liggéey.",
    },
    "err.description_courte": {
        "fr": "Décrivez votre activité en une ou deux phrases (20 caractères minimum).",
        "en": "Describe your work in one or two sentences (at least 20 characters).",
        "wo": "Wone leen seen liggéey ci benn walla ñaari kàddu (20 araf lu néew néew).",
    },
    "err.description_longue": {
        "fr": "Votre description ne doit pas dépasser 1000 caractères.",
        "en": "Your description must not exceed 1000 characters.",
        "wo": "Seen description warul ëpp 1000 araf.",
    },
    "err.inconnu": {"fr": "Information inconnue.", "en": "Unknown information.", "wo": "Xibaar bu ñu xamul."},
    # ------------------------------------------------------------ Fassa
    "fassa.accueil": {
        "fr": (
            "Bonjour. Je suis Fassa, l'assistante IA de vérification professionnelle de MIMOSY. "
            "Je vais vous poser quelques questions sur votre expérience et votre activité, "
            "afin de préparer votre dossier de vérification. "
            "L'entretien dure {duree} au maximum. "
            "Vous pouvez répondre à la voix, ou par écrit."
        ),
        "en": (
            "Hello. I am Fassa, MIMOSY's AI professional verification assistant. I will ask you a few "
            "questions about your experience and your work, to prepare your verification file. "
            "The interview lasts {duree} at most. You can answer by voice, or in writing."
        ),
        "wo": (
            "Salaamaalekum. Man laa Fassa, assistante IA bu MIMOSY ngir vérification professionnelle. "
            "Dinaa leen laaj ay laaj ci seen expérience ak seen liggéey, ngir waajal seen dossier. "
            "Entretien bi du ëpp {duree}. Mën ngeen tontu ci kàddu, walla ci bind."
        ),
    },
    "fassa.fin": {
        "fr": (
            "Merci pour vos réponses. L'entretien est terminé. "
            "Je transmets votre dossier à l'équipe MIMOSY, qui prendra la décision finale."
        ),
        "en": (
            "Thank you for your answers. The interview is over. I am passing your file to the MIMOSY "
            "team, who will make the final decision."
        ),
        "wo": (
            "Jërëjëf ci seen tontu yi. Entretien bi jeex na. Dinaa yónnee seen dossier équipe MIMOSY, "
            "ñoom ñoo ciy jël décision bu mujj bi."
        ),
    },
    "fassa.temps_ecoule": {
        "fr": "Merci. Nous arrivons à la fin du temps prévu.",
        "en": "Thank you. We have reached the end of the planned time.",
        "wo": "Jërëjëf. Waxtu bi ñu waajaloon jeex na.",
    },
    "fassa.merci": {"fr": "Merci.", "en": "Thank you.", "wo": "Jërëjëf."},
    "fassa.transition.1": {"fr": "D'accord, c'est noté.", "en": "All right, noted.", "wo": "Waaw, bind naa ko."},
    "fassa.transition.2": {"fr": "Très bien, merci.", "en": "Very good, thank you.", "wo": "Baax na, jërëjëf."},
    "fassa.transition.3": {"fr": "Entendu.", "en": "Understood.", "wo": "Dégg naa."},
    "fassa.transition.4": {
        "fr": "Merci pour ces précisions.",
        "en": "Thank you for these details.",
        "wo": "Jërëjëf ci leeral yi.",
    },
    "fassa.relance_annees": {
        "fr": "Depuis combien d'années environ ?",
        "en": "For about how many years?",
        "wo": "Ñaata at lu jege?",
    },
    "fassa.relance_exemple": {
        "fr": "Pouvez-vous donner un exemple concret ?",
        "en": "Could you give a concrete example?",
        "wo": "Mën ngeen joxe benn misaal bu leer?",
    },
    # Durées dites par Fassa dans l'accueil.
    "duree.minutes": {"fr": "{nombre} minute{pluriel}", "en": "{nombre} minute{pluriel_en}", "wo": "{nombre} minit"},
}

NOMBRES_EN_LETTRES = {
    "fr": {1: "une", 2: "deux", 3: "trois", 4: "quatre", 5: "cinq", 6: "six", 7: "sept", 8: "huit", 9: "neuf", 10: "dix"},
    "en": {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"},
}


def texte(cle, langue="fr", **valeurs):
    """Le texte « cle » dans « langue » (français à défaut), valeurs remplies."""

    variantes = TEXTES[cle]
    modele = variantes.get(langue) or variantes["fr"]
    return modele.format(**valeurs) if valeurs else modele


def duree_minutes(minutes, langue="fr"):
    """« cinq minutes », « five minutes », « 5 minit »."""

    nombre = NOMBRES_EN_LETTRES.get(langue, {}).get(minutes, minutes)
    return texte("duree.minutes", langue, nombre=nombre, pluriel="s" if minutes > 1 else "",
                 pluriel_en="s" if minutes != 1 else "")


def question_langue(codes):
    """Question du choix de langue, posée dans toutes les langues proposées (la langue n'est pas encore connue)."""

    return " · ".join(texte("langue.question", code) for code in codes)
