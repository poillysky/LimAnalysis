<script setup lang="ts">
export type PageMetricItem = {
  value: string | number;
  label: string;
  /** 主指标（如不良率）略强调 */
  accent?: boolean;
  /** 预警类数字用红 */
  alert?: boolean;
};

withDefaults(
  defineProps<{
    title?: string;
    subtitle?: string;
    metrics?: PageMetricItem[];
  }>(),
  {
    title: "",
    subtitle: "",
    metrics: () => []
  }
);
</script>

<template>
  <header class="page-metric-bar">
    <div
      v-if="title || subtitle || $slots.context"
      class="page-metric-bar__context"
    >
      <slot name="context">
        <strong v-if="title" class="page-metric-bar__title">{{ title }}</strong>
        <span v-if="subtitle" class="page-metric-bar__subtitle">{{
          subtitle
        }}</span>
      </slot>
    </div>

    <div v-if="$slots.default" class="page-metric-bar__main">
      <slot />
    </div>

    <div v-if="metrics.length" class="page-metric-bar__metrics">
      <div
        v-for="(item, index) in metrics"
        :key="`${item.label}-${index}`"
        class="page-metric-bar__metric"
        :class="{ 'is-accent': item.accent, 'is-alert': item.alert }"
      >
        <b class="page-metric-bar__value">{{ item.value }}</b>
        <span class="page-metric-bar__label">{{ item.label }}</span>
      </div>
    </div>

    <div v-if="$slots.end" class="page-metric-bar__end">
      <slot name="end" />
    </div>
  </header>
</template>

<style scoped>
.page-metric-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
  min-height: 52px;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid #c6c6c6;
  border-radius: 8px;
}

.page-metric-bar__context {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
  min-width: 0;
}

.page-metric-bar__title {
  color: #1f2937;
  font-size: 13px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.page-metric-bar__subtitle {
  color: #6b7280;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.3;
}

.page-metric-bar__main {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
  min-width: 0;
}

.page-metric-bar__metrics {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 8px;
  margin-left: auto;
}

.page-metric-bar__end {
  display: flex;
  flex: none;
  align-items: center;
}

.page-metric-bar__metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  min-width: 4.25rem;
  padding: 4px 10px 5px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fafafa;
  text-align: center;
}

.page-metric-bar__metric.is-accent {
  border-color: #b7d3c3;
  background: #f3faf6;
}

.page-metric-bar__metric.is-alert {
  border-color: #f0c7c7;
  background: #fff5f5;
}

.page-metric-bar__value {
  color: #111827;
  font-size: 18px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.05;
}

.page-metric-bar__metric.is-accent .page-metric-bar__value {
  color: #1e4e79;
}

.page-metric-bar__metric.is-alert .page-metric-bar__value {
  color: #9c0006;
}

.page-metric-bar__label {
  color: #6b7280;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.2;
  white-space: nowrap;
}

.page-metric-bar__metric.is-accent .page-metric-bar__label {
  color: #3d8a5c;
}

.page-metric-bar__metric.is-alert .page-metric-bar__label {
  color: #9c0006;
}

@media (max-width: 900px) {
  .page-metric-bar {
    padding: 8px 10px;
  }

  .page-metric-bar__metrics {
    width: 100%;
    margin-left: 0;
    padding-top: 8px;
    border-top: 1px solid #e5e7eb;
  }

  .page-metric-bar__metric {
    flex: 1 1 auto;
    align-items: center;
  }
}
</style>
