<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  getInspectionBootstrap,
  getViewerDates,
  getViewerFolders,
  getViewerImages,
  searchViewerImages,
  type AppearanceDim,
  type InspectionImage,
  type InspectionProject,
  type PhotoSource
} from "@/api/modules/inspection";
import { backendErrorHint } from "@/api/http";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";

defineOptions({
  name: "InspectionViewer"
});

const router = useRouter();
const route = useRoute();
const photoSource = computed<PhotoSource>(() =>
  route.meta.photoSource === "appearance" ? "appearance" : "mold"
);
const pageTitle = computed(() => String(route.meta.title || "注塑机图片"));
const pageIcon = computed(() =>
  photoSource.value === "appearance" ? "ri/eye-line" : "ri/image-line"
);
const isAppearance = computed(() => photoSource.value === "appearance");
/** 仅外观页：tester=外观测试机维度，mold=注塑机维度 */
const queryDim = ref<AppearanceDim>("tester");
const isMoldDim = computed(
  () => isAppearance.value && queryDim.value === "mold"
);
const loading = ref(false);
const hint = ref("");
const ready = ref(false);
const projects = ref<InspectionProject[]>([]);
const projectId = ref("");
const machine = ref("");
const cavity = ref("A");
const camera = ref("");
const dateStr = ref("");
const status = ref("OK");
const dates = ref<string[]>([]);
const cavities = ref<string[]>([]);
const testers = ref<string[]>([]);
const moldMachines = ref<string[]>([]);
const cameras = ref<string[]>([]);
const statuses = ref<string[]>(["OK"]);
const images = ref<InspectionImage[]>([]);
const index = ref(0);
const started = ref(false);
const locating = ref(false);
const qrQuery = ref("");
const filmRef = ref<HTMLElement | null>(null);
/** 扫码定位时检出但不在项目机台清单里的机台，临时并入下拉 */
const machineExtras = ref<string[]>([]);

const currentProject = computed(
  () => projects.value.find(item => item.project_id === projectId.value) || null
);
const machineChoices = computed(() => {
  let base: string[] = [];
  if (isAppearance.value) {
    base = isMoldDim.value ? moldMachines.value : testers.value;
  } else {
    base = currentProject.value?.machines || [];
  }
  const extras = machineExtras.value.filter(
    code => code && !base.some(b => b.toLowerCase() === code.toLowerCase())
  );
  return extras.length ? [...base, ...extras] : base;
});
const machineFieldLabel = computed(() => {
  if (!isAppearance.value) return "机台";
  return isMoldDim.value ? "注塑机台" : "测试机";
});
const dateFieldLabel = computed(() =>
  isAppearance.value && isMoldDim.value ? "生产日" : "日期"
);
const current = computed(() => images.value[index.value] || null);
const canQuery = computed(() => {
  if (!ready.value || !projectId.value || !machine.value || !dateStr.value) {
    return false;
  }
  if (isAppearance.value) {
    if (!camera.value) return false;
    if (isMoldDim.value && !cavity.value) return false;
    return true;
  }
  return Boolean(cavity.value);
});
const counter = computed(() =>
  images.value.length
    ? `${index.value + 1} / ${images.value.length}`
    : "0 / 0"
);

function formatDate(value: string) {
  const raw = String(value || "").trim();
  if (/^\d{8}$/.test(raw)) {
    return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  }
  const dotted = raw.match(/^(\d{4})[.\-](\d{2})[.\-](\d{2})$/);
  if (dotted) return `${dotted[1]}-${dotted[2]}-${dotted[3]}`;
  return raw || "—";
}

function errMessage(error: unknown, fallback: string) {
  const msg = (error as { response?: { data?: { message?: string } } })
    ?.response?.data?.message;
  return msg || fallback;
}

