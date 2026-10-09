<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  getScanBootstrap,
  saveDefectScanItems,
  type ScanProject
} from "@/api/modules/scan";
import { backendErrorHint } from "@/api/http";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";

defineOptions({
  name: "FeatureScanDefects"
});

const loading = ref(false);
const saving = ref(false);
const hint = ref("");
const projects = ref<ScanProject[]>([]);
const projectId = ref("");
const items = ref<string[]>([]);
const draft = ref("");
let abort: AbortController | null = null;

const projectName = computed(() => {
  return (
    projects.value.find(item => item.project_id === projectId.value)
      ?.display_name || ""
  );
});

async function load(id = "") {
  abort?.abort();
  abort = new AbortController();
  loading.value = true;
  hint.value = "";
  try {
    const res = await getScanBootstrap(id || undefined, abort.signal);
    const data = res?.data;
    projects.value = data?.projects || [];
    projectId.value = data?.current_id || "";
    items.value = (data?.defects || []).map(item => item.key);
    if (!projects.value.length) hint.value = "还没有启用的项目";
  } catch (error) {
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

async function persist(next = items.value) {
  if (!projectId.value) {
    ElMessage.warning("请选择项目");
    return false;
  }
  saving.value = true;
  try {
    const res = await saveDefectScanItems({
      project_id: projectId.value,
      items: next
    });
    items.value = [...(res?.data?.items || next)];
    return true;
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
    return false;
  } finally {
    saving.value = false;
  }
}

async function addItem() {
  const name = draft.value.trim();
  if (!name) return;
  if (items.value.includes(name)) {
    ElMessage.warning("该名称已存在");
    return;
  }
  draft.value = "";
  const ok = await persist([...items.value, name]);
  if (ok) ElMessage.success("已添加");
}

async function removeItem(index: number) {
  const ok = await persist(items.value.filter((_, i) => i !== index));
  if (ok) ElMessage.success("已删除");
}

async function moveItem(index: number, step: number) {
  const next = [...items.value];
  const target = index + step;
  if (target < 0 || target >= next.length) return;
  [next[index], next[target]] = [next[target], next[index]];
  await persist(next);
}

onMounted(() => load());
onUnmounted(() => abort?.abort());
</script>

<template>
  <div class="cfg-page" v-loading="loading">
    <header class="cfg-head">
      <div>
        <strong>次品名称</strong>
        <span>每个项目单独维护扫码下拉，只显示这里添加过的名称</span>
      </div>
      <span class="cfg-count">{{ items.length }} 项</span>
    </header>

    <p v-if="hint" class="cfg-banner">{{ hint }}</p>

    <section class="cfg-layout">
      <aside class="cfg-projects">
        <p>项目</p>
        <button
          v-for="item in projects"
          :key="item.project_id"
          type="button"
          class="cfg-project"
          :class="{ on: item.project_id === projectId }"
          @click="load(item.project_id)"
        >
          <span>{{ item.display_name }}</span>
          <small>{{ item.project_id }}</small>
        </button>
        <p v-if="!projects.length" class="cfg-muted">暂无启用项目</p>
      </aside>

      <div class="cfg-sheet">
        <div class="cfg-sheet__top">
          <div>
            <strong>{{ projectName || "未选择项目" }}</strong>
            <span>输入名称后回车即可保存</span>
          </div>
        </div>

        <div class="cfg-add">
          <el-input
            v-model="draft"
            maxlength="80"
            clearable
            :disabled="!projectId || saving"
            placeholder="输入次品名称"
            @keyup.enter="addItem"
          >
            <template #prefix>
              <component :is="useRenderIcon('ri/add-line')" />
            </template>
          </el-input>
          <el-button type="primary" :disabled="!projectId" :loading="saving" @click="addItem">
            添加
          </el-button>
        </div>

        <ul v-if="items.length" class="cfg-list">
          <li v-for="(name, index) in items" :key="`${name}-${index}`">
            <i>{{ String(index + 1).padStart(2, "0") }}</i>
            <span>{{ name }}</span>
            <div class="cfg-ops">
              <button type="button" :disabled="index === 0" @click="moveItem(index, -1)">
                上移
              </button>
              <button
                type="button"
                :disabled="index === items.length - 1"
                @click="moveItem(index, 1)"
              >
                下移
              </button>
              <button type="button" class="danger" @click="removeItem(index)">删除</button>
            </div>
          </li>
        </ul>
        <div v-else class="cfg-empty">
          <strong>还没有次品名称</strong>
          <span>不要使用系统默认项。添加后，「次品扫码」的下拉才会出现选项。</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.cfg-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-sizing: border-box;
  min-height: calc(100vh - var(--la-chrome-total));
  margin: 0 !important;
  padding: var(--la-page-pad-y) var(--la-page-pad-x) var(--la-space-xl);
  background: #eef7fb;
}

.cfg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--la-space-md);
}

