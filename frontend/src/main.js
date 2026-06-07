import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'

import Dashboard from './views/Dashboard.vue'
import ProjectDetail from './views/ProjectDetail.vue'
import Settings from './views/Settings.vue'
import Login from './views/Login.vue'

const routes = [
  { path: '/login', name: 'Login', component: Login, meta: { guest: true } },
  { path: '/', name: 'Dashboard', component: Dashboard },
  { path: '/project/:name', name: 'ProjectDetail', component: ProjectDetail },
  { path: '/settings', name: 'Settings', component: Settings },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局导航守卫：未登录时跳转到登录页
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('auth_token')
  if (to.meta.guest) {
    // 登录页：已登录则跳回首页
    if (token) return next('/')
    return next()
  }
  // 其他页面：未登录则跳转登录页
  if (!token) return next('/login')
  next()
})

const app = createApp(App)
app.use(router)
app.mount('#app')
