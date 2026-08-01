import { ref, computed, watch } from 'vue'
import { api } from '../api/client'
import { useActiveProject } from './useActiveProject'

/**
 * Socle commun aux deux écrans « Parcours » (matériel et techniciens), ajoutés
 * le 2026-07-30 à la demande de Samuel : voir le cheminement de chaque
 * ressource sur toute la durée de la production.
 *
 * Ce que le composable prend en charge :
 *  - le chargement de la liste sélectionnable et du parcours lui-même ;
 *  - la sélection (cases à cocher, plusieurs à la fois) ;
 *  - le découpage du projet en journées et la position d'un instant dans la
 *    journée choisie.
 *
 * Ce qu'il laisse à chaque vue : le rendu des barres, qui n'a rien à voir
 * d'une page à l'autre (séjours par lieu d'un côté, engagements de l'autre).
 *
 * Affichage jour par jour (2026-07-31, demande de Samuel : « comme le
 * dashboard principal, avec des boutons de filtre pour sélectionner la
 * journée »). Le Dashboard affiche chaque jour de la semaine sur sa PROPRE
 * ligne avec un axe horaire ; ici les lignes sont déjà prises par les
 * ressources (matériel/technicien) pour pouvoir les comparer entre elles, donc
 * on ne peut pas faire pareil. À la place : une seule journée à la fois,
 * choisie via des puces, appliquée à toutes les lignes en même temps — chaque
 * piste devient un axe 0h→24h, même esprit visuel qu'une ligne du Dashboard.
 * Avant ce changement, l'axe couvrait tout le projet en jours ; ce
 * découpage-là (`ticks`) a disparu, remplacé par `days` (le sélecteur) et
 * `hourMarks` (l'axe de la journée choisie).
 */
