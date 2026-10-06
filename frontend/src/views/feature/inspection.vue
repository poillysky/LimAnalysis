<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  getInspectionBootstrap,
  getInspectionDirs,
  saveInspectionSettings,
  type InspectionDirItem,
  type InspectionDirListing,
  type InspectionSettings
} from "@/api/modules/inspection";
import { backendErrorHint } from "@/api/http";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";

defineOptions({
  name: "FeatureInspection"
});

type RootKey = keyof InspectionSettings;

type Picker = {
  open: boolean;
  dirs: InspectionDirItem[];
  up: string;
};

const fields: {
  key: RootKey;
  label: string;
  placeholder: string;
  note: string;
}[] = [
  {
    key: "mold_root_path",
    label: "注塑机",
    placeholder: "请选择注塑机照片根目录",
    note: "根目录 / 机台 / YYYYMMDD / 穴位 / 状态 / 文件"
  },
  {
    key: "appearance_root_path",
    label: "自动外观",
    placeholder: "请选择自动外观照片根目录",
    note: "根目录 / 项目 / 测试机 / 相机 / 日期 / 文件（暂定）"
  }
];

const loading = ref(false);
const saving = ref(false);
const hint = ref("");
const form = reactive<InspectionSettings>({
  mold_root_path: "",
  appearance_root_path: ""
});
const pickers = reactive<Record<RootKey, Picker>>({
  mold_root_path: { open: false, dirs: [], up: "" },
  appearance_root_path: { open: false, dirs: [], up: "" }
});

function isDrive(path: string) {
  return /^[a-zA-Z]:\\?$/.test(path);
}

function itemIcon(path: string) {
  return isDrive(path) ? "ri/hard-drive-2-line" : "ri/folder-open-line";
}

function errMessage(error: unknown, fallback: string) {
  const msg = (error as { response?: { data?: { message?: string } } })
    ?.response?.data?.message;
  return msg || fallback;
}

function applyListing(
  key: RootKey,
  listing?: InspectionDirListing | null,
  parent = ""
) {
  const items = listing?.dirs || [];
  const up = listing?.up || "";
  pickers[key].dirs = items.filter(
    item => item.path !== parent && item.path !== up
  );
  pickers[key].up = up;
}

async function loadDirs(key: RootKey, parent = "") {
  try {
    const res = await getInspectionDirs(parent);
    applyListing(key, res?.data, parent);
  } catch (error) {
    if (parent) {
      await loadDirs(key, "");
      return;
    }
    pickers[key].dirs = [];
    pickers[key].up = "";
    hint.value = errMessage(error, "无法列出目录");
  }
}

async function enterDir(key: RootKey, path: string) {
  pickers[key].open = true;
  form[key] = path;
  await loadDirs(key, path);
}

function clearDir(key: RootKey) {
  form[key] = "";
  void loadDirs(key, "");
  pickers[key].open = true;
}

