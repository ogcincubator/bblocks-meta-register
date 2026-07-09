<template>
  <v-container class="py-8">
    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
    >
      Could not load bblock: {{ error.message }}
    </v-alert>

    <v-skeleton-loader
      v-else
      type="article"
    />
  </v-container>
</template>

<script lang="ts" setup>
import type { BblockSummary } from '~/types/api';

const route = useRoute();
const identifier = route.params.identifier as string;

const { data: bblock, error } = await useApi<BblockSummary>(`/bblocks/${identifier}`);

if (bblock.value) {
  const [org, register] = bblock.value.register_id.split('/');
  await navigateTo(`/orgs/${org}/registers/${register}/bblocks/${identifier}`, { redirectCode: 301 });
}
</script>