export function useParcours({ endpoint, itemsKey, listEndpoint, listParam }) {
  const { activeProjectId } = useActiveProject()

  const options = ref([])
  const selectedIds = ref([])
  const rows = ref([])
  const window_ = ref(null)
  const loading = ref(false)
  const loadError = ref(null)

  async function loadOptions() {
    if (!activeProjectId.value) return
    const data = await api.get(listEndpoint, { project: activeProjectId.value })
    options.value = Array.isArray(data) ? data : (data.results ?? [])
    // Sélection de départ : les 5 premiers, pour que l'écran ne soit pas vide
    // à l'ouverture sans pour autant afficher 200 lignes.
    if (selectedIds.value.length === 0) {
      selectedIds.value = options.value.slice(0, 5).map((o) => o.id)
    }
  }

  async function loadParcours() {
    if (!activeProjectId.value) return
    if (selectedIds.value.length === 0) {
      rows.value = []
      return
    }
    loading.value = true
    loadError.value = null
    try {
      const data = await api.get(`/projects/${activeProjectId.value}/${endpoint}/`, {
        [listParam]: selectedIds.value.join(','),
      })
      window_.value = data.window
      rows.value = data[itemsKey] ?? []
    } catch (e) {
      loadError.value = e
    } finally {
      loading.value = false
    }
  }

  async function reload() {
    await loadOptions()
    await loadParcours()
  }

  watch(activeProjectId, reload, { immediate: true })
  watch(selectedIds, loadParcours)

  function toggle(id) {
    selectedIds.value = selectedIds.value.includes(id)
      ? selectedIds.value.filter((other) => other !== id)
      : [...selectedIds.value, id]
  }

  /**
   * « Tout » sélectionne ce qui est VISIBLE, pas tout le catalogue : sur le
   * parcours matériel, un filtre par catégorie est appliqué en amont et
   * cocher 200 items alors qu'on en regarde 12 n'aurait aucun sens.
   * `visible` est optionnel — sans lui, on retombe sur toutes les options.
   */
  function selectAll(visible = null) {
    // Garde-fou : un `@click="selectAll"` sans parenthèses passerait
    // l'événement de clic ici. On n'accepte qu'un vrai tableau.
    const liste = Array.isArray(visible) ? visible : options.value
    selectedIds.value = liste.map((o) => o.id)
  }

  function selectNone() {
    selectedIds.value = []
  }

  // --- Fenêtre globale du projet (pour la liste des jours sélectionnables) ---

  const bounds = computed(() => {
    if (!window_.value) return null
    const start = new Date(window_.value.start).getTime()
    const end = new Date(window_.value.end).getTime()
    return end > start ? { start, end, span: end - start } : null
  })

  const dayFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })

  /** Clé stable 'YYYY-MM-DD' en heure locale (pas `toISOString`, qui bascule en UTC). */
  function dayKey(date) {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  }

  /** Une entrée par jour calendaire couvert par le projet, pour les puces de sélection. */
  const days = computed(() => {
    if (!bounds.value) return []
    const liste = []
    const curseur = new Date(bounds.value.start)
    curseur.setHours(0, 0, 0, 0)
    const finTime = bounds.value.end
    while (curseur.getTime() < finTime) {
      liste.push({ key: dayKey(curseur), date: new Date(curseur), label: dayFmt.format(curseur) })
      curseur.setDate(curseur.getDate() + 1)
    }
    return liste
  })

  const selectedDayKey = ref(null)

  // Choix par défaut : aujourd'hui si le projet le couvre, sinon le premier
  // jour — et on ne retombe sur un défaut que si la sélection actuelle sort
  // de la liste (nouveau projet, par ex.), pas à chaque rechargement.
  watch(days, (liste) => {
    if (liste.length === 0) {
      selectedDayKey.value = null
      return
    }
    if (selectedDayKey.value && liste.some((j) => j.key === selectedDayKey.value)) return
    const aujourdhui = dayKey(new Date())
    selectedDayKey.value = liste.some((j) => j.key === aujourdhui) ? aujourdhui : liste[0].key
  }, { immediate: true })

  function selectDay(key) {
    selectedDayKey.value = key
  }

  /** Passe au jour précédent/suivant de la liste (bornée, pas de bouclage). */
  function stepDay(delta) {
    const liste = days.value
    const index = liste.findIndex((j) => j.key === selectedDayKey.value)
    if (index === -1) return
    const suivant = liste[index + delta]
    if (suivant) selectedDayKey.value = suivant.key
  }

  // --- Positionnement dans la journée choisie ---

  const dayBounds = computed(() => {
    if (!selectedDayKey.value) return null
    const [y, m, d] = selectedDayKey.value.split('-').map(Number)
    const start = new Date(y, m - 1, d, 0, 0, 0, 0).getTime()
    const end = new Date(y, m - 1, d + 1, 0, 0, 0, 0).getTime()
    return { start, end, span: end - start }
  })

  /** Position (0-100 %) d'un instant dans la journée choisie, bornée aux extrémités. */
  function pct(iso) {
    if (!dayBounds.value || !iso) return 0
    const t = new Date(iso).getTime()
    return Math.min(100, Math.max(0, ((t - dayBounds.value.start) / dayBounds.value.span) * 100))
  }

  /** Un segment déborde-t-il, même partiellement, de la journée choisie ? */
  function overlapsDay(startIso, endIso) {
    if (!dayBounds.value || !startIso || !endIso) return false
    return new Date(endIso).getTime() > dayBounds.value.start
      && new Date(startIso).getTime() < dayBounds.value.end
  }

  /** Style `left`/`width` d'un segment, tronqué aux bornes de la journée. */
  function segmentStyle(startIso, endIso) {
    const left = pct(startIso)
    const width = Math.max(pct(endIso) - left, 0.6)
    return { left: `${left}%`, width: `${width}%` }
  }

  // Graduation fixe (0h→24h, un repère toutes les 2h) : contrairement à
  // l'ancien axe multi-jours, la journée choisie a toujours la même étendue,
  // pas besoin d'une granularité adaptative comme sur le Dashboard.
  const hourMarks = computed(() => {
    if (!dayBounds.value) return []
    const marques = []
    for (let h = 0; h <= 24; h += 2) {
      marques.push({ key: h, label: `${String(h).padStart(2, '0')}h`, left: `${(h / 24) * 100}%` })
    }
    return marques
  })

  return {
    options,
    selectedIds,
    rows,
    window: window_,
    bounds,
    loading,
    loadError,
    days,
    selectedDayKey,
    selectDay,
    stepDay,
    hourMarks,
    overlapsDay,
    toggle,
    selectAll,
    selectNone,
    pct,
    segmentStyle,
    reload,
  }
}
