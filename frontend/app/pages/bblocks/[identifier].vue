<template>
  <v-container class="py-8">
    <v-breadcrumbs
      :items="[
        { title: 'Home', to: '/' },
        { title: 'Organizations', to: '/orgs' },
        { title: identifier },
      ]"
    />

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
    >
      Could not load bblock: {{ error.message }}
    </v-alert>

    <template v-else-if="status === 'pending'">
      <v-skeleton-loader type="article" />
    </template>

    <template v-else-if="bblock">
      <div class="d-flex align-center flex-wrap ga-2 mb-1">
        <h1 class="text-h4">
          {{ bblock.name }}
        </h1>

        <StatusChip :status="bblock.status" />

        <v-chip
          v-if="bblock.item_class"
          size="small"
          variant="outlined"
        >
          {{ bblock.item_class }}
        </v-chip>

        <v-chip
          v-if="bblock.version"
          size="small"
          variant="text"
        >
          v{{ bblock.version }}
        </v-chip>
      </div>

      <NuxtLink
        class="text-medium-emphasis text-decoration-none"
        :to="`/registers/${bblock.register_id}`"
      >
        {{ bblock.register_id }}
      </NuxtLink>

      <p class="text-caption text-medium-emphasis mb-4">
        {{ bblock.id }}
      </p>

      <p
        v-if="bblock.abstract"
        class="text-body-1 mb-4"
      >
        {{ bblock.abstract }}
      </p>

      <div
        v-if="bblock.tags.length > 0"
        class="d-flex flex-wrap ga-2 mb-6"
      >
        <v-chip
          v-for="tag in bblock.tags"
          :key="tag"
          size="small"
          variant="tonal"
        >
          {{ tag }}
        </v-chip>
      </div>

      <h2 class="text-subtitle-1 mb-2">
        Assets
      </h2>

      <div class="d-flex flex-wrap ga-2 mb-6">
        <template
          v-for="(url, name) in bblock.schema_urls"
          :key="`schema-${name}`"
        >
          <v-btn
            :href="url"
            prepend-icon="mdi-code-json"
            rel="noopener"
            size="small"
            target="_blank"
            variant="tonal"
          >
            Schema ({{ name }})
          </v-btn>
        </template>

        <v-btn
          v-if="bblock.ld_context_url"
          :href="bblock.ld_context_url"
          prepend-icon="mdi-vector-link"
          rel="noopener"
          size="small"
          target="_blank"
          variant="tonal"
        >
          JSON-LD context
        </v-btn>

        <v-btn
          v-for="(url, i) in bblock.shacl_shapes_urls"
          :key="`shacl-${i}`"
          :href="url"
          prepend-icon="mdi-shape-outline"
          rel="noopener"
          size="small"
          target="_blank"
          variant="tonal"
        >
          SHACL shape {{ bblock.shacl_shapes_urls.length > 1 ? i + 1 : '' }}
        </v-btn>

        <span
          v-if="Object.keys(bblock.schema_urls).length === 0 && !bblock.ld_context_url && bblock.shacl_shapes_urls.length === 0"
          class="text-medium-emphasis"
        >No schema, context, or shapes published.</span>
      </div>

      <template v-if="bblock.sources.length > 0">
        <h2 class="text-subtitle-1 mb-2">
          Sources
        </h2>

        <v-list
          class="mb-6"
          density="compact"
        >
          <v-list-item
            v-for="(source, i) in bblock.sources"
            :key="i"
            :href="source.link"
            prepend-icon="mdi-book-open-variant"
            rel="noopener"
            target="_blank"
            :title="source.title || source.link"
          />
        </v-list>
      </template>

      <v-row v-if="bblock.depends_on.length > 0 || bblock.dependents.length > 0">
        <v-col
          v-if="bblock.depends_on.length > 0"
          cols="12"
          md="6"
        >
          <h2 class="text-subtitle-1 mb-2">
            Depends on
          </h2>

          <div class="d-flex flex-wrap ga-2">
            <v-chip
              v-for="dep in bblock.depends_on"
              :key="dep.id"
              size="small"
              :to="`/bblocks/${dep.id}`"
            >
              {{ dep.id }}
              <template #append>
                <span class="text-caption ml-1">({{ dep.kind }})</span>
              </template>
            </v-chip>
          </div>
        </v-col>

        <v-col
          v-if="bblock.dependents.length > 0"
          cols="12"
          md="6"
        >
          <h2 class="text-subtitle-1 mb-2">
            Depended on by
          </h2>

          <div class="d-flex flex-wrap ga-2">
            <v-chip
              v-for="dep in bblock.dependents"
              :key="dep.id"
              size="small"
              :to="`/bblocks/${dep.id}`"
            >
              {{ dep.id }}
              <template #append>
                <span class="text-caption ml-1">({{ dep.kind }})</span>
              </template>
            </v-chip>
          </div>
        </v-col>
      </v-row>

      <v-divider class="my-6" />

      <div class="text-caption text-medium-emphasis">
        Added {{ bblock.date_time_addition || '—' }} · Last changed {{ bblock.date_of_last_change || '—' }}
      </div>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import type { BblockDetail } from '~/types/api'

  const route = useRoute()
  const identifier = route.params.identifier as string

  const { data: bblock, status, error } = useApi<BblockDetail>(`/bblocks/${identifier}`)
</script>