.cfg-head strong {
  display: block;
  color: #0c3f56;
  font-size: var(--la-page-title);
  font-weight: 650;
  letter-spacing: -0.01em;
}

.cfg-head span {
  color: #5b6b63;
  font-size: var(--la-page-desc);
}

.cfg-count {
  padding: 4px 10px;
  color: #1e4e79;
  background: #fff;
  border: 1px solid #d5ddd8;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
}

.cfg-banner {
  margin: 0;
  padding: 8px 12px;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #f0d48a;
  border-radius: 8px;
  font-size: 13px;
}

.cfg-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 14px;
  min-height: 520px;
}

.cfg-projects {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  background: #fff;
  border: 1px solid #d5ddd8;
  border-radius: 12px;
}

.cfg-projects > p {
  margin: 0 0 4px;
  color: #6b7b74;
  font-size: 12px;
}

.cfg-project {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #f6f8f6;
  color: #0c3f56;
  text-align: left;
  cursor: pointer;
}

.cfg-project small {
  color: #7a8a83;
  font-size: 11px;
}

.cfg-project.on {
  background: #e0f4fc;
  border-color: #b7d8c4;
  font-weight: 650;
}

.cfg-muted {
  color: #8a9a93 !important;
}

.cfg-sheet {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 20px 20px;
  background: #fff;
  border: 1px solid #d5ddd8;
  border-radius: 12px;
}

.cfg-sheet__top strong {
  display: block;
  color: #0c3f56;
  font-size: 16px;
}

.cfg-sheet__top span {
  color: #6b7b74;
  font-size: 12px;
}

.cfg-add {
  display: flex;
  gap: 10px;
}

.cfg-list {
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid #dce4de;
  border-radius: 10px;
  overflow: hidden;
}

.cfg-list li {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 0 8px 0 14px;
  min-height: 48px;
  border-bottom: 1px solid #edf1ee;
  color: #0c3f56;
  font-size: 14px;
}

.cfg-list li:last-child {
  border-bottom: 0;
}

.cfg-list li:nth-child(even) {
  background: #f8fbf9;
}

.cfg-list i {
  color: #8aa093;
  font-style: normal;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.cfg-ops {
  display: flex;
}

.cfg-ops button {
  padding: 8px 10px;
  border: 0;
  background: transparent;
  color: #5b6b63;
  font-size: 12px;
  cursor: pointer;
}

.cfg-ops button:hover:not(:disabled) {
  color: #0c3f56;
}

.cfg-ops button:disabled {
  opacity: 0.35;
  cursor: default;
}

.cfg-ops button.danger {
  color: #b42318;
}

.cfg-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 280px;
  padding: 24px;
  color: #6b7b74;
  background:
    linear-gradient(#fff, #fff) padding-box,
    repeating-linear-gradient(
      -12deg,
      #dce4de,
      #dce4de 6px,
      transparent 6px,
      transparent 12px
    )
    border-box;
  border: 1px dashed transparent;
  border-radius: 12px;
  text-align: center;
}

.cfg-empty strong {
  color: #0c3f56;
  font-size: 15px;
}

.cfg-empty span {
  max-width: 360px;
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 860px) {
  .cfg-layout {
    grid-template-columns: 1fr;
  }
}
</style>
