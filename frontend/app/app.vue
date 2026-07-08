<template>
  <v-app>
    <v-app-bar>
      <v-app-bar-title>
        <NuxtLink
          class="flex items-center gap-3 no-underline"
          to="/"
        >
          <img
            alt="OGC"
            class="h-7 w-auto shrink-0 dark:brightness-0 dark:invert"
            src="~/assets/images/ogc-logo.svg"
          >
          OGC Building Blocks Meta-Registry
        </NuxtLink>
      </v-app-bar-title>

      <v-text-field
        v-model="query"
        class="mx-4 md:grid"
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
        class="md:hidden"
        icon="mdi-magnify"
        to="/search"
      />

      <v-btn
        class="md:hidden"
        icon="mdi-domain"
        to="/orgs"
      />

      <v-btn
        class="hidden md:flex"
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