async function bootstrap() {
  loading.value = true;
  hint.value = "";
  try {
    const res = await getInspectionBootstrap();
    projects.value = res?.data?.projects || [];
    cavities.value = res?.data?.cavities || [];
    statuses.value = res?.data?.statuses?.length ? res.data.statuses : ["OK"];
    ready.value = Boolean(res?.data?.ready?.[photoSource.value]);
    if (!projectId.value && projects.value.length) {
      projectId.value = projects.value[0].project_id;
    }
    if (isAppearance.value) {
      camera.value = camera.value || "";
      await loadAppearanceMeta();
    } else {
      syncMachine();
      if (cavities.value.length && !cavities.value.includes(cavity.value)) {
        cavity.value = cavities.value[0];
      }
    }
    if (!ready.value) hint.value = "还没有配置照片目录。";
    else if (isAppearance.value) await loadAppearanceViews();
    else await loadDates();
  } catch (error) {
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

function syncChoice(list: string[], current: string) {
  if (!list.length) return "";
  return list.includes(current) ? current : list[0];
}

function matchChoice(list: string[], want: string): string {
  const raw = String(want || "").trim();
  if (!raw) return "";
  if (list.includes(raw)) return raw;
  const lower = raw.toLowerCase();
  const hit = list.find(item => item.toLowerCase() === lower);
  return hit || raw;
}

function ensureChoice(list: string[], want: string): string[] {
  const raw = String(want || "").trim();
  if (!raw) return list;
  if (list.some(item => item.toLowerCase() === raw.toLowerCase())) return list;
  return [...list, raw];
}

function syncMachine() {
  machine.value = syncChoice(machineChoices.value, machine.value);
}

async function loadAppearanceMeta() {
  testers.value = [];
  moldMachines.value = [];
  cameras.value = [];
  camera.value = "";
  dates.value = [];
  dateStr.value = "";
  if (!ready.value || !projectId.value) {
    machine.value = "";
    return;
  }
  try {
    const res = await getViewerFolders(
      projectId.value,
      "",
      queryDim.value
    );
    testers.value = res?.data?.testers || [];
    moldMachines.value =
      res?.data?.machines?.length
        ? res.data.machines
        : currentProject.value?.machines || [];
    if (res?.data?.cavities?.length) cavities.value = res.data.cavities;
    if (isMoldDim.value) {
      cameras.value = res?.data?.cameras || [];
      camera.value = syncChoice(cameras.value, camera.value);
      if (cavities.value.length && !cavities.value.includes(cavity.value)) {
        cavity.value = cavities.value[0];
      }
    }
    syncMachine();
  } catch (error) {
    testers.value = [];
    moldMachines.value = [];
    machine.value = "";
    hint.value = backendErrorHint(error);
  }
}

async function loadAppearanceViews() {
  cameras.value = [];
  if (!ready.value || !projectId.value) {
    camera.value = "";
    dates.value = [];
    dateStr.value = "";
    return;
  }
  if (isMoldDim.value) {
    if (!machine.value) {
      camera.value = "";
      dates.value = [];
      dateStr.value = "";
      return;
    }
    try {
      const res = await getViewerFolders(
        projectId.value,
        "",
        "mold"
      );
      cameras.value = res?.data?.cameras || [];
      camera.value = syncChoice(cameras.value, camera.value);
      if (res?.data?.cavities?.length) cavities.value = res.data.cavities;
      await loadDates();
    } catch (error) {
      camera.value = "";
      hint.value = backendErrorHint(error);
    }
    return;
  }
  if (!machine.value) {
    camera.value = "";
    dates.value = [];
    dateStr.value = "";
    return;
  }
  try {
    const res = await getViewerFolders(
      projectId.value,
      machine.value,
      "tester"
    );
    cameras.value = res?.data?.cameras || [];
    camera.value = syncChoice(cameras.value, camera.value);
    await loadDates();
  } catch (error) {
    camera.value = "";
    hint.value = backendErrorHint(error);
  }
}

async function loadDates(keepDate = "") {
  const needCamera = isAppearance.value ? camera.value : true;
  const needCavity = isMoldDim.value ? cavity.value : true;
  if (
    !ready.value ||
    !projectId.value ||
    !machine.value ||
    !needCamera ||
    !needCavity
  ) {
    dates.value = [];
    if (!keepDate) dateStr.value = "";
    return;
  }
  try {
    const res = await getViewerDates(
      projectId.value,
      machine.value,
      photoSource.value,
      isAppearance.value ? camera.value : "",
      isAppearance.value ? queryDim.value : "tester"
    );
    const listed = res?.data?.dates || [];
    dates.value = listed;
    if (keepDate) {
      if (!dates.value.includes(keepDate)) dates.value = [keepDate, ...dates.value];
      dateStr.value = keepDate;
    } else {
      dateStr.value = res?.data?.default_date || "";
    }
    if (res?.data?.cavities?.length) cavities.value = res.data.cavities;
    if (res?.data?.statuses?.length) statuses.value = res.data.statuses;
    if (res?.data?.testers?.length) testers.value = res.data.testers;
    if (res?.data?.machines?.length) moldMachines.value = res.data.machines;
    if (res?.data?.cameras?.length) cameras.value = res.data.cameras;
  } catch (error) {
    hint.value = backendErrorHint(error);
  }
}

watch(projectId, () => {
  if (locating.value) return;
  machineExtras.value = [];
  if (isAppearance.value) {
    void loadAppearanceMeta().then(() => loadAppearanceViews());
  } else syncMachine();
});

watch(queryDim, () => {
  if (!isAppearance.value || locating.value) return;
  images.value = [];
  index.value = 0;
  started.value = false;
  machine.value = "";
  camera.value = "";
  void loadAppearanceMeta().then(() => loadAppearanceViews());
});

watch(machine, () => {
  if (locating.value) return;
  images.value = [];
  index.value = 0;
  started.value = false;
  if (isAppearance.value) void loadAppearanceViews();
  else void loadDates();
});

watch(camera, () => {
  if (locating.value || !isAppearance.value) return;
  images.value = [];
  index.value = 0;
  started.value = false;
  void loadDates();
});

watch(cavity, () => {
  if (locating.value || !isMoldDim.value) return;
  images.value = [];
  index.value = 0;
  started.value = false;
  void loadDates();
});

watch(index, () => {
  void nextTick(scrollFilm);
  const item = images.value[index.value];
  if (!item || !started.value) return;
  locating.value = true;
  locateFromImage(item);
  void nextTick(() => {
    locating.value = false;
  });
});

function scrollFilm() {
  const root = filmRef.value;
  if (!root) return;
  const active = root.querySelector<HTMLElement>("[data-active='true']");
  active?.scrollIntoView({ inline: "center", block: "nearest" });
}

function onProjectChange(id: string | number | boolean) {
  projectId.value = String(id);
  syncMachine();
}

async function startCheck() {
  if (!ready.value) {
    router.push("/feature/inspection");
    return;
  }
  if (!canQuery.value) {
    ElMessage.warning(
      isMoldDim.value
        ? "请选择项目、注塑机台、穴位、视角和生产日"
        : isAppearance.value
          ? "请选择项目、测试机、视角和日期"
          : "请选择项目、机台、穴位和日期"
    );
    return;
  }
  loading.value = true;
  hint.value = "";
  started.value = true;
  try {
    const res = await getViewerImages({
      project_id: projectId.value,
      machine: machine.value,
      cavity: isAppearance.value
        ? isMoldDim.value
          ? cavity.value
          : camera.value
        : cavity.value,
      date: dateStr.value,
      status: status.value,
      source: photoSource.value,
      dim: isAppearance.value ? queryDim.value : undefined,
      camera: isMoldDim.value ? camera.value : undefined
    });
    images.value = res?.data?.images || [];
    index.value = 0;
    if (!images.value.length) {
      hint.value = res?.data?.hint || "这个筛选下没有照片。";
    }
    await nextTick();
    scrollFilm();
  } catch (error) {
    hint.value = errMessage(error, "取图失败");
    images.value = [];
  } finally {
    loading.value = false;
  }
}

function locateFromImage(item: InspectionImage | null) {
  if (!item) return;
  const foundMachine = String(item.machine || "").trim();
  if (foundMachine) {
    if (isAppearance.value && !isMoldDim.value) {
      testers.value = ensureChoice(testers.value, foundMachine);
    } else {
      const inProject = (currentProject.value?.machines || []).some(
        code => code.toLowerCase() === foundMachine.toLowerCase()
      );
      if (!inProject) {
        machineExtras.value = ensureChoice(machineExtras.value, foundMachine);
      }
      if (isMoldDim.value) {
        moldMachines.value = ensureChoice(moldMachines.value, foundMachine);
      }
    }
    machine.value = matchChoice(machineChoices.value, foundMachine);
  }

  if (isAppearance.value) {
    const cameraName = String(item.camera || "").trim();
    if (cameraName) {
      cameras.value = ensureChoice(cameras.value, cameraName);
      camera.value = matchChoice(cameras.value, cameraName);
    }
    if (isMoldDim.value && item.cavity) {
      const letter = String(item.cavity).trim().toUpperCase();
      cavities.value = ensureChoice(cavities.value, letter);
      cavity.value = matchChoice(cavities.value, letter);
    }
  } else if (item.cavity) {
    const letter = String(item.cavity).trim().toUpperCase();
    cavities.value = ensureChoice(cavities.value, letter);
    cavity.value = matchChoice(cavities.value, letter);
  }

  if (item.date_str) {
    const day = String(item.date_str).trim();
    if (day) {
      dates.value = ensureChoice(dates.value, day);
      // 日期保持后端给的原值（通常 YYYYMMDD）
      dateStr.value = dates.value.includes(day)
        ? day
        : matchChoice(dates.value, day) || day;
    }
  }

  if (item.status && !isAppearance.value) {
    const st = String(item.status).trim();
    statuses.value = ensureChoice(statuses.value, st);
    status.value = matchChoice(statuses.value, st);
  }
}

async function searchByName() {
  if (!ready.value) {
    router.push("/feature/inspection");
    return;
  }
  const query = qrQuery.value.trim();
  if (!query) {
    ElMessage.warning("请扫码或输入文件名");
    return;
  }
  if (!projectId.value) {
    ElMessage.warning("请选择项目");
    return;
  }
  loading.value = true;
  hint.value = "";
  started.value = true;
  try {
    const res = await searchViewerImages(
      projectId.value,
      query,
      photoSource.value
    );
    images.value = res?.data?.images || [];
    index.value = 0;
    if (!images.value.length) {
      hint.value = "没有匹配该文件名的照片。";
    } else {
      locating.value = true;
      const hit = images.value[0];
      // 先按命中结果校正机台/穴位/相机，再拉日期列表，最后再校正一次防覆盖
      locateFromImage(hit);
      if (isAppearance.value) await loadAppearanceViews();
      await loadDates(hit.date_str || "");
      locateFromImage(hit);
      ElMessage.success(
        `已定位 ${hit.machine || "—"}${
          isAppearance.value
            ? [
                isMoldDim.value && hit.cavity ? `${hit.cavity}穴` : "",
                hit.camera || (!isMoldDim.value ? hit.cavity : "")
              ]
                .filter(Boolean)
                .map(part => ` / ${part}`)
                .join("")
            : hit.cavity
              ? ` / ${hit.cavity}穴`
              : ""
        }`
      );
    }
    await nextTick();
    locating.value = false;
    scrollFilm();
  } catch (error) {
    locating.value = false;
    hint.value = errMessage(error, "搜索失败");
    images.value = [];
  } finally {
    loading.value = false;
  }
}

function prev() {
  if (index.value > 0) index.value -= 1;
}

function next() {
  if (index.value < images.value.length - 1) index.value += 1;
}

function jump(i: number) {
  index.value = i;
}

function onKey(event: KeyboardEvent) {
  if (!images.value.length) return;
  const target = event.target as HTMLElement | null;
  if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    prev();
  }
  if (event.key === "ArrowRight") {
    event.preventDefault();
    next();
  }
}

onMounted(() => {
  void bootstrap();
  window.addEventListener("keydown", onKey);
});
watch(photoSource, () => {
  images.value = [];
  index.value = 0;
  started.value = false;
  queryDim.value = "tester";
  void bootstrap();
});
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="viewer-page" v-loading="loading">
    <section class="viewer-bar">
      <header class="viewer-bar__head">
        <span class="viewer-bar__icon">
          <component :is="useRenderIcon(pageIcon)" />
        </span>
        <h2>{{ pageTitle }}</h2>
      </header>

      <div class="viewer-fields">
        <div v-if="isAppearance" class="viewer-dim">
          <button
            type="button"
            class="viewer-dim__btn"
            :class="{ 'is-on': queryDim === 'tester' }"
            @click="queryDim = 'tester'"
          >
            外观测试机
          </button>
          <button
            type="button"
            class="viewer-dim__btn"
            :class="{ 'is-on': queryDim === 'mold' }"
            @click="queryDim = 'mold'"
          >
            注塑机
          </button>
        </div>

        <label class="viewer-field">
          <span>项目</span>
          <el-select
            v-if="projects.length"
            :model-value="projectId"
            filterable
            placeholder="项目"
            style="width: 148px"
            @change="onProjectChange"
          >
            <el-option
              v-for="item in projects"
              :key="item.project_id"
              :label="item.display_name"
              :value="item.project_id"
            />
          </el-select>
          <span v-else class="viewer-muted">暂无项目</span>
        </label>

        <label class="viewer-field">
          <span>{{ machineFieldLabel }}</span>
          <el-select
            v-model="machine"
            :placeholder="machineFieldLabel"
            style="width: 120px"
          >
            <el-option
              v-for="code in machineChoices"
              :key="code"
              :label="code"
              :value="code"
            />
          </el-select>
        </label>

        <label v-if="!isAppearance || isMoldDim" class="viewer-field">
          <span>穴位</span>
          <el-select v-model="cavity" placeholder="穴位" style="width: 96px">
            <el-option
              v-for="code in cavities"
              :key="code"
              :label="`${code}穴`"
              :value="code"
            />
          </el-select>
        </label>

        <label v-if="isAppearance" class="viewer-field">
          <span>视角</span>
          <el-select v-model="camera" placeholder="视角" style="width: 132px">
            <el-option
              v-for="code in cameras"
              :key="code"
              :label="code"
              :value="code"
            />
          </el-select>
        </label>

        <label class="viewer-field">
          <span>{{ dateFieldLabel }}</span>
          <el-select
            v-model="dateStr"
            :placeholder="dateFieldLabel"
            style="width: 140px"
          >
            <el-option
              v-for="day in dates"
              :key="day"
              :label="formatDate(day)"
              :value="day"
            />
          </el-select>
        </label>

        <label v-if="!isAppearance" class="viewer-field">
          <span>状态</span>
          <el-select v-model="status" placeholder="状态" style="width: 120px">
            <el-option
              v-for="item in statuses"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </label>

        <label class="viewer-field viewer-field--qr">
          <span>二维码</span>
          <el-input
            v-model="qrQuery"
            clearable
            placeholder="扫码或输入文件名"
            @keyup.enter="searchByName"
          >
            <template #prefix>
              <component :is="useRenderIcon('ri/qr-scan-2-line')" />
            </template>
          </el-input>
        </label>

        <div class="viewer-actions">
          <el-button :disabled="!ready || !projectId" @click="searchByName">
            搜索
          </el-button>
          <el-button
            type="primary"
            :disabled="ready && !canQuery"
            @click="startCheck"
          >
            {{ ready ? "开始照片检查" : "去配置目录" }}
          </el-button>
        </div>
      </div>
    </section>

    <div v-if="current" class="viewer-stage">
      <div class="viewer-frame">
        <div class="viewer-chrome">
          <strong v-if="isAppearance">
            <template v-if="isMoldDim">
              {{ current.machine }} · {{ current.cavity }}穴 ·
              {{ current.camera || "—" }}
            </template>
            <template v-else>
              {{ current.machine }} · {{ current.camera || current.cavity }}
            </template>
          </strong>
          <strong v-else>{{ current.machine }} · {{ current.cavity }}穴</strong>
          <span>{{ counter }}</span>
          <span
            v-if="!isAppearance"
            class="viewer-status"
            :class="{ ok: (current.status || status) === 'OK' }"
          >
            {{ current.status || status }}
          </span>
        </div>
        <button
          type="button"
          class="viewer-nav"
          :disabled="index === 0"
          aria-label="上一张"
          @click="prev"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="none"
              stroke="currentColor"
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M15 6 9 12l6 6"
            />
          </svg>
        </button>
        <img :src="current.view_url" :alt="current.filename" />
        <button
          type="button"
          class="viewer-nav"
          :disabled="index >= images.length - 1"
          aria-label="下一张"
          @click="next"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="none"
              stroke="currentColor"
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="m9 6 6 6-6 6"
            />
          </svg>
        </button>
        <p class="viewer-caption" :title="current.filename">
          {{ current.filename }}
        </p>
      </div>

      <div class="viewer-dock">
        <div ref="filmRef" class="viewer-film" role="list">
          <button
            v-for="(item, i) in images"
            :key="item.id || item.rel_path"
            type="button"
            class="viewer-thumb"
            :data-active="i === index"
            :class="{ active: i === index }"
            :aria-label="item.filename"
            @click="jump(i)"
          >
            <img :src="item.view_url" :alt="item.filename" loading="lazy" />
            <span>{{ i + 1 }}</span>
          </button>
        </div>
        <p class="viewer-keys">左右方向键翻页</p>
      </div>
    </div>

    <div v-else-if="!loading" class="viewer-empty">
      <span class="viewer-empty__icon">
        <component :is="useRenderIcon('ri/image-line')" />
      </span>
      <p>
        {{
          started
            ? "这个筛选下没有照片"
            : "选定条件后开始检查，或扫码搜索文件名"
        }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.viewer-page {
  box-sizing: border-box;
  min-height: calc(100vh - 96px);
  padding: 20px 24px 28px;
  background:
    radial-gradient(
      1100px 420px at 8% -12%,
      rgb(64 158 255 / 10%),
      transparent 55%
    ),
    linear-gradient(180deg, #f7f9fc 0%, #eef2f7 100%);
}

.viewer-bar {
  padding: 14px 16px 16px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow: 0 8px 24px rgb(15 23 42 / 5%);
}

.viewer-bar__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 12px;
}

.viewer-bar__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  font-size: 18px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 8px;
}

.viewer-bar__head h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #1f2a37;
}

