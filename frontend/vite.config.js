import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
//
// `base` dépend du mode (2026-08-xx, déploiement "option B" — Django sert le
// build via WhiteNoise, voir CLAUDE.md) : en dev (`vite`/`npm run dev`), le
// serveur Vite reste à la racine (`/`), inchangé. En build (`vite build`,
// utilisé par le Dockerfile de déploiement), les assets sont préfixés par
// `/static/` pour correspondre à STATIC_URL côté Django — `STATICFILES_DIRS`
// (config/settings.py) attend les fichiers construits sous ce préfixe.
export default defineConfig(({ command }) => ({
  plugins: [vue()],
  base: command === 'build' ? '/static/' : '/',
}))
