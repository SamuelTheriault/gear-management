"""
Assainissement du HTML saisi dans les notes (2026-08-05).

Demande de Samuel : pouvoir mettre du texte riche — et surtout des liens —
dans les notes d'un spectacle et d'un déplacement. Les notes passent donc de
texte brut à un petit HTML produit par l'éditeur de la fiche.

**Pourquoi assainir plutôt que faire confiance à l'éditeur** : le contenu
revient par l'API, et rien n'oblige un client à passer par l'éditeur — un
`PATCH` direct suffirait à stocker `<script>`. Il serait ensuite rendu tel
quel par `v-html` chez tous ceux qui consultent la fiche. Depuis que l'app
est multi-tenant (voir `ProjectMembership`), ce n'est plus seulement le
contenu de Samuel qui s'affiche dans le navigateur de Samuel.

L'assainissement se fait à l'ÉCRITURE (voir `ShowSerializer`/
`TransportSerializer`) : ce qui est en base est donc déjà propre, et un
futur consommateur qui oublierait de nettoyer à l'affichage ne peut pas
réintroduire la faille. La bibliothèque est `nh3` (successeur de bleach,
recommandé par ce dernier depuis son abandon).

Liste blanche volontairement courte : ce que produit la barre d'outils de
`RichTextEditor.vue`, rien de plus. Pas d'images ni de tableaux — si le
besoin apparaît, c'est une décision à prendre, pas un oubli à combler
discrètement.
"""

import nh3

BALISES_AUTORISEES = {
    'p', 'br', 'strong', 'em', 'u', 's',
    'ul', 'ol', 'li',
    'a',
    'h3', 'h4',
    'blockquote', 'code',
}

ATTRIBUTS_AUTORISES = {
    'a': {'href', 'title'},
}

# Schémas d'URL acceptés pour un lien. `mailto`/`tel` sont utiles dans ce
# contexte (contacts de salle) ; `javascript:` est exclu de fait, c'est le
# vecteur classique.
SCHEMAS_AUTORISES = {'http', 'https', 'mailto', 'tel'}


def clean_notes(html):
    """Retourne `html` débarrassé de tout ce qui n'est pas dans la liste blanche.

    Une chaîne vide ou `None` ressort telle quelle. Le texte brut déjà saisi
    avant ce changement traverse sans dommage : il ne contient pas de balise,
    donc rien à retirer.

    `link_rel` ajoute `noopener noreferrer` aux liens — sans ça, une page
    ouverte depuis un lien peut manipuler la fenêtre d'origine.
    """
    if not html:
        return html
    return nh3.clean(
        html,
        tags=BALISES_AUTORISEES,
        attributes=ATTRIBUTS_AUTORISES,
        url_schemes=SCHEMAS_AUTORISES,
        link_rel='noopener noreferrer',
    )