.viewer-fields {
  display: flex;
  flex-wrap: nowrap;
  align-items: flex-end;
  gap: 8px 10px;
  margin-top: 14px;
  padding: 10px 12px;
  overflow-x: auto;
  background: #f8fafc;
  border-radius: 10px;
}

.viewer-dim {
  display: flex;
  flex: 0 0 auto;
  gap: 0;
  overflow: hidden;
  border: 1px solid #d0d7de;
  border-radius: 8px;
  background: #fff;
}

.viewer-dim__btn {
  padding: 7px 12px;
  border: 0;
  background: transparent;
  color: #4b5563;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.viewer-dim__btn + .viewer-dim__btn {
  border-left: 1px solid #d0d7de;
}

.viewer-dim__btn.is-on {
  color: #fff;
  background: #1e4e79;
}

.viewer-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.viewer-field > span:first-child {
  font-size: 12px;
  font-weight: 600;
  color: #4b5563;
}

.viewer-field--qr {
  flex: 1 1 180px;
  min-width: 140px;
  max-width: 280px;
}

.viewer-muted {
  font-size: 13px;
  color: #4b5563;
}

.viewer-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 8px;
  padding-bottom: 1px;
}

.viewer-fields :deep(.el-select),
.viewer-fields :deep(.el-input) {
  min-width: 0;
}

