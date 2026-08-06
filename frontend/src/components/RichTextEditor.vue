<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'

/**
 * Éditeur de texte riche pour les notes (2026-08-05, demande de Samuel :
 * « une zone de texte avec la possibilité de mettre du texte riche comme
 * inclure des liens »). Utilisé par la fiche spectacle et la fiche transport.
 *
 * ## Pourquoi TipTap plutôt qu'un `contenteditable` maison
 *
 * Un éditeur `document.execCommand` tient en une centaine de lignes, mais
 * dégrade précisément là où on ne le voit pas tout de suite : collage depuis
 * Word ou une page web, annulation (⌘Z) qui déborde du champ, listes
 * imbriquées, position du curseur après une commande. `execCommand` est aussi
 * déprécié, sans remplacement. TipTap gère tout ça et reste maintenu.
 *
 * ## La barre d'outils est calée sur ce que le backend accepte
 *
 * `inventory/rich_text.py` assainit les notes à l'écriture avec une liste
 * blanche. Les extensions que cette liste ne couvre PAS sont désactivées ici
 * (`horizontalRule`, `codeBlock`) et les niveaux de titre limités à 3-4 :
 * sinon l'éditeur produirait du contenu que l'enregistrement retirerait
 * silencieusement, ce qui donne l'impression d'avoir perdu son travail.
 *
 * Les protocoles de lien sont la même liste des deux côtés (`http`, `https`,
 * `mailto`, `tel`) — `javascript:` n'y est pas, c'est le vecteur classique.
 */

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const PROTOCOLES = ['http', 'https', 'mailto', 'tel']

const editor = useEditor({
  content: props.modelValue || '',
  extensions: [
    StarterKit.configure({
      // Voir la note de tête : tout ce que `clean_notes` retirerait est
      // désactivé ici plutôt que produit puis effacé à l'enregistrement.
      horizontalRule: false,
      codeBlock: false,
      heading: { levels: [3, 4] },
      link: {
        openOnClick: false,
        protocols: PROTOCOLES,
        HTMLAttributes: { rel: 'noopener noreferrer' },
      },
    }),
  ],
  onUpdate: ({ editor: instance }) => {
    // TipTap renvoie `<p></p>` pour un contenu vide : on émet une chaîne vide
    // à la place, sinon la carte Notes s'afficherait pour un paragraphe vide.
    emit('update:modelValue', instance.isEmpty ? '' : instance.getHTML())
  },
})

// Synchronisation descendante (annulation d'une édition, rechargement de la
// fiche) — sans la comparaison, réécrire le contenu à chaque frappe
// replacerait le curseur au début.
watch(() => props.modelValue, (valeur) => {
  const instance = editor.value
  if (!instance) return
  const actuel = instance.isEmpty ? '' : instance.getHTML()
  if ((valeur || '') === actuel) return
  instance.commands.setContent(valeur || '', { emitUpdate: false })
})

onBeforeUnmount(() => editor.value?.destroy())

// --- Lien ---
// Champ en ligne plutôt qu'un `window.prompt` : bloqué dans certains
// contextes, et impossible à styler ou à pré-remplir proprement.
const editingLink = ref(false)
const linkUrl = ref('')

function openLink() {
  const instance = editor.value
  if (!instance) return
  linkUrl.value = instance.getAttributes('link').href ?? ''
  editingLink.value = true
}

function applyLink() {
  const instance = editor.value
  if (!instance) return
  const url = linkUrl.value.trim()
  if (!url) {
    instance.chain().focus().extendMarkRange('link').unsetLink().run()
  } else {
    instance.chain().focus().extendMarkRange('link').setLink({ href: url }).run()
  }
  editingLink.value = false
}

function removeLink() {
  editor.value?.chain().focus().extendMarkRange('link').unsetLink().run()
  editingLink.value = false
}

function actif(nom, options) {
  return editor.value?.isActive(nom, options) ?? false
}
</script>

<template>
  <div v-if="editor" class="rte">
    <div class="rte__toolbar">
      <button
        type="button" class="rte__btn" :class="{ 'rte__btn--on': actif('bold') }"
        title="Gras" @click="editor.chain().focus().toggleBold().run()"
      ><strong>G</strong></button>
      <button
        type="button" class="rte__btn" :class="{ 'rte__btn--on': actif('italic') }"
        title="Italique" @click="editor.chain().focus().toggleItalic().run()"
      ><em>I</em></button>
      <button
        type="button" class="rte__btn" :class="{ 'rte__btn--on': actif('underline') }"
        title="Souligné" @click="editor.chain().focus().toggleUnderline().run()"
      ><u>S</u></button>

      <span class="rte__sep" />

      <button
        type="button" class="rte__btn" :class="{ 'rte__btn--on': actif('heading', { level: 3 }) }"
        title="Titre" @click="editor.chain().focus().toggleHeading({ level: 3 }).run()"
      >T</button>
      <button
        type="button" class="rte__btn" :class="{ 'rte__btn--on': actif('bulletList') }"
        title="Liste à puces" @click="editor.chain().focus().toggleBulletList().run()"
      >•</button>
      <button
        type="button" class="rte__btn" :class="{ 'rte__btn--on': actif('orderedList') }"
        title="Liste numérotée" @click="editor.chain().focus().toggleOrderedList().run()"
      >1.</button>
      <button
        type="button" class="rte__btn" :class="{ 'rte__btn--on': actif('blockquote') }"
        title="Citation" @click="editor.chain().focus().toggleBlockquote().run()"
      >❝</button>

      <span class="rte__sep" />

      <button
        type="button" class="rte__btn" :class="{ 'rte__btn--on': actif('link') }"
        title="Lien" @click="openLink"
      >🔗</button>
      <button
        v-if="actif('link')" type="button" class="rte__btn"
        title="Retirer le lien" @click="removeLink"
      >⛔</button>
    </div>

    <div v-if="editingLink" class="rte__link-row">
      <input
        v-model="linkUrl"
        class="fiche-input"
        placeholder="https://… (ou mailto:, tel:)"
        @keydown.enter.prevent="applyLink"
        @keydown.esc.prevent="editingLink = false"
      />
      <button type="button" class="fiche-btn fiche-btn--primary" @click="applyLink">Appliquer</button>
      <button type="button" class="fiche-btn" @click="editingLink = false">Annuler</button>
    </div>

    <EditorContent :editor="editor" class="rte__content rich-text" />
    <div v-if="placeholder" class="fiche-hint">{{ placeholder }}</div>
  </div>
</template>

<style scoped>
.rte {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rte__toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.rte__btn {
  border: 0;
  min-width: 30px;
  height: 28px;
  padding: 0 8px;
  border-radius: var(--radius-notch-sm);
  background: rgba(var(--fg-rgb), 0.08);
  color: rgba(var(--fg-rgb), 0.75);
  font: 600 12px system-ui;
  cursor: pointer;
}

.rte__btn--on {
  background: rgba(var(--accent-rgb), 0.25);
  color: var(--accent);
}

.rte__sep {
  width: 1px;
  height: 18px;
  background: rgba(var(--fg-rgb), 0.12);
  margin: 0 4px;
}

.rte__link-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rte__content {
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  padding: 10px 12px;
}

/* `:deep` : le contenu est rendu par TipTap dans un sous-arbre, hors de
   portée du `scoped`. */
.rte__content :deep(.ProseMirror) {
  outline: none;
  min-height: 90px;
}
</style>