async function load() {
  loading.value = true;
  hint.value = "";
  try {
    const res = await getInspectionBootstrap();
    const settings = res?.data?.settings;
    form.mold_root_path = settings?.mold_root_path || "";
    form.appearance_root_path = settings?.appearance_root_path || "";
    await Promise.all(
      fields.map(item => loadDirs(item.key, form[item.key] || ""))
    );
  } catch (error) {
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    await saveInspectionSettings({
      mold_root_path: form.mold_root_path.trim(),
      appearance_root_path: form.appearance_root_path.trim()
    });
    ElMessage.success("已保存");
  } catch (error) {
    ElMessage.error(errMessage(error, "保存失败"));
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="p-4" v-loading="loading">
    <el-card shadow="never">
      <template #header>照片根目录</template>
      <p v-if="hint" class="cfg-hint">{{ hint }}</p>
      <el-form label-width="96px">
        <el-form-item
          v-for="field in fields"
          :key="field.key"
          :label="field.label"
        >
          <div>
            <el-popover
            v-model:visible="pickers[field.key].open"
            trigger="click"
            placement="bottom-start"
            :width="520"
            :hide-after="0"
            :show-arrow="false"
            popper-class="dir-select-popper"
          >
            <template #reference>
              <div
                class="dir-select"
                :class="{ 'is-open': pickers[field.key].open }"
              >
                <span class="dir-select__icon">
                  <component
                    :is="
                      useRenderIcon(
                        form[field.key]
                          ? itemIcon(form[field.key])
                          : 'ri/folder-open-line'
                      )
                    "
                  />
                </span>
                <span
                  class="dir-select__value"
                  :class="{ 'is-placeholder': !form[field.key] }"
                >
                  {{ form[field.key] || field.placeholder }}
                </span>
                <button
                  v-if="form[field.key]"
                  type="button"
                  class="dir-select__clear"
                  aria-label="清空"
                  @click.stop="clearDir(field.key)"
                >
                  <component :is="useRenderIcon('ri/close-line')" />
                </button>
                <span
                  class="dir-select__caret"
                  :class="{ 'is-open': pickers[field.key].open }"
                >
                  <component :is="useRenderIcon('ri/arrow-down-s-line')" />
                </span>
              </div>
            </template>
            <div class="dir-menu" @click.stop>
              <button
                v-if="pickers[field.key].up"
                type="button"
                class="dir-menu__item is-up"
                @click="enterDir(field.key, pickers[field.key].up)"
              >
                <span class="dir-menu__icon">
                  <component :is="useRenderIcon('ri/arrow-go-back-line')" />
                </span>
                <span class="dir-menu__text">上一级</span>
              </button>
              <button
                v-for="item in pickers[field.key].dirs"
                :key="item.path"
                type="button"
                class="dir-menu__item"
                @click="enterDir(field.key, item.path)"
              >
                <span class="dir-menu__icon">
                  <component :is="useRenderIcon(itemIcon(item.path))" />
                </span>
                <span class="dir-menu__text">{{ item.name }}</span>
                <span class="dir-menu__go">
                  <component :is="useRenderIcon('ri/arrow-right-s-line')" />
                </span>
              </button>
              <p
                v-if="
                  !pickers[field.key].dirs.length && !pickers[field.key].up
                "
                class="dir-menu__empty"
              >
                没有可进入的文件夹
              </p>
            </div>
          </el-popover>
          <p class="cfg-note">{{ field.note }}</p>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.cfg-hint {
  color: var(--el-color-warning);
  font-size: 13px;
}

.cfg-note {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.dir-select {
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 520px;
  min-height: 32px;
  padding: 1px 8px 1px 10px;
  cursor: pointer;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  transition: border-color 0.15s ease;
}

.dir-select:hover,
.dir-select.is-open {
  border-color: var(--el-color-primary);
}

.dir-select.is-open {
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}

.dir-select__icon {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  font-size: 15px;
  color: #2563eb;
}

.dir-select__value {
  overflow: hidden;
  flex: 1;
  min-width: 0;
  font-size: 14px;
  line-height: 22px;
  color: var(--el-text-color-regular);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dir-select__value.is-placeholder {
  color: var(--el-text-color-placeholder);
}

.dir-select__clear,
.dir-select__caret {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  color: var(--el-text-color-placeholder);
  background: transparent;
  border: 0;
}

.dir-select__clear {
  cursor: pointer;
}

.dir-select__caret {
  transition: transform 0.15s ease;
}

.dir-select__caret.is-open {
  transform: rotate(180deg);
}

.dir-menu {
  max-height: 280px;
  overflow: auto;
  scrollbar-color: #cbd5e1 transparent;
}

.dir-menu__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  font-size: 14px;
  line-height: 22px;
  color: var(--el-text-color-regular);
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 6px;
}

.dir-menu__item:hover {
  background: var(--el-fill-color-light);
}

.dir-menu__item.is-up {
  color: #2563eb;
  font-weight: 600;
}

.dir-menu__icon,
.dir-menu__go {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  color: #2563eb;
}

.dir-menu__go {
  margin-left: auto;
  color: var(--el-text-color-placeholder);
}

.dir-menu__text {
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dir-menu__empty {
  margin: 0;
  padding: 16px 8px;
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  text-align: center;
}
</style>

<style>
.dir-select-popper.el-popover.el-popper {
  padding: 6px;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgb(15 23 42 / 10%);
}
</style>
