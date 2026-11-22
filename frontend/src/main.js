import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { useAuthStore } from '@/stores/auth'
import { useEventsStore } from '@/stores/events'
import './style.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)

// One shared event socket for the whole app; it feeds all stores.
const events = useEventsStore()
useAuthStore()
  .fetchInfo()
  .catch(() => {})
events.start()

app.mount('#app')
