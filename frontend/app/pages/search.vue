<template>
  <v-container class="py-8">
    <v-breadcrumbs :items="[{ title: 'Home', to: '/' }, { title: 'Search' }]" />

    <h1 class="text-3xl mb-6">
      Search Building Blocks
    </h1>

    <v-row class="mb-2">
      <v-col
        cols="12"
        md="5"
      >
        <v-text-field
          v-model="q"
          clearable
          density="comfortable"
          hide-details
          label="Query"
          prepend-inner-icon="mdi-magnify"
          variant="outlined"
        />
      </v-col>

      <v-col
        cols="12"
        md="3"
        sm="6"
      >
        <v-select
          v-model="itemClass"
          clearable
          density="comfortable"
          hide-details
          :items="itemClassOptions"
          label="Type"
          variant="outlined"
        />
      </v-col>

      <v-col
        cols="12"
        md="4"
        sm="6"
      >
        <v-select
          v-model="statusFilter"
          clearable
          density="comfortable"
          hide-details
          :items="statusOptions"
          label="Status"
          variant="outlined"
        />
      </v-col>
    </v-row>

    <v-alert
      v-if="error"
      class="mb-4"
      type="error"
      variant="tonal"
    >
      Search failed: {{ error.message }}
    </v-alert>

    <v-progress-linear
      v-if="fetchStatus === 'pending'"
      class="mb-4"
      indeterminate
    />

    <template v-else-if="data">
      <p class="opacity-70 mb-4">
        {{ data.numberMatched }} result{{ data.numberMatched === 1 ? '' : 's' }}
      </p>

      <v-list v-if="data.items.length > 0">
        <BblockListItem
          v-for="bblock in data.items"
          :key="bblock.id"
          :bblock="bblock"
        />
      </v-list>

      <p
        v-else
        class="opacity-70"
      >
        No building blocks matched your search.
      </p>

      <div class="flex justify-center mt-6">
        <v-pagination
          v-if="pageCount > 1"
          v-model="page"
          :length="pageCount"
        />
      </div>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import type { BblockListResponse } from '~/types/api'

  const route = useRoute()
  const router = useRouter()

  const q = ref((route.query.q as string) ?? '')
  const itemClass = ref((route.query.item_class as string) ?? null)
  const statusFilter = ref((route.query.status as string) ?? null)
  const page = ref(Number(route.query.page) || 1)
  const limit = 20

  const itemClassOptions = ['schema', 'datatype', 'api', 'model', 'requirements-class']
  const statusOptions = ['under-development', 'experimental', 'stable', 'superseded', 'retired']

  const queryParams = computed(() => ({
    q: q.value || undefined,
    item_class: itemClass.value || undefined,
    status: statusFilter.value || undefined,
    limit,
    offset: (page.value - 1) * limit,
  }))

  const { data, status: fetchStatus, error } = useApi<BblockListResponse>('/bblocks', { query: queryParams })

  const pageCount = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.numberMatched / limit)) : 1))

  watch([q, itemClass, statusFilter], () => {
    page.value = 1
  })

  watch([q, itemClass, statusFilter, page], () => {
    router.replace({
      query: {
        ...(q.value ? { q: q.value } : {}),
        ...(itemClass.value ? { item_class: itemClass.value } : {}),
        ...(statusFilter.value ? { status: statusFilter.value } : {}),
        ...(page.value > 1 ? { page: page.value } : {}),
      },
    })
  })
</script>
