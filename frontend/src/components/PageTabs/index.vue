<script setup lang="ts">
import { computed } from "vue";

export type PageTabOption = {
  value: string;
  label: string;
  hint?: string;
  disabled?: boolean;
};

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    options?: PageTabOption[];
    size?: "small" | "default";
    /** 占满一行（数据浏览等） */
    stretch?: boolean;
    ariaLabel?: string;
  }>(),
  {
    modelValue: "",
    options: () => [],
    size: "default",
    stretch: false,
    ariaLabel: "切换"
  }
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
  change: [value: string];
}>();

const rich = computed(() => props.options.some(item => Boolean(item.hint)));

function select(item: PageTabOption) {
  if (item.disabled || item.value === props.modelValue) return;
  emit("update:modelValue", item.value);
  emit("change", item.value);
}
</script>

<template>
  <div
    class="page-tabs"
    :class="[
      `page-tabs--${size}`,
      {
        'page-tabs--stretch': stretch,
        'page-tabs--rich': rich
      }
    ]"
    role="tablist"
    :aria-label="ariaLabel"
  >
    <button
      v-for="item in options"
      :key="item.value"
      type="button"
      role="tab"
      class="page-tabs__item"
      :class="{ 'is-active': item.value === modelValue }"
      :aria-selected="item.value === modelValue"
      :disabled="item.disabled"
      @click="select(item)"
    >
      <span class="page-tabs__label">{{ item.label }}</span>
      <span v-if="item.hint" class="page-tabs__hint">{{ item.hint }}</span>
    </button>
  </div>
</template>

<style scoped>
.page-tabs {
  --page-tabs-pad-y: 3px;
  --page-tabs-pad-x: 3px;
  --page-tabs-gap: 2px;
  --page-tabs-radius: 10px;
  --page-tabs-item-radius: 8px;
  --page-tabs-item-pad-y: 6px;
  --page-tabs-item-pad-x: 14px;
  --page-tabs-font: 13px;

  display: inline-flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: var(--page-tabs-gap);
  max-width: 100%;
  padding: var(--page-tabs-pad-y) var(--page-tabs-pad-x);
  background: color-mix(
    in srgb,
    var(--el-fill-color-light) 88%,
    var(--el-bg-color)
  );
  border: 1px solid
    color-mix(in srgb, var(--el-border-color-lighter) 85%, transparent);
  border-radius: var(--page-tabs-radius);
  box-shadow: inset 0 1px 0
    color-mix(in srgb, var(--el-bg-color) 55%, transparent);
}

.page-tabs--small {
  --page-tabs-pad-y: 2px;
  --page-tabs-pad-x: 2px;
  --page-tabs-radius: 8px;
  --page-tabs-item-radius: 6px;
  --page-tabs-item-pad-y: 4px;
  --page-tabs-item-pad-x: 11px;
  --page-tabs-font: 12px;
}

.page-tabs--stretch {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  width: 100%;
}

.page-tabs--rich {
  --page-tabs-item-pad-y: 10px;
  --page-tabs-item-pad-x: 14px;
  --page-tabs-gap: 4px;
}

.page-tabs__item {
  position: relative;
  z-index: 0;
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
  min-width: 0;
  margin: 0;
  padding: var(--page-tabs-item-pad-y) var(--page-tabs-item-pad-x);
  color: var(--el-text-color-secondary);
  font: inherit;
  font-size: var(--page-tabs-font);
  font-weight: 500;
  letter-spacing: -0.015em;
  line-height: 1.25;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--page-tabs-item-radius);
  outline: none;
  transition:
    color 180ms cubic-bezier(0.22, 1, 0.36, 1),
    background 180ms cubic-bezier(0.22, 1, 0.36, 1),
    border-color 180ms cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 180ms cubic-bezier(0.22, 1, 0.36, 1),
    transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
}

.page-tabs:not(.page-tabs--rich) .page-tabs__item {
  align-items: center;
}

.page-tabs__item:hover:not(:disabled):not(.is-active) {
  color: var(--el-text-color-primary);
  background: color-mix(in srgb, var(--el-bg-color) 70%, transparent);
}

.page-tabs__item:focus-visible {
  box-shadow: 0 0 0 2px
    color-mix(in srgb, var(--el-color-primary) 35%, transparent);
}

.page-tabs__item.is-active {
  z-index: 1;
  color: var(--el-color-primary);
  font-weight: 650;
  background: var(--el-bg-color);
  border-color: color-mix(
    in srgb,
    var(--el-color-primary) 22%,
    var(--el-border-color-extra-light)
  );
  box-shadow:
    0 1px 2px color-mix(in srgb, var(--el-text-color-primary) 8%, transparent),
    0 1px 3px color-mix(in srgb, var(--el-color-primary) 10%, transparent);
}

.page-tabs__item:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.page-tabs__label {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.page-tabs__hint {
  max-width: 100%;
  overflow: hidden;
  color: var(--el-text-color-placeholder);
  font-size: 11px;
  font-weight: 450;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-tabs__item.is-active .page-tabs__hint {
  color: color-mix(
    in srgb,
    var(--el-color-primary) 55%,
    var(--el-text-color-secondary)
  );
}

@media (prefers-reduced-motion: reduce) {
  .page-tabs__item {
    transition: none;
  }
}
</style>
