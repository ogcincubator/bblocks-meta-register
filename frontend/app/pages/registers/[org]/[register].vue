<template>
  <v-container class="py-8">
    <v-breadcrumbs
      :items="[
        { title: 'Home', to: '/' },
        { title: 'Organizations', to: '/orgs' },
        { title: orgId, to: `/orgs/${orgId}` },
        { title: registerName },
      ]"
    />

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
    >
      Could not load register: {{ error.message }}
    </v-alert>

    <template v-else-if="status === 'pending'">
      <v-skeleton-loader type="article" />
    </template>

    <template v-else-if="register">
      <h1 class="text-3xl mb-1">
        {{ register.name }}
      </h1>

      <p class="opacity-70 mb-4">
        {{ register.org_id }}
      </p>

      <p
        v-if="register.description"
        class="text-base mb-4"
      >
        {{ register.description }}
      </p>

      <div class="flex flex-wrap gap-2 mb-6">
        <v-btn
          :href="register.register_url"
          prepend-icon="mdi-file-code-outline"
          rel="noopener"
          size="small"
          target="_blank"
          variant="tonal"
        >
          register.json
        </v-btn>

        <v-btn
          v-if="register.viewer_url"
          :href="register.viewer_url"
          prepend-icon="mdi-open-in-new"
          rel="noopener"
          size="small"
          target="_blank"
          variant="tonal"
        >
          Open in bblocks-viewer
        </v-btn>
      </div>

      <v-card
        class="mb-6"
        variant="outlined"
      >
        <v-card-text class="flex flex-wrap gap-6">
          <div>
            <div class="text-xs opacity-70">
              Last crawled
            </div>

            <div>{{ register.last_crawled_at ? new Date(register.last_crawled_at).toLocaleString() : '—' }}</div>
          </div>

          <div>
            <div class="text-xs opacity-70">
              Crawl status
            </div>

            <div>{{ register.last_crawl_status || '—' }}</div>
          </div>

          <div>
            <div class="text-xs opacity-70">
              Modified
            </div>

            <div>{{ register.modified || '—' }}</div>
          </div>
        </v-card-text>
      </v-card>

      <template v-if="register.depends_on.length > 0 || register.dependents.length > 0">
        <h3 class="text-base font-medium mb-2">
          Register dependencies
        </h3>

        <DependencyGraph
          :center-id="`${orgId}/${registerName}`"
          class="mb-6"
          :graph="graph"
          node-type="register"
        />

        <v-divider class="mb-6" />
      </template>

      <h2 class="text-2xl mb-4">
        Building Blocks ({{ register.bblocks.length }})
      </h2>

      <v-list v-if="register.bblocks.length > 0">
        <BblockListItem
          v-for="bblock in register.bblocks"
          :key="bblock.id"
          :bblock="bblock"
        />
      </v-list>

      <p
        v-else
        class="opacity-70"
      >
        No building blocks indexed for this register yet.
      </p>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import type { DependencyGraph as DependencyGraphData, RegisterDetail } from '~/types/api'

  const route = useRoute()
  const orgId = route.params.org as string
  const registerName = route.params.register as string

  const { data: register, status, error } = useApi<RegisterDetail>(`/registers/${orgId}/${registerName}`)
  const { data: graph } = useApi<DependencyGraphData>(`/registers/${orgId}/${registerName}/graph`, { query: { depth: 2 } })

  useHead({ title: () => register.value?.name ?? registerName })
</script>
