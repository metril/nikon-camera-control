import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { takePairCode, useAuthStore } from '@/stores/auth'
import { useEventsStore } from '@/stores/events'
import './style.css'

const app = createApp(App)
app.use(createPinia())

async function boot() {
  const auth = useAuthStore()
  // Kiosk pairing comes first: nothing else may load before the device has its session. On
  // failure the status below says "not authenticated" and the sign-in screen appears.
  const code = takePairCode()
  if (code) await auth.pairKiosk(code).catch(() => {})
  await auth.fetchStatus().catch(() => {})
  await auth.migrateLegacyKey()
  auth.fetchInfo().catch(() => {})
  // One shared event socket for the whole app; it feeds all stores.
  useEventsStore().start()
  app.mount('#app')
}
boot()
