<template>
  <v-list-item
    lines="two"
    :to="`/bblocks/${bblock.id}`"
  >
    <template #title>
      <span class="font-weight-medium">{{ bblock.name }}</span>
      <span class="text-medium-emphasis text-body-2 ml-2">{{ bblock.id }}</span>
    </template>

    <template #subtitle>
      {{ bblock.abstract }}
    </template>

    <template #append>
      <div class="d-flex align-center ga-2">
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

        <StatusChip :status="bblock.status" />
      </div>
    </template>
  </v-list-item>
</template>

<script lang="ts" setup>
  import type { BblockSummary } from '~/types/api'

  defineProps<{ bblock: BblockSummary }>()
</script>
