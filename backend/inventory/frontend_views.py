"""Sert le build Vue (frontend/dist/index.html) pour le routage SPA.

Déploiement "option B" (2026-08-xx, voir CLAUDE.md) : Django sert le
frontend construit depuis le même service que l'API, plutôt qu'un
hébergement séparé. `vue-router` utilise `createWebHistory` (mode history,
voir frontend/src/router/index.js) — une route profonde comme
`/spectacles/5` n'a pas de fichier correspondant sur disque, donc le
serveur doit répondre avec `index.html` pour que vue-router prenne le
relais côté client. C'est le rôle de cette vue, montée en dernier (catch-all)
dans config/urls.py.

`index.html` n'est PAS servi via STATICFILES_DIRS/WhiteNoise comme les
assets hashés (voir config/settings.py) : `ManifestStaticFilesStorage`
renommerait le fichier avec un hash de contenu, cassant l'URL stable dont
ce catch-all a besoin. Il est donc lu directement depuis le disque ici.
"""

from django.conf import settings
from django.http import HttpResponse

_INDEX_HTML_PATH = settings.FRONTEND_DIST_DIR / 'index.html'


def spa_index(request):
    """Renvoie le `index.html` du build Vue tel quel.

    Si le frontend n'a pas été construit (`npm run build` dans
    `frontend/`, absent en dev local sans étape de build), répond 501 avec
    un message explicite plutôt qu'un 404/500 opaque — utile en local et
    en cas de souci de build sur Railway.
    """
    try:
        html = _INDEX_HTML_PATH.read_text(encoding='utf-8')
    except FileNotFoundError:
        return HttpResponse(
            "Frontend non construit : lancez `npm run build` dans "
            "frontend/ (voir CLAUDE.md, déploiement).",
            status=501,
        )
    return HttpResponse(html)


def robots_txt(request):
    """`robots.txt` — interdit l'indexation des pages publiques de rapport.

    Ajouté avec les liens publics (2026-08-08). Le catch-all SPA répondrait
    sinon `index.html` sur `/robots.txt`, ce qu'un robot interprète comme
    « pas de règles », donc « tout est indexable ». Or `/p/<token>` sert des
    feuilles de tournée avec adresses de quai et coordonnées de contacts.

    Ceci ne PROTÈGE rien — un robot malveillant ignore ce fichier, et de
    toute façon la liste des jetons n'est nulle part. C'est une mesure
    d'hygiène contre l'indexation accidentelle par un moteur qui suivrait un
    lien collé dans un courriel ou un canal public. La vraie protection reste
    l'entropie du jeton et l'en-tête `X-Robots-Tag` (voir public_views.py).
    """
    return HttpResponse(
        'User-agent: *\nDisallow: /p/\nDisallow: /api/\n',
        content_type='text/plain; charset=utf-8',
    )
