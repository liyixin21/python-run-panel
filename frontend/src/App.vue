<template>
  <Layout v-if="$route.name !== 'Login'">
    <router-view />
  </Layout>
  <router-view v-else />
</template>

<script setup>
import Layout from './components/Layout.vue'
</script>
