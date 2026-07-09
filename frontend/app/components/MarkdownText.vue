<template>
  <div
    class="markdown-content"
    v-html="html"
  />
</template>

<script lang="ts" setup>
const props = defineProps<{ text: string | null | undefined }>();

const { renderMarkdown } = useMarkdown();
const html = computed(() => props.text ? renderMarkdown(props.text) : '');
</script>

<style scoped>
.markdown-content :deep(p) {
  margin-bottom: 0.75rem;
}

.markdown-content :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(a) {
  color: rgb(var(--v-theme-primary));
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 1.25rem;
  margin-bottom: 0.75rem;
}

.markdown-content :deep(code) {
  background: rgba(128, 128, 128, 0.15);
  padding: 0.1em 0.3em;
  border-radius: 4px;
  font-size: 0.9em;
}

.markdown-content :deep(pre) {
  background: rgba(128, 128, 128, 0.15);
  padding: 0.75rem;
  border-radius: 6px;
  overflow-x: auto;
}

.markdown-content :deep(pre) code {
  background: none;
  padding: 0;
}
</style>
