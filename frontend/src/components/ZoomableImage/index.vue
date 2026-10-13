<script setup lang="ts">
import { computed, ref, watch } from "vue";

const props = withDefaults(
  defineProps<{
    src: string;
    alt?: string;
  }>(),
  { alt: "" }
);

const MIN = 1;
const MAX = 8;
const STEP = 1.12;

const rootRef = ref<HTMLElement | null>(null);
const scale = ref(1);
const tx = ref(0);
const ty = ref(0);
const dragging = ref(false);

let dragOriginX = 0;
let dragOriginY = 0;
let dragStartTx = 0;
let dragStartTy = 0;

const imgStyle = computed(() => ({
  transform: `translate(${tx.value}px, ${ty.value}px) scale(${scale.value})`,
  cursor:
    scale.value > 1 ? (dragging.value ? "grabbing" : "grab") : "zoom-in"
}));

function reset() {
  scale.value = 1;
  tx.value = 0;
  ty.value = 0;
  dragging.value = false;
}

watch(
  () => props.src,
  () => reset()
);

function onWheel(event: WheelEvent) {
  event.preventDefault();
  const root = rootRef.value;
  if (!root) return;

  const next = Math.min(
    MAX,
    Math.max(
      MIN,
      scale.value * (event.deltaY < 0 ? STEP : 1 / STEP)
    )
  );
  if (Math.abs(next - scale.value) < 1e-6) return;

  const rect = root.getBoundingClientRect();
  const cx = event.clientX - rect.left - rect.width / 2;
  const cy = event.clientY - rect.top - rect.height / 2;
  tx.value = cx - ((cx - tx.value) / scale.value) * next;
  ty.value = cy - ((cy - ty.value) / scale.value) * next;
  scale.value = next;
  if (next === MIN) {
    tx.value = 0;
    ty.value = 0;
  }
}

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return;
  if (scale.value <= MIN) return;
  const root = rootRef.value;
  if (!root) return;
  dragging.value = true;
  dragOriginX = event.clientX;
  dragOriginY = event.clientY;
  dragStartTx = tx.value;
  dragStartTy = ty.value;
  root.setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return;
  tx.value = dragStartTx + (event.clientX - dragOriginX);
  ty.value = dragStartTy + (event.clientY - dragOriginY);
}

function onPointerUp(event: PointerEvent) {
  if (!dragging.value) return;
  dragging.value = false;
  const root = rootRef.value;
  root?.releasePointerCapture(event.pointerId);
}

function onDblClick() {
  if (scale.value > MIN) {
    reset();
    return;
  }
  scale.value = 2;
}
</script>

<template>
  <div
    ref="rootRef"
    class="zoomable-image"
    @wheel="onWheel"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
    @dblclick="onDblClick"
  >
    <img
      :src="src"
      :alt="alt"
      :style="imgStyle"
      draggable="false"
      @dragstart.prevent
    />
    <span v-if="scale > 1" class="zoomable-image__badge">
      {{ Math.round(scale * 100) }}%
    </span>
  </div>
</template>

<style scoped>
.zoomable-image {
  position: absolute;
  inset: 0;
  z-index: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  touch-action: none;
  user-select: none;
}

.zoomable-image img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  transform-origin: center center;
  will-change: transform;
  pointer-events: none;
}

.zoomable-image__badge {
  position: absolute;
  right: 12px;
  bottom: 12px;
  z-index: 1;
  padding: 2px 8px;
  border-radius: 999px;
  color: var(--la-media-text, #f4f4f5);
  background: rgba(18, 20, 26, 0.72);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 650;
  pointer-events: none;
}
</style>
