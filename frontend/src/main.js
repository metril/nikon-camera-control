import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { useAuthStore } from '@/stores/auth'
import { useEventsStore } from '@/stores/events'
import './style.css'

const app = createApp(App)
app.use(createPinia())

// One shared event socket for the whole app; it feeds all stores.
useAuthStore()
  .fetchInfo()
  .catch(() => {})
useEventsStore().start()

app.mount('#app')
