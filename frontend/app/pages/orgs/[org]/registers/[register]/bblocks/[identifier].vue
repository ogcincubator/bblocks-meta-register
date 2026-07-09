<template>
  <v-container class="py-8">
    <v-breadcrumbs
      :items="[
        { title: 'Home', to: '/' },
        { title: 'Organizations', to: '/orgs' },
        { title: orgId, to: `/orgs/${orgId}` },
        { title: registerName, to: `/orgs/${orgId}/registers/${registerName}` },
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
      <div class="flex items-center flex-wrap gap-2 mb-1">
        <h1 class="text-3xl">
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
        class="opacity-70 no-underline"
        :to="registerLink"
      >
        {{ bblock.register_id }}
      </NuxtLink>

      <p class="text-xs opacity-70 mb-4">
        {{ bblock.id }}
      </p>

      <div
        v-if="bblockViewerUrl"
        class="mb-4"
      >
        <v-btn
          :href="bblockViewerUrl"
          prepend-icon="mdi-open-in-new"
          rel="noopener"
          size="small"
          target="_blank"
          variant="tonal"
        >
          Open in bblocks-viewer
        </v-btn>
      </div>

      <MarkdownText
        v-if="bblock.abstract"
        class="text-base mb-4"
        :text="bblock.abstract"
      />

      <div
        v-if="bblock.tags.length > 0"
        class="flex flex-wrap gap-2 mb-6"
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

      <h2 class="text-base font-medium mb-2">
        Assets
      </h2>

      <div class="flex flex-wrap gap-2 mb-6">
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
          class="opacity-70"
        >No schema, context, or shapes published.</span>
      </div>

      <template v-if="bblock.sources.length > 0">
        <h2 class="text-base font-medium mb-2">
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

      <template v-if="bblock.depends_on.length > 0 || bblock.dependents.length > 0">
        <h2 class="text-base font-medium mb-2">
          Dependencies
        </h2>

        <DependencyGraph
          :center-id="identifier"
          :graph="graph"
          node-type="bblock"
        />
      </template>

      <v-divider class="my-6" />

      <div class="text-xs opacity-70">
        Added {{ bblock.date_time_addition || '—' }} · Last changed {{ bblock.date_of_last_change || '—' }}
      </div>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
import type { BblockDetail, DependencyGraph as DependencyGraphData, RegisterSummary } from '~/types/api';

const route = useRoute();
const orgId = route.params.org as string;
const registerName = route.params.register as string;
const identifier = route.params.identifier as string;

const { data: bblock, status, error } = useApi<BblockDetail>(`/bblocks/${identifier}`);
const { data: graph } = useApi<DependencyGraphData>(`/bblocks/${identifier}/graph`, { query: { depth: 2 } });
const { data: registers } = useApi<RegisterSummary[]>('/registers', { query: { org: orgId } });

const bblockViewerUrl = computed(() => {
  const registerId = bblock.value?.register_id;
  const viewerUrl = registers.value?.find(r => r.id === registerId)?.viewer_url;
  return viewerUrl ? `${viewerUrl.replace(/\/$/, '')}/bblock/${identifier}` : null;
});

const registerLink = computed(() => {
  const [org, register] = (bblock.value?.register_id ?? '').split('/');
  return `/orgs/${org}/registers/${register}`;
});

useHead({ title: () => bblock.value?.name ?? identifier });
</script>
