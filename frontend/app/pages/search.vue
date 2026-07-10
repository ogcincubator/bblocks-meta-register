<template>
  <v-container class="py-8">
    <v-breadcrumbs :items="[{ title: 'Home', to: '/' }, { title: 'Search' }]" />

    <h1 class="text-3xl mb-6">
      Search Building Blocks
    </h1>

    <v-form
      class="mb-2"
      @submit.prevent="applyFilters"
    >
      <v-row>
        <v-col
          cols="12"
          md
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
          md="3"
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

        <v-col
          class="d-flex align-center"
          cols="12"
          md="auto"
        >
          <v-btn
            aria-label="Search"
            class="hidden md:inline-flex"
            color="primary"
            size="x-large"
            type="submit"
            variant="flat"
          >
            <v-icon icon="mdi-magnify" />
          </v-btn>

          <v-btn
            block
            class="md:hidden"
            color="primary"
            prepend-icon="mdi-magnify"
            type="submit"
            variant="flat"
          >
            Search
          </v-btn>
        </v-col>
      </v-row>
    </v-form>

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
import type { BblockListResponse } from '~/types/api';

const route = useRoute();
const router = useRouter();

// Editable form state — not sent to the API until applyFilters() commits it.
const q = ref((route.query.q as string) ?? '');
const itemClass = ref((route.query.item_class as string) ?? null);
const statusFilter = ref((route.query.status as string) ?? null);

// Committed state that actually drives the search request.
const appliedQ = ref(q.value);
const appliedItemClass = ref(itemClass.value);
const appliedStatusFilter = ref(statusFilter.value);
const page = ref(Number(route.query.page) || 1);
const limit = 20;

const itemClassOptions = ['schema', 'datatype', 'api', 'model', 'requirements-class'];
const statusOptions = ['under-development', 'experimental', 'stable', 'superseded', 'retired'];

function applyFilters() {
  appliedQ.value = q.value;
  appliedItemClass.value = itemClass.value;
  appliedStatusFilter.value = statusFilter.value;
  page.value = 1;
}

const queryParams = computed(() => ({
  q: appliedQ.value || undefined,
  item_class: appliedItemClass.value || undefined,
  status: appliedStatusFilter.value || undefined,
  limit,
  offset: (page.value - 1) * limit,
}));

const { data, status: fetchStatus, error } = useApi<BblockListResponse>('/bblocks', { query: queryParams });

useHead({ title: 'Search' });

const pageCount = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.numberMatched / limit)) : 1));

watch([appliedQ, appliedItemClass, appliedStatusFilter, page], () => {
  router.replace({
    query: {
      ...(appliedQ.value ? { q: appliedQ.value } : {}),
      ...(appliedItemClass.value ? { item_class: appliedItemClass.value } : {}),
      ...(appliedStatusFilter.value ? { status: appliedStatusFilter.value } : {}),
      ...(page.value > 1 ? { page: page.value } : {}),
    },
  });
});
</script>
