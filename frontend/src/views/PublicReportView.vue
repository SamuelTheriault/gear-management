<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'

/**
 * Page publique d'une sortie de rapport — la destination du code QR imprimé
 * en pied de feuille (chantier 2026-08-08).
 *
 * C'est la SEULE page de l'app accessible sans session : le routeur l'exempte
 * explicitement de sa garde d'authentification (voir router/index.js), et
 * elle tape sur `/api/public/reports/<token>/`, seul endpoint DRF en
 * `AllowAny` (voir backend/inventory/public_views.py).
 *
 * Conséquences sur ce qu'on a le droit d'y mettre :
 *
 * - **Pas d'`AppShell`.** Ni barre latérale, ni sélecteur de projet, ni lien
 *   vers le reste de l'app. La personne qui scanne n'a pas de compte ; lui
 *   montrer une navigation qu'elle ne peut pas suivre est au mieux inutile,
 *   au pire une invitation à chercher une faille.
 * - **Aucune écriture.** Pas de bouton, pas de formulaire. La feuille se lit.
 * - **Pensée pour un téléphone, dans un quai mal éclairé.** Contrastes francs,
 *   corps de texte généreux, aucune interaction indispensable.
 *
 * L'élément le plus important de la page n'est pas le contenu mais
 * `fetched_at` : c'est ce que la personne compare avec la date imprimée sur
 * sa feuille pour savoir si sa copie papier a pris du retard. Sans cette
 * comparaison, scanner le code n'apprend rien.
 */

const route = useRoute()

const chargement = ref(true)
const erreur = ref('')
const donnees = ref(null)

const rapport = computed(() => donnees.value?.report ?? null)

/** Format « jeudi 14 septembre, 8 h 35 » — convention francophone (« 8 h 35 »
 *  avec espaces, pas « 08:35 »), comme partout ailleurs dans l'app. */
function heure(valeur) {
  if (!valeur) return '—'
  const d = new Date(valeur)
  return d.toLocaleTimeString('fr-CA', { hour: 'numeric', minute: '2-digit' }).replace(':', ' h ')
}

function jourEtHeure(valeur) {
  if (!valeur) return '—'
  const d = new Date(valeur)
  return `${d.toLocaleDateString('fr-CA', { weekday: 'long', day: 'numeric', month: 'long' })}, ${heure(valeur)}`
}

function km(metres) {
  if (!metres) return null
  return (metres / 1000).toFixed(1).replace('.', ',')
}

// Fond clair forcé le temps de cette page. Le thème de l'app (clair ou
// sombre, voir useTheme) pose son fond sur `body` ; une feuille publique doit
// rester lisible quel que soit le réglage de la PERSONNE QUI A IMPRIMÉ, et
// surtout ressembler à la version papier. On restaure au démontage plutôt que
// de déclarer une règle globale non scopée, qui teindrait toute l'app une fois
// le bundle chargé.
let fondPrecedent = ''
onMounted(() => {
  fondPrecedent = document.body.style.background
  document.body.style.background = '#fff'
})
onUnmounted(() => {
  document.body.style.background = fondPrecedent
})

onMounted(async () => {
  // Appel direct plutôt que via `api/client.js` : ce dernier envoie
  // `credentials: 'include'` et un jeton CSRF, inutiles ici et qui feraient
  // porter à une page publique des cookies qu'elle n'a aucune raison de
  // manipuler.
  try {
    const res = await fetch(`/api/public/reports/${encodeURIComponent(route.params.token)}/`, {
      headers: { Accept: 'application/json' },
    })
    if (!res.ok) {
      const corps = await res.json().catch(() => null)
      erreur.value = corps?.detail
        || "Ce lien n'est plus valide. Demande une version à jour à la personne qui te l'a remis."
      return
    }
    donnees.value = await res.json()
  } catch {
    erreur.value = "Impossible de joindre le serveur. Vérifie ta connexion et réessaie."
  } finally {
    chargement.value = false
  }
})
</script>

