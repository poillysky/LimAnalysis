<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { getMetabaseBoard, type BoardOption, type BoardProject } from "@/api/modules/exception";
import { backendErrorHint } from "@/api/http";
import PageTabs from "@/components/PageTabs/index.vue";

defineOptions({
  name: "ExceptionMonitor"
});

const loading = ref(false);
const hint = ref("");
const projects = ref<BoardProject[]>([]);
const projectId = ref("");
const boardKind = ref("");
const boards = ref<BoardOption[]>([]);
const embedUrl = ref("");
let refreshTimer: number | null = null;

const projectTabs = computed(() =>
  projects.value.map(item => ({
    value: item.project_id,
    label: item.display_name
  }))
);
const boardTabs = computed(() =>
  boards.value.map(item => ({
    value: item.kind,
    label: item.label
  }))
);

async function load(id?: string, kind?: string) {
  loading.value = true;
  hint.value = "";
  try {
    const res = await getMetabaseBoard(id, kind);
    const data = res?.data;
    projects.value = data?.projects || [];
    const current = data?.current;
    if (current?.project_id) projectId.value = current.project_id;
    else if (projects.value.length && !projectId.value) {
      projectId.value = projects.value[0].project_id;
    }
    boards.value = current?.boards || [];
    boardKind.value = current?.board || boards.value[0]?.kind || "";
    embedUrl.value = current?.embed_url || "";
    hint.value = data?.error || "";
  } catch (error) {
    embedUrl.value = "";
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

function onProjectChange(id: string) {
  boardKind.value = "";
  load(id);
}

function onBoardChange(kind: string) {
  load(projectId.value, kind);
}

onMounted(() => {
  load();
  refreshTimer = window.setInterval(() => {
    if (projectId.value) load(projectId.value, boardKind.value || undefined);
  }, 45 * 60 * 1000);
});

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});
</script>

<template>
  <div class="board-page" v-loading="loading">
    <div class="board-bar">
      <PageTabs
        v-if="projectTabs.length"
        :model-value="projectId"
        :options="projectTabs"
        aria-label="项目"
        @change="onProjectChange"
      />
      <PageTabs
        v-if="boardTabs.length > 1"
        :model-value="boardKind"
        :options="boardTabs"
        aria-label="看板"
        @change="onBoardChange"
      />
    </div>
    <el-alert
      v-if="hint"
      class="board-hint"
      type="warning"
      :closable="false"
      :title="hint"
    />
    <iframe
      v-if="embedUrl"
      class="board-frame"
      :key="embedUrl"
      :src="embedUrl"
      title="数据看板"
      allow="fullscreen"
    />
    <div v-else class="board-empty">
      {{ hint || "该项目暂无看板" }}
    </div>
  </div>
</template>

<style scoped>
.board-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 52px);
  min-height: 520px;
  margin: 0 !important;
  padding: 8px 8px 8px;
}

.board-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.board-hint {
  margin-bottom: 12px;
}

.board-frame {
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 0;
  border-radius: 0;
  background: var(--el-bg-color);
}

.board-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  border: 1px dashed var(--el-border-color);
  border-radius: 12px;
}
</style>
