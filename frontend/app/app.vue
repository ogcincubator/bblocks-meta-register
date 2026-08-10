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

    <v-footer
      border
      class="flex-col gap-2 py-4"
    >
      <div class="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm">
        <a
          class="inline-flex items-center gap-1 opacity-70 no-underline hover:opacity-100"
          :href="`${apiBase}/docs`"
          rel="noopener"
          target="_blank"
        >
          <v-icon
            icon="mdi-api"
            size="16"
          />
          REST API
        </a>

        <a
          class="inline-flex items-center gap-1 opacity-70 no-underline hover:opacity-100"
          :href="`${apiBase}/mcp`"
          rel="noopener"
          target="_blank"
        >
          <v-icon
            icon="mdi-robot-outline"
            size="16"
          />
          MCP server
        </a>

        <a
          class="inline-flex items-center gap-1 opacity-70 no-underline hover:opacity-100"
          href="https://github.com/ogcincubator/bblocks-meta-register"
          rel="noopener"
          target="_blank"
        >
          <v-icon
            icon="mdi-github"
            size="16"
          />
          GitHub
        </a>
      </div>

      <div class="text-xs opacity-50">
        Free to reuse — REST API and MCP server open to any client, no key required.
      </div>
    </v-footer>
  </v-app>
</template>

<script lang="ts" setup>
useHead({
  titleTemplate: titleChunk => titleChunk
    ? `${titleChunk} · OGC Building Blocks Meta-Registry`
    : 'OGC Building Blocks Meta-Registry',
});

const query = ref('');
const router = useRouter();
const apiBase = useRuntimeConfig().public.apiBase;

function runSearch() {
  if (!query.value.trim()) {
    return;
  }
  router.push({ path: '/search', query: { q: query.value } });
}
</script>
