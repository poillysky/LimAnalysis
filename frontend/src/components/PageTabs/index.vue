<script setup lang="ts">
import { computed } from "vue";

export type PageTabOption = {
  value: string;
  label: string;
  hint?: string;
  disabled?: boolean;
  status?: {
    ok: boolean;
    label: string;
  };
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

const rich = computed(() =>
  props.options.some(item => Boolean(item.hint) || Boolean(item.status))
);

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
      <span class="page-tabs__row">
        <span class="page-tabs__label">{{ item.label }}</span>
        <span
          v-if="item.status"
          class="page-tabs__status"
          :class="item.status.ok ? 'is-ok' : 'is-bad'"
        >
          {{ item.status.label }}
        </span>
      </span>
      <span v-if="item.hint" class="page-tabs__hint">{{ item.hint }}</span>
    </button>
  </div>
</template>

<style scoped>
.page-tabs {
  --page-tabs-pad-y: var(--la-space-xs);
  --page-tabs-pad-x: var(--la-space-xs);
  --page-tabs-gap: var(--la-space-2xs);
  --page-tabs-radius: var(--la-radius-md);
  --page-tabs-item-radius: var(--la-radius-sm);
  --page-tabs-item-pad-y: var(--la-space-sm);
  --page-tabs-item-pad-x: var(--la-space-lg);
  --page-tabs-font: var(--la-text-sm);

  display: inline-flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: var(--page-tabs-gap);
  max-width: 100%;
  padding: var(--page-tabs-pad-y) var(--page-tabs-pad-x);
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-extra-light);
  border-radius: var(--page-tabs-radius);
}

.page-tabs--small {
  --page-tabs-pad-y: var(--la-space-2xs);
  --page-tabs-pad-x: var(--la-space-2xs);
  --page-tabs-radius: var(--la-radius-sm);
  --page-tabs-item-radius: var(--la-radius-xs);
  --page-tabs-item-pad-y: var(--la-space-xs);
  --page-tabs-item-pad-x: 10px;
  --page-tabs-font: var(--la-text-xs);
}

.page-tabs--stretch {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  width: 100%;
}

.page-tabs--rich {
  --page-tabs-item-pad-y: var(--la-space-md);
  --page-tabs-item-pad-x: var(--la-space-lg);
  --page-tabs-gap: var(--la-space-xs);
}

.page-tabs__item {
  position: relative;
  z-index: 0;
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: var(--la-space-2xs);
  min-width: 0;
  margin: 0;
  padding: var(--page-tabs-item-pad-y) var(--page-tabs-item-pad-x);
  color: var(--el-text-color-secondary);
  font: inherit;
  font-size: var(--page-tabs-font);
  font-weight: 500;
  letter-spacing: -0.02em;
  line-height: var(--la-leading-tight);
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--page-tabs-item-radius);
  outline: none;
  transition:
    color 180ms ease-out,
    background 180ms ease-out,
    border-color 180ms ease-out,
    box-shadow 180ms ease-out;
}

.page-tabs:not(.page-tabs--rich) .page-tabs__item {
  align-items: center;
}

.page-tabs__item:hover:not(:disabled):not(.is-active) {
  color: var(--el-text-color-primary);
  background: var(--el-bg-color);
}

.page-tabs__item:focus-visible {
  box-shadow: var(--la-ring-focus);
}

.page-tabs__item.is-active {
  z-index: 1;
  color: var(--el-text-color-primary);
  font-weight: 600;
  background: var(--el-bg-color);
  border-color: var(--el-border-color-lighter);
  box-shadow: var(--la-shadow-sm);
}

.page-tabs__item.is-active .page-tabs__label {
  color: var(--el-color-primary);
}

.page-tabs__item:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.page-tabs__row {
  display: flex;
  align-items: center;
  gap: var(--la-space-sm);
  min-width: 0;
  max-width: 100%;
  height: 18px;
}

.page-tabs__label {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  height: 18px;
  overflow: hidden;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-tabs__status {
  display: inline-flex;
  flex: none;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--la-radius-pill);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0;
  line-height: 18px;
  white-space: nowrap;
}

.page-tabs__status.is-ok {
  color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}

.page-tabs__status.is-bad {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.page-tabs__hint {
  max-width: 100%;
  overflow: hidden;
  color: var(--el-text-color-placeholder);
  font-size: var(--la-text-2xs);
  font-weight: 450;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-tabs__item.is-active .page-tabs__hint {
  color: var(--el-text-color-secondary);
}

@media (prefers-reduced-motion: reduce) {
  .page-tabs__item {
    transition: none;
  }
}
</style>
