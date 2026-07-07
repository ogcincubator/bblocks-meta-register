<template>
  <v-container class="py-8">
    <div class="text-center py-8">
      <h1 class="text-h3 font-weight-bold mb-2">
        Find OGC Building Blocks
      </h1>

      <p class="text-medium-emphasis mb-6">
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

    <div class="d-flex align-center justify-space-between mb-4">
      <h2 class="text-h5">
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

          <v-card-text class="text-medium-emphasis">
            {{ org.description || 'No description available.' }}
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script lang="ts" setup>
  import type { OrgSummary } from '~/types/api'

  const query = ref('')
  const router = useRouter()

  const { data: orgs, status, error } = useApi<OrgSummary[]>('/orgs')

  function runSearch () {
    if (!query.value.trim()) return
    router.push({ path: '/search', query: { q: query.value } })
  }
</script>