<template>
  <div class="page">
    <p v-if="chargement" class="etat">Chargement…</p>

    <div v-else-if="erreur" class="etat erreur">
      <h1>Lien indisponible</h1>
      <p>{{ erreur }}</p>
      <p class="signature-app">RégiStock</p>
    </div>

    <article v-else class="fiche">
      <header class="entete">
        <div class="ligne-badges">
          <span class="badge">{{ donnees.kind_display }}</span>
          <span class="projet">{{ donnees.project }}</span>
          <!-- Même jeton, même contenu : le PDF est simplement la version
               imprimable de cette page. Utile au DT d'une salle qui veut sa
               copie papier avant l'arrivée du camion, sans avoir à réclamer
               un compte à personne. -->
          <a class="lien-pdf" :href="`/api/public/reports/${$route.params.token}/pdf/`">
            Version imprimable (PDF)
          </a>
        </div>

        <!-- La mention qui donne son sens au code QR : cette page-ci est à
             jour, la feuille papier date de son impression. -->
        <p class="fraicheur">
          Version à jour, lue le <strong>{{ jourEtHeure(donnees.fetched_at) }}</strong>.
          En cas d'écart avec ta copie papier, c'est cette page qui fait foi.
        </p>
      </header>

      <!-- ------------------------------ Transport ------------------------------ -->
      <section v-if="rapport.kind === 'transport'">
        <h1>{{ rapport.stops[0]?.venue?.name }} → {{ rapport.stops[rapport.stops.length - 1]?.venue?.name }}</h1>
        <p v-if="rapport.show" class="sous-titre">Rattaché à {{ rapport.show }}</p>

        <dl class="resume">
          <div><dt>Départ</dt><dd>{{ heure(rapport.scheduled_datetime) }}</dd></div>
          <div><dt>Arrivée</dt><dd>{{ heure(rapport.ends_at) }}</dd></div>
          <div><dt>Arrêts</dt><dd>{{ rapport.stops.length }}</dd></div>
          <div v-if="km(rapport.distance_meters)">
            <dt>Distance</dt>
            <dd>{{ rapport.distance_is_partial ? 'au moins ' : '' }}{{ km(rapport.distance_meters) }} km</dd>
          </div>
          <div v-if="rapport.truck"><dt>Camion</dt><dd>{{ rapport.truck }}</dd></div>
        </dl>

        <p v-if="rapport.team.length" class="equipe">
          <span class="etiquette">Équipe</span>
          <span v-for="p in rapport.team" :key="p.id">
            {{ p.name }}<span v-if="p.specialty" class="discret"> ({{ p.specialty }})</span>
          </span>
        </p>

        <ol class="arrets">
          <li v-for="arret in rapport.stops" :key="arret.order">
            <div class="arret-heure">
              <strong>{{ heure(arret.arrival_at) }}</strong>
              <span class="discret">{{ arret.is_first ? 'départ' : arret.travel_minutes_from_previous + ' min' }}</span>
            </div>
            <div class="arret-corps">
              <h2>{{ arret.venue.name }} <span v-if="arret.venue.code" class="code">{{ arret.venue.code }}</span></h2>
              <p v-if="arret.venue.address" class="discret">
                {{ arret.venue.address }}<span v-if="arret.venue.contact_info"> · {{ arret.venue.contact_info }}</span>
              </p>

              <div v-if="arret.load.length" class="manifeste charger">
                <h3>Charger</h3>
                <p v-for="(l, i) in arret.load" :key="'c' + i">
                  <span class="qte">{{ l.quantity }}</span> {{ l.material }}
                  <span v-if="l.to" class="discret">→ {{ l.to }}</span>
                </p>
              </div>

              <div v-if="arret.unload.length" class="manifeste decharger">
                <h3>Décharger</h3>
                <p v-for="(l, i) in arret.unload" :key="'d' + i">
                  <span class="qte">{{ l.quantity }}</span> {{ l.material }}
                </p>
              </div>
            </div>
          </li>
        </ol>

        <p v-if="rapport.notes" class="notes">{{ rapport.notes }}</p>
      </section>

      <!-- ------------------------------ Spectacle ------------------------------ -->
      <section v-else-if="rapport.kind === 'show'">
        <h1>{{ rapport.title }}</h1>
        <p class="sous-titre">{{ rapport.event_type_display }} · {{ rapport.venue?.name }}</p>

        <dl class="resume">
          <div><dt>Début</dt><dd>{{ jourEtHeure(rapport.start_datetime) }}</dd></div>
          <div><dt>Fin</dt><dd>{{ heure(rapport.end_datetime) }}</dd></div>
        </dl>

        <template v-if="rapport.blocks.length">
          <h2>Montages, démontages et répétitions</h2>
          <p v-for="bloc in rapport.blocks" :key="bloc.id" class="ligne">
            <strong>{{ heure(bloc.start_datetime) }}</strong> — {{ bloc.event_type_display }}
            <span class="discret">{{ bloc.venue?.name }}</span>
          </p>
        </template>

        <template v-if="rapport.transports.length">
          <h2>Transports</h2>
          <p v-for="t in rapport.transports" :key="t.id" class="ligne">
            <strong>{{ heure(t.scheduled_datetime) }}</strong> — {{ t.from }} → {{ t.to }}
          </p>
        </template>

        <template v-if="rapport.team.length">
          <h2>Équipe</h2>
          <p v-for="p in rapport.team" :key="p.id" class="ligne">
            {{ p.name }}<span v-if="p.specialty" class="discret"> — {{ p.specialty }}</span>
          </p>
        </template>

        <template v-if="rapport.materials.length">
          <h2>Matériel — {{ rapport.materials.length }} lignes</h2>
          <p v-for="(m, i) in rapport.materials" :key="i" class="ligne">
            <span class="qte">{{ m.quantity }}</span> {{ m.material }}
            <span v-if="m.is_rental" class="discret">— location{{ m.rental_vendor ? ' · ' + m.rental_vendor : '' }}</span>
          </p>
        </template>
      </section>

      <!-- ------------------------- Parcours technicien -------------------------- -->
      <section v-else-if="rapport.kind === 'technician'">
        <h1>{{ rapport.name }}</h1>
        <p v-if="rapport.specialty" class="sous-titre">{{ rapport.specialty }}</p>

        <ol class="arrets">
          <li v-for="e in rapport.engagements" :key="e.type + e.id + e.start">
            <div class="arret-heure">
              <strong>{{ heure(e.start) }}</strong>
              <span class="discret">{{ new Date(e.start).toLocaleDateString('fr-CA', { day: 'numeric', month: 'short' }) }}</span>
            </div>
            <div class="arret-corps">
              <h2>{{ e.title }}</h2>
              <p class="discret">
                {{ e.type === 'transport' ? 'Tournée' : e.event_type_display }}
                <span v-if="e.venue"> · {{ e.venue.name }}</span>
                <span v-if="e.inherited"> · rattaché au spectacle</span>
              </p>
            </div>
          </li>
        </ol>
        <p v-if="!rapport.engagements.length" class="etat">Aucun engagement planifié.</p>
      </section>

      <!-- ------------------------ Horaire de la journée ------------------------- -->
      <section v-else-if="rapport.kind === 'day'">
        <h1>{{ new Date(rapport.day + 'T12:00:00').toLocaleDateString('fr-CA', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) }}</h1>

        <div v-for="(lane, i) in rapport.lanes" :key="i" class="couloir">
          <h2>{{ lane.venue?.name ?? 'Sans lieu' }}</h2>
          <p v-for="item in lane.items" :key="item.type + item.id" class="ligne">
            <strong>{{ heure(item.start) }}–{{ heure(item.end) }}</strong>
            {{ item.title }}
            <span v-if="item.team.length" class="discret">
              — {{ item.team.map((p) => p.name).join(', ') }}
            </span>
          </p>
        </div>
        <p v-if="!rapport.lanes.length" class="etat">Rien de planifié ce jour-là.</p>
      </section>
      <p class="signature-app">RégiStock</p>
    </article>
  </div>
