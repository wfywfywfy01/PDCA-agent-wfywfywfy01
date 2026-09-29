import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './styles/tokens.css'
import './styles/ui.css'

async function start() {
  if (import.meta.env.MODE === 'omega-demo') {
    const { installOmegaDemo } = await import('./demo/omega-demo')
    installOmegaDemo()
    if (location.pathname === '/') history.replaceState(null, '', '/omega')
  }
  createApp(App).use(createPinia()).use(router).mount('#app')
}

void start()
