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
      <h1 class="text-h4 mb-1">
        {{ register.name }}
      </h1>

      <p class="text-medium-emphasis mb-4">
        {{ register.org_id }}
      </p>

      <p
        v-if="register.description"
        class="text-body-1 mb-4"
      >
        {{ register.description }}
      </p>

      <div class="d-flex flex-wrap ga-2 mb-6">
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
        <v-card-text class="d-flex flex-wrap ga-6">
          <div>
            <div class="text-caption text-medium-emphasis">
              Last crawled
            </div>

            <div>{{ register.last_crawled_at ? new Date(register.last_crawled_at).toLocaleString() : '—' }}</div>
          </div>

          <div>
            <div class="text-caption text-medium-emphasis">
              Crawl status
            </div>

            <div>{{ register.last_crawl_status || '—' }}</div>
          </div>

          <div>
            <div class="text-caption text-medium-emphasis">
              Modified
            </div>

            <div>{{ register.modified || '—' }}</div>
          </div>
        </v-card-text>
      </v-card>

      <template v-if="register.depends_on.length > 0 || register.dependents.length > 0">
        <v-row class="mb-2">
          <v-col
            v-if="register.depends_on.length > 0"
            cols="12"
            md="6"
          >
            <h3 class="text-subtitle-1 mb-2">
              Depends on
            </h3>

            <div class="d-flex flex-wrap ga-2">
              <v-chip
                v-for="dep in register.depends_on"
                :key="dep.id"
                size="small"
                :to="`/registers/${dep.id}`"
              >
                {{ dep.id }}
              </v-chip>
            </div>
          </v-col>

          <v-col
            v-if="register.dependents.length > 0"
            cols="12"
            md="6"
          >
            <h3 class="text-subtitle-1 mb-2">
              Depended on by
            </h3>

            <div class="d-flex flex-wrap ga-2">
              <v-chip
                v-for="dep in register.dependents"
                :key="dep.id"
                size="small"
                :to="`/registers/${dep.id}`"
              >
                {{ dep.id }}
              </v-chip>
            </div>
          </v-col>
        </v-row>

        <v-divider class="mb-6" />
      </template>

      <h2 class="text-h5 mb-4">
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
        class="text-medium-emphasis"
      >
        No building blocks indexed for this register yet.
      </p>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import type { RegisterDetail } from '~/types/api'

  const route = useRoute()
  const orgId = route.params.org as string
  const registerName = route.params.register as string

  const { data: register, status, error } = useApi<RegisterDetail>(`/registers/${orgId}/${registerName}`)
</script>
