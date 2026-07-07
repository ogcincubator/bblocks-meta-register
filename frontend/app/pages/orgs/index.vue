<template>
  <v-container class="py-8">
    <v-breadcrumbs :items="[{ title: 'Home', to: '/' }, { title: 'Organizations' }]" />

    <h1 class="text-3xl mb-4">
      Organizations
    </h1>

    <v-alert
      v-if="error"
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
        v-for="org in orgs"
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
  </v-container>
</template>

<script lang="ts" setup>
  import type { OrgSummary } from '~/types/api'

  const { data: orgs, status, error } = useApi<OrgSummary[]>('/orgs')
</script>
