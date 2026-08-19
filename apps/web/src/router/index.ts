import { createRouter, createWebHistory } from 'vue-router'
import LoginPage from '@/pages/LoginPage.vue'
import HomePage from '@/pages/HomePage.vue'

export const router = createRouter({
  history: createWebHistory(import.meta.env.VITE_SPA_BASE || '/'),
  routes: [
    { path: '/', name: 'home', component: HomePage },
    { path: '/login', name: 'login', component: LoginPage },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
