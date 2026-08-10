<template>
  <v-container class="py-8">
    <div class="text-center py-8">
      <h1 class="text-4xl font-bold mb-2">
        Find OGC Building Blocks
      </h1>

      <p class="opacity-70 mb-6">
        Search across every register known to the OGC Building Blocks meta-registry.
      </p>

      <v-form
        class="mx-auto"
        style="max-width: 640px"
        @submit.prevent="runSearch"
      >
        <v-text-field
          v-model="query"
          density="comfortable"
          hide-details
          placeholder="Search by name, identifier, tag…"
          prepend-inner-icon="mdi-magnify"
          variant="solo"
          @keyup.enter="runSearch"
        />
      </v-form>
    </div>

    <v-divider class="mb-6" />

    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl">
        Organizations
      </h2>

      <v-btn
        append-icon="mdi-arrow-right"
        to="/orgs"
        variant="text"
      >
        View all
      </v-btn>
    </div>

    <v-alert
      v-if="error"
      class="mb-4"
      type="error"
      variant="tonal"
    >
      Could not load organizations: {{ error.message }}
    </v-alert>

    <v-row v-if="status === 'pending'">
      <v-col
        v-for="n in 6"
        :key="n"
        cols="12"
        md="4"
        sm="6"
      >
        <v-skeleton-loader type="card" />
      </v-col>
    </v-row>

    <v-row v-else>
      <v-col
        v-for="org in orgs?.slice(0, 6)"
        :key="org.id"
        cols="12"
        md="4"
        sm="6"
      >
        <v-card
          height="100%"
          :to="`/orgs/${org.id}`"
          variant="outlined"
        >
          <v-card-title>{{ org.name }}</v-card-title>

          <v-card-text class="opacity-70">
            {{ org.description || 'No description available.' }}
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-divider class="my-10" />

    <div class="text-center mb-6">
      <h2 class="text-2xl mb-2">
        Build on this catalog
      </h2>

      <p class="opacity-70">
        This index is free to reuse — query it from your own app, script, or AI agent.
      </p>
    </div>

    <v-row>
      <v-col
        cols="12"
        sm="6"
      >
        <v-card
          :href="`${apiBase}/docs`"
          height="100%"
          rel="noopener"
          target="_blank"
          variant="outlined"
        >
          <v-card-item>
            <template #prepend>
              <v-icon
                icon="mdi-api"
                size="32"
              />
            </template>

            <v-card-title>REST API</v-card-title>
          </v-card-item>

          <v-card-text class="opacity-70">
            Browse the interactive Swagger docs and call the read-only, unauthenticated JSON
            API directly from your own code.
          </v-card-text>
        </v-card>
      </v-col>

      <v-col
        cols="12"
        sm="6"
      >
        <v-card
          :href="`${apiBase}/mcp`"
          height="100%"
          rel="noopener"
          target="_blank"
          variant="outlined"
        >
          <v-card-item>
            <template #prepend>
              <v-icon
                icon="mdi-robot-outline"
                size="32"
              />
            </template>

            <v-card-title>MCP server</v-card-title>
          </v-card-item>

          <v-card-text class="opacity-70">
            Point an MCP-compatible AI agent (Claude, etc.) at this endpoint to search and
            browse the catalog as tool calls.
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script lang="ts" setup>
import type { OrgSummary } from '~/types/api';

const query = ref('');
const router = useRouter();
const apiBase = useRuntimeConfig().public.apiBase;

const { data: orgs, status, error } = useApi<OrgSummary[]>('/orgs');

function runSearch() {
  if (!query.value.trim()) {
    return;
  }
  router.push({ path: '/search', query: { q: query.value } });
}
</script>
