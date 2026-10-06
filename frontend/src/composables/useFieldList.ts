/**
 * ETL / 聚合模型编辑器的字段列表操作 —— 由 `views/feature/etl.vue` 与
 * `views/feature/agg.vue` 逐字相同的实现收敛而来（2026-10-06 去重）。
 *
 * ⚠️ 刻意保留的「同名不同义」，**不要**合并：
 * - `statusLabel`：etl 版多一个 `partial: "部分成功"` key，agg 版没有。
 *   两边共用一个 map 会让 agg 的任务状态标签错位。
 * - `emptyField`：etl 用 `mapping_type` / `constant_value` / `is_required`，
 *   agg 用 `field_category` / `aggregate_func`。字段集不同，各自一份。
 * - `startRunBar` / `applyJobToBar` / `finishRunBar` / `fmtElapsed`：名字相同但
 *   语义不同（etl 为 8/22/68/100 + 1s 轮询 +「分秒」，agg 为 12/20/55 + 500ms
 *   +「m s」），且 agg 的 applyJobToBar 不处理终态。属两套 UI 契约，不是复制粘贴。
 */

import type { Ref } from "vue";

/** 字段列表最小契约：两个页面的 Field 类型都满足 */
export type SortableField = {
  sort_order: number;
  [key: string]: unknown;
};

export function addFieldTo<T extends SortableField>(
  fields: Ref<T[]>,
  make: (order: number) => T
) {
  fields.value.push(make(fields.value.length));
}

export function removeFieldAt<T extends SortableField>(fields: Ref<T[]>, index: number) {
  fields.value.splice(index, 1);
  fields.value.forEach((f, i) => {
    f.sort_order = i;
  });
}

export function moveFieldBy<T extends SortableField>(
  fields: Ref<T[]>,
  index: number,
  delta: number
) {
  const next = index + delta;
  if (next < 0 || next >= fields.value.length) return;
  const copy = [...fields.value];
  const [item] = copy.splice(index, 1);
  copy.splice(next, 0, item);
  copy.forEach((f, i) => {
    f.sort_order = i;
  });
  fields.value = copy;
}

/** Element Plus tag 类型映射（etl / agg 完全一致） */
export function statusType(status: string) {
  if (status === "success" || status === "queued") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "busy") return "warning";
  return "info";
}
