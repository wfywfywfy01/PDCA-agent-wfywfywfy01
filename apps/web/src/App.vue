<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue'
import { RouterView, useRouter } from 'vue-router'

const router = useRouter()
function requireLogin() {
  const current = router.currentRoute.value
  if (current.name !== 'login') router.replace({ path: '/login', query: { next: current.fullPath } })
}
onMounted(() => window.addEventListener('pdca-session-expired', requireLogin))
onBeforeUnmount(() => window.removeEventListener('pdca-session-expired', requireLogin))
</script>

<template>
  <RouterView />
</template>
