<template>
  <v-list-item
    lines="two"
    :to="`/orgs/${bblock.register_id.split('/')[0]}/registers/${bblock.register_id.split('/')[1]}/bblocks/${bblock.id}`"
  >
    <template #title>
      <div class="flex flex-col sm:flex-row sm:gap-2 truncate">
        <span class="font-medium truncate">{{ bblock.name }}</span>
        <span class="opacity-70 text-sm truncate">{{ bblock.id }}</span>
      </div>
    </template>

    <template #subtitle>
      {{ bblock.abstract }}
    </template>

    <template #append>
      <div class="flex items-center gap-2">
        <div class="hidden sm:flex items-center gap-2">
          <v-icon
            v-if="bblock.has_schema"
            icon="mdi-code-json"
            size="small"
            title="Has schema"
          />

          <v-icon
            v-if="bblock.has_ld_context"
            icon="mdi-vector-link"
            size="small"
            title="Has JSON-LD context"
          />

          <v-icon
            v-if="bblock.has_shacl_shapes"
            icon="mdi-shape-outline"
            size="small"
            title="Has SHACL shapes"
          />

          <v-chip
            v-if="bblock.item_class"
            size="small"
            variant="outlined"
          >
            {{ bblock.item_class }}
          </v-chip>
        </div>

        <StatusChip :status="bblock.status" />
      </div>
    </template>
  </v-list-item>
</template>

<script lang="ts" setup>
import type { BblockSummary } from '~/types/api';

defineProps<{ bblock: BblockSummary }>();
</script>
