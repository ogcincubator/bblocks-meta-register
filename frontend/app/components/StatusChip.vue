<template>
  <v-chip
    v-if="status"
    :color="color"
    size="small"
    variant="tonal"
  >
    {{ status }}
  </v-chip>
</template>

<script lang="ts" setup>
const props = defineProps<{ status: string | null }>();

const colors: Record<string, string> = {
  'stable': 'success',
  'experimental': 'warning',
  'under-development': 'info',
  'superseded': 'default',
  'retired': 'error',
};

const color = computed(() => (props.status ? colors[props.status] ?? 'default' : 'default'));
</script>
