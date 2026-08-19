import { createRouter, createWebHistory } from 'vue-router'
import LoginPage from '@/pages/LoginPage.vue'
import HomePage from '@/pages/HomePage.vue'

export const router = createRouter({
  history: createWebHistory(import.meta.env.VITE_SPA_BASE || '/'),
  routes: [
    { path: '/', name: 'home', component: HomePage },
    {
      path: '/dashboard',
      name: 'dashboard',
      // 路由级代码分割：ECharts 重依赖仅在看板页按需加载
      component: () => import('@/pages/DashboardPage.vue'),
    },
    {
      path: '/logistics',
      name: 'logistics',
      component: () => import('@/pages/LogisticsPage.vue'),
    },
    { path: '/login', name: 'login', component: LoginPage },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
