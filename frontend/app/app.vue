<template>
  <v-app>
    <v-app-bar>
      <v-app-bar-title>
        <NuxtLink
          class="text-decoration-none text-high-emphasis"
          to="/"
        >
          OGC Building Blocks Meta-Registry
        </NuxtLink>
      </v-app-bar-title>

      <v-text-field
        v-model="query"
        class="mx-4"
        density="compact"
        flat
        hide-details
        placeholder="Search bblocks…"
        prepend-inner-icon="mdi-magnify"
        single-line
        style="max-width: 480px"
        variant="solo-filled"
        @keyup.enter="runSearch"
      />

      <v-btn
        to="/orgs"
        variant="text"
      >
        Organizations
      </v-btn>

      <v-btn
        icon="mdi-theme-light-dark"
        @click="$vuetify.theme.cycle()"
      />
    </v-app-bar>

    <v-main>
      <nuxt-page />
    </v-main>
  </v-app>
</template>

<script lang="ts" setup>
  const query = ref('')
  const router = useRouter()

  function runSearch () {
    if (!query.value.trim()) return
    router.push({ path: '/search', query: { q: query.value } })
  }
</script>
