<template>
  <v-container class="py-8">
    <v-breadcrumbs
      :items="[
        { title: 'Home', to: '/' },
        { title: 'Organizations', to: '/orgs' },
        { title: orgId },
      ]"
    />

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
    >
      Could not load organization: {{ error.message }}
    </v-alert>

    <template v-else-if="status === 'pending'">
      <v-skeleton-loader type="article" />
    </template>

    <template v-else-if="org">
      <h1 class="text-3xl mb-1">
        {{ org.name }}
      </h1>

      <a
        v-if="org.url"
        class="opacity-70"
        :href="org.url"
        rel="noopener"
        target="_blank"
      >{{ org.url }}</a>

      <p class="text-base mt-4">
        {{ org.description }}
      </p>

      <v-list
        v-if="org.maintainers.length > 0"
        class="mb-6"
        density="compact"
      >
        <v-list-subheader>Maintainers</v-list-subheader>

        <v-list-item
          v-for="(m, i) in org.maintainers"
          :key="i"
          prepend-icon="mdi-account"
          :subtitle="m.github && m.email ? m.email : undefined"
          :title="m.github || m.email || 'Unknown'"
        />
      </v-list>

      <v-divider class="mb-6" />

      <h2 class="text-2xl mb-4">
        Registers
      </h2>

      <v-list>
        <v-list-item
          v-for="register in org.registers"
          :key="register.id"
          lines="two"
          :subtitle="register.register_url"
          :title="register.name"
          :to="`/registers/${register.id}`"
        />
      </v-list>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import type { OrgDetail } from '~/types/api'

  const route = useRoute()
  const orgId = route.params.org as string

  const { data: org, status, error } = useApi<OrgDetail>(`/orgs/${orgId}`)
</script>