.viewer-stage {
  display: grid;
  gap: 0;
  margin-top: 16px;
  overflow: hidden;
  background: #0b1220;
  border-radius: 12px;
  box-shadow: 0 10px 28px rgb(15 23 42 / 12%);
}

.viewer-frame {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: min(58vh, 680px);
  background: #0b1220;
}

.viewer-frame > img {
  max-width: 100%;
  max-height: 58vh;
  object-fit: contain;
}

.viewer-chrome,
.viewer-caption {
  position: absolute;
  right: 0;
  left: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  color: #f9fafb;
  font-size: 13px;
  background: linear-gradient(
    180deg,
    rgb(11 18 32 / 78%) 0%,
    rgb(11 18 32 / 0%) 100%
  );
  pointer-events: none;
}

.viewer-chrome {
  top: 0;
}

.viewer-chrome strong {
  font-size: 15px;
  font-weight: 700;
}

.viewer-caption {
  bottom: 0;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(
    0deg,
    rgb(11 18 32 / 82%) 0%,
    rgb(11 18 32 / 0%) 100%
  );
  text-overflow: ellipsis;
  white-space: nowrap;
}

.viewer-status {
  margin-left: auto;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 600;
  color: #9a3412;
  pointer-events: auto;
  background: #ffedd5;
  border-radius: 999px;
}