</template>

<style scoped>
/* Autonome et volontairement sans dépendance au thème de l'app : cette page
   est vue par des gens qui n'ont pas de compte, souvent sur un téléphone,
   parfois imprimée à leur tour. Elle doit tenir seule. */
.page {
  max-width: 46rem;
  margin: 0 auto;
  padding: 1.25rem 1rem 4rem;
  background: #fff;
  min-height: 100vh;
  color: #0f1216;
  font: 400 16px/1.5 system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.etat { color: #555; padding: 2rem 0; }
.erreur h1 { font-size: 1.25rem; margin-bottom: 0.5rem; }

.entete { border-bottom: 2px solid #0f1216; padding-bottom: 0.75rem; margin-bottom: 1.25rem; }
.ligne-badges { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 0.75rem; }
.badge {
  background: #b0136d; color: #fff; font-size: 0.7rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase; padding: 0.3rem 0.55rem;
  border-radius: 0 0.5rem 0 0.5rem;
}
.projet { color: #555; font-size: 0.9rem; }
.lien-pdf {
  margin-left: auto; font-size: 0.82rem; color: #b0136d; text-decoration: none;
  border: 1px solid #b0136d; padding: 0.3rem 0.6rem; border-radius: 0 0.5rem 0 0.5rem;
}
.fraicheur {
  margin-top: 0.6rem; font-size: 0.85rem; color: #333;
  background: #f3f4f6; border-left: 3px solid #b0136d; padding: 0.5rem 0.7rem;
}

h1 { font-size: 1.5rem; line-height: 1.2; margin: 0 0 0.25rem; }
.sous-titre { color: #555; margin: 0 0 1rem; }
h2 { font-size: 1rem; margin: 1.5rem 0 0.4rem; }
h3 {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.09em;
  margin: 0 0 0.25rem; color: #0a7c53;
}
.decharger h3 { color: #1f5fbf; }

.resume { display: flex; flex-wrap: wrap; gap: 0.5rem 1.5rem; margin: 1rem 0; }
.resume dt { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em; color: #666; }
.resume dd { margin: 0; font-size: 1.1rem; font-weight: 700; }

.equipe { display: flex; flex-wrap: wrap; gap: 0.3rem 0.9rem; margin: 0.75rem 0; }
.etiquette { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em; color: #666; }
.discret { color: #666; font-weight: 400; }

.arrets { list-style: none; padding: 0; margin: 1.25rem 0 0; }
.arrets li {
  display: grid; grid-template-columns: 5.5rem 1fr; gap: 0.75rem;
  border-top: 1px solid #e2e4e8; padding: 0.9rem 0;
}
.arret-heure { display: flex; flex-direction: column; align-items: flex-end; }
.arret-heure strong { font-size: 1.1rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
.arret-heure .discret { font-size: 0.78rem; }
.arret-corps h2 { margin: 0 0 0.15rem; font-size: 1.05rem; }
.code {
  font-size: 0.68rem; border: 1px solid #c9ccd2; padding: 0.1rem 0.3rem;
  border-radius: 0 0.35rem 0 0.35rem; color: #555; vertical-align: middle;
}

.manifeste { border: 1px solid #e2e4e8; border-radius: 0 0.6rem 0 0.6rem; padding: 0.55rem 0.7rem; margin-top: 0.5rem; }
.manifeste p { margin: 0.15rem 0; }
.qte { display: inline-block; min-width: 1.6rem; font-weight: 700; font-variant-numeric: tabular-nums; }

.ligne { margin: 0.3rem 0; }
.couloir { margin-bottom: 1.25rem; }
.notes { margin-top: 1.25rem; padding-top: 0.75rem; border-top: 1px solid #e2e4e8; color: #333; }

/* Réimpression depuis le téléphone ou le poste d'une salle : on retire les
   aplats, qui vident une cartouche pour rien. Le PDF officiel reste celui
   généré par le serveur (WeasyPrint) — ceci n'est qu'un filet. */
.signature-app {
  margin-top: 2rem; font-size: 0.75rem; letter-spacing: 0.14em;
  text-transform: uppercase; color: #999;
}

@media print {
  .page { max-width: none; padding: 0; font-size: 11pt; }
  .badge { background: none; color: #0f1216; border: 1px solid #0f1216; }
  .lien-pdf { display: none; }
  .fraicheur { background: none; }
  .arrets li { break-inside: avoid; }
}
</style>