.viewer-status.ok {
  color: #166534;
  background: #dcfce7;
}

.viewer-nav {
  position: absolute;
  top: 50%;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  padding: 0;
  line-height: 1;
  color: #fff;
  cursor: pointer;
  background: rgb(17 24 39 / 55%);
  border: 0;
  border-radius: 999px;
  transform: translateY(-50%);
}

.viewer-nav:first-of-type {
  left: 12px;
}

.viewer-nav:last-of-type {
  right: 12px;
}

.viewer-nav:hover:not(:disabled) {
  background: rgb(17 24 39 / 78%);
}

.viewer-nav:disabled {
  opacity: 0.28;
  cursor: default;
}

.viewer-nav svg {
  width: 20px;
  height: 20px;
}

.viewer-nav:focus-visible {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}

.viewer-dock {
  display: grid;
  gap: 8px;
  padding: 12px 14px 14px;
  background: #111827;
}

.viewer-film {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  scrollbar-color: #4b5563 transparent;
}

.viewer-thumb {
  position: relative;
  flex: 0 0 auto;
  width: 64px;
  height: 48px;
  padding: 0;
  overflow: hidden;
  cursor: pointer;
  background: #1f2937;
  border: 2px solid transparent;
  border-radius: 8px;
}

.viewer-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.viewer-thumb span {
  position: absolute;
  right: 4px;
  bottom: 3px;
  padding: 0 4px;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  line-height: 16px;
  color: #fff;
  background: rgb(17 24 39 / 72%);
  border-radius: 4px;
}

.viewer-thumb.active {
  border-color: #60a5fa;
}

.viewer-thumb:focus-visible {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}

.viewer-keys {
  margin: 0;
  color: #9ca3af;
  font-size: 12px;
}

.viewer-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 320px;
  margin-top: 16px;
  color: #4b5563;
  background: #fff;
  border: 1px dashed #d1d5db;
  border-radius: 12px;
}

.viewer-empty__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  font-size: 22px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 10px;
}

.viewer-empty p {
  margin: 0;
  font-size: 14px;
}

@media (max-width: 900px) {
  .viewer-page {
    padding: 12px;
  }

  .viewer-frame {
    min-height: 46vh;
  }

  .viewer-frame > img {
    max-height: 46vh;
  }
}
</style>
