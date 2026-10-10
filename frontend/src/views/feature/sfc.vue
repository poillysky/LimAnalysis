<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  clearSfcLogs,
  createSfcAccount,
  deleteSfcAccount,
  runSfcNow,
  saveSfcConfig,
  sfcOverview,
  updateSfcAccount,
  uploadSfcCsv,
  waitForSfcJob,
  type SfcAccount,
  type SfcConfig,
  type SfcProjectRow
} from "@/api/modules/sfc";
import { updateProject } from "@/api/modules/feature";
import { backendErrorHint } from "@/api/http";
import { switchValue } from "@/utils/switchValue";
import type { UploadFile, UploadInstance } from "element-plus";

defineOptions({
  name: "FeatureSfc"
});

type LogRow = {
  id?: number;
  started_at: string;
  ended_at: string;
  trigger: string;
  status: string;
  message: string;
  project_id?: string;
  project_name?: string;
  account?: string;
  rows_affected?: number;
  rows_inserted?: number;
  rows_updated?: number;
  duration?: number;
  detail?: {
    lines?: { time: string; level: string; message: string }[];
    rows_inserted?: number;
    rows_updated?: number;
  };
};

const activeTab = ref("config");
const loading = ref(false);
const saving = ref(false);
const running = ref(false);
const backendHint = ref("");
const accounts = ref<SfcAccount[]>([]);
const projects = ref<SfcProjectRow[]>([]);
const logs = ref<LogRow[]>([]);
const lastRunTime = ref("");
const lastRunStatus = ref("");
const config = reactive<SfcConfig>({
  sso_login_url: "",
  sfc_base_url: "",
  sfc_logon_path: "",
  sfc_data_path: "",
  line_option: "all",
  section_option: "LIM",
  crawl_interval: 10,
  retry: 3,
  is_active: false,
  is_running: false,
  last_run_time: "",
  last_run_status: ""
});
const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const accountForm = reactive({
  name: "",
  username: "",
  password: "",
  sort_order: 0,
  enabled: true
});
const projectDialogVisible = ref(false);
const projectSaving = ref(false);
const projectForm = reactive({
  project_id: "",
  display_name: "",
  sfc_code: "",
  btype: "0",
  prefix: "",
  enabled: true
});

function defaultSfcCode(displayName: string) {
  const name = (displayName || "").trim();
  if (!name) return "";
  return name.toUpperCase().startsWith("SFC") ? name : `SFC${name}`;
}
const enabledProjectCount = computed(
  () => projects.value.filter(item => item.enabled).length
);
const enabledAccountCount = computed(
  () => accounts.value.filter(item => item.enabled).length
);
const enabledAccounts = computed(() =>
  accounts.value.filter(item => item.enabled)
);
const enabledProjects = computed(() =>
  projects.value.filter(item => item.enabled)
);
const topologyTrigger = computed(() =>
  config.is_active ? "定时调度" : "手动触发"
);
const uploadProjectId = ref("");
const uploadFile = ref<File | null>(null);
const uploading = ref(false);
const uploadResult = ref<{
  rows: number;
  rows_inserted?: number;
  rows_updated?: number;
  table: string;
  display_name: string;
} | null>(null);
const uploadRef = ref<UploadInstance>();
const uploadTarget = computed(() => {
  const item = projects.value.find(p => p.project_id === uploadProjectId.value);
  if (!item) return null;
  return {
    name: item.display_name || item.project_id,
    table: `${item.prefix || item.project_id}_raw`
  };
});
const uploadFileMeta = computed(() => {
  const file = uploadFile.value;
  if (!file) return null;
  const kb = file.size / 1024;
  const size =
    kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(kb))} KB`;
  return { name: file.name, size };
});
const canUpload = computed(
  () => Boolean(uploadProjectId.value && uploadFile.value) && !uploading.value
);
let timer: ReturnType<typeof setInterval> | null = null;

function statusType(status: string) {
  const value = (status || "").toLowerCase();
  if (!value) return "info";
  if (["ok", "success", "succeeded", "done"].includes(value)) return "success";
  if (["partial"].includes(value)) return "warning";
  if (["running", "pending", "start"].some(k => value.includes(k)))
    return "warning";
  if (["fail", "error", "timeout"].some(k => value.includes(k))) return "danger";
  return "info";
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    success: "成功",
    failed: "失败",
    partial: "部分成功",
    running: "进行中",
    fail: "失败",
    error: "失败"
  };
  return map[(status || "").toLowerCase()] || status || "—";
}

function triggerLabel(trigger: string) {
  const map: Record<string, string> = {
    manual: "手动",
    auto: "自动",
    upload: "上传"
  };
  return map[(trigger || "").toLowerCase()] || trigger || "—";
}

function formatDuration(sec: number) {
  const n = Number(sec) || 0;
  if (n <= 0) return "—";
  if (n < 1) return `${Math.round(n * 1000)} ms`;
  if (n < 60) return `${n.toFixed(1)} 秒`;
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return `${m} 分 ${s} 秒`;
}

function dash(value: string | number | null | undefined) {
  if (value === 0) return "0";
  if (value == null || value === "") return "—";
  return String(value);
}

/** 手动刷新：显式传 false，避免 @click 把 MouseEvent 当成 silent 传进来 */
function refresh() {
  return load(false);
}

async function load(silent = false) {
  // silent：轮询时不盖整页 loading，避免采集中页面“假死”
  if (!silent) loading.value = true;
  backendHint.value = "";
  try {
    const res = await sfcOverview();
    const data = (res as { data?: Record<string, unknown> })?.data || {};
    Object.assign(config, data.config || {});
    accounts.value = (data.accounts as SfcAccount[]) || [];
    projects.value = (data.projects as SfcProjectRow[]) || [];
    const status = (data.status || {}) as {
      is_running?: boolean;
      logs?: LogRow[];
    };
    running.value = Boolean(status.is_running || config.is_running);
    lastRunTime.value = config.last_run_time || "";
    lastRunStatus.value = config.last_run_status || "";
    logs.value = status.logs || [];
  } catch (error) {
    if (!silent) backendHint.value = backendErrorHint(error);
  } finally {
    if (!silent) loading.value = false;
  }
}

async function onSaveConfig() {
  saving.value = true;
  try {
    await saveSfcConfig({
      sso_login_url: config.sso_login_url,
      sfc_base_url: config.sfc_base_url,
      sfc_logon_path: config.sfc_logon_path,
      sfc_data_path: config.sfc_data_path,
      line_option: config.line_option,
      section_option: config.section_option,
      crawl_interval: Number(config.crawl_interval) || 10,
      retry: Number(config.retry) || 3,
      is_active: config.is_active
    });
    ElMessage.success("已保存");
    await load();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

function openCreate() {
  editingId.value = null;
  accountForm.name = "";
  accountForm.username = "";
  accountForm.password = "";
  accountForm.sort_order = 0;
  accountForm.enabled = true;
  dialogVisible.value = true;
}

function openEdit(row: SfcAccount) {
  editingId.value = row.id;
  accountForm.name = row.name;
  accountForm.username = row.username;
  accountForm.password = "";
  accountForm.sort_order = row.sort_order;
  accountForm.enabled = row.enabled;
  dialogVisible.value = true;
}

async function submitAccount() {
  if (!accountForm.username.trim()) {
    ElMessage.warning("请填写用户名");
    return;
  }
  if (editingId.value == null && !accountForm.password) {
    ElMessage.warning("请填写密码");
    return;
  }
  try {
    if (editingId.value == null) {
      await createSfcAccount({
        ...accountForm,
        username: accountForm.username.trim()
      });
    } else {
      const payload: Record<string, unknown> = {
        name: accountForm.name,
        username: accountForm.username.trim(),
        sort_order: accountForm.sort_order,
        enabled: accountForm.enabled
      };
      if (accountForm.password) payload.password = accountForm.password;
      await updateSfcAccount(editingId.value, payload);
    }
    ElMessage.success("已保存");
    dialogVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  }
}

async function onDelete(row: SfcAccount) {
  try {
    await ElMessageBox.confirm(`删除账号 ${row.username}？`, "确认", {
      type: "warning"
    });
  } catch {
    return;
  }
  try {
    await deleteSfcAccount(row.id);
    ElMessage.success("已删除");
    await load();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  }
}

async function onClearLogs() {
  if (!logs.value.length) {
    ElMessage.info("暂无日志可清除");
    return;
  }
  const hasRunningRow = logs.value.some(item => item.status === "running");
  const busy = running.value || hasRunningRow;
  try {
    if (busy) {
      await ElMessageBox.confirm(
        "检测到「采集中」或任务未结束。中途清日志容易留下死记录。\n\n选「强制清除」可删掉含进行中的全部日志（推荐用于死记录）。",
        "采集未结束",
        {
          type: "warning",
          confirmButtonText: "强制清除",
          cancelButtonText: "取消"
        }
      );
      const res = await clearSfcLogs(true);
      const deleted = res?.data?.deleted ?? 0;
      ElMessage.success(deleted ? `已强制清除 ${deleted} 条` : "已清除");
    } else {
      await ElMessageBox.confirm("清除全部运行日志？", "确认", {
        type: "warning"
      });
      const res = await clearSfcLogs(false);
      const deleted = res?.data?.deleted ?? 0;
      ElMessage.success(deleted ? `已清除 ${deleted} 条` : "已清除");
    }
    await load();
  } catch (error) {
    if (error === "cancel" || error === "close") return;
    // 默认清除撞上进行中 → 提示后可再强制
    const status = (error as { response?: { status?: number } })?.response
      ?.status;
    if (status === 409) {
      try {
        await ElMessageBox.confirm(
          `${backendErrorHint(error)}\n\n是否强制清除？`,
          "无法清除",
          { type: "warning", confirmButtonText: "强制清除" }
        );
        const res = await clearSfcLogs(true);
        ElMessage.success(
          res?.data?.deleted ? `已强制清除 ${res.data.deleted} 条` : "已清除"
        );
        await load();
      } catch {
        /* cancel */
      }
      return;
    }
    ElMessage.error(backendErrorHint(error));
  }
}

async function onRun() {
  try {
    const res = await runSfcNow();
    const data = res?.data;
    if (!data?.accepted || !data.job_id) {
      ElMessage.warning(data?.message || "无法入队（可能已有采集任务）");
      return;
    }
    ElMessage.success(`已提交采集任务 #${data.job_id}，等待 Worker…`);
    running.value = true;
    const job = await waitForSfcJob(data.job_id);
    if (job.status === "success") {
      ElMessage.success(job.message || "采集完成");
    } else {
      ElMessage.error(job.message || "采集失败");
    }
    await load(true);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    running.value = false;
    await load(true);
  }
}

function openProjectEdit(row: SfcProjectRow) {
  projectForm.project_id = row.project_id;
  projectForm.display_name = row.display_name;
  projectForm.sfc_code = row.sfc_code || defaultSfcCode(row.display_name);
  projectForm.btype = row.btype || "0";
  projectForm.prefix = row.prefix || "";
  projectForm.enabled = row.enabled;
  projectDialogVisible.value = true;
}

async function onToggleProject(row: SfcProjectRow, enabled: boolean) {
  try {
    await updateProject(row.project_id, { enabled });
    row.enabled = enabled;
    ElMessage.success(enabled ? "已启用" : "已停用");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
    await load();
  }
}

async function submitProject() {
  if (!projectForm.prefix.trim()) {
    ElMessage.warning("请填写前缀");
    return;
  }
  projectSaving.value = true;
  try {
    await updateProject(projectForm.project_id, {
      sfc_code:
        projectForm.sfc_code.trim() ||
        defaultSfcCode(projectForm.display_name),
      btype: projectForm.btype.trim() || "0",
      prefix: projectForm.prefix.trim(),
      enabled: projectForm.enabled
    });
    ElMessage.success("已保存");
    projectDialogVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    projectSaving.value = false;
  }
}

async function onUpload() {
  if (!uploadProjectId.value) {
    ElMessage.warning("请选择项目");
    return;
  }
  if (!uploadFile.value) {
    ElMessage.warning("请选择 CSV 文件");
    return;
  }
  uploading.value = true;
  uploadResult.value = null;
  try {
    const res = await uploadSfcCsv(uploadProjectId.value, uploadFile.value);
    const data = res?.data;
    if (!data?.accepted || !data.job_id) {
      ElMessage.warning(data?.message || "无法入队");
      return;
    }
    ElMessage.info(`已提交入库任务 #${data.job_id}，等待 Worker…`);
    const job = await waitForSfcJob(data.job_id);
    if (job.status !== "success") {
      ElMessage.error(job.message || "入库失败");
      return;
    }
    const result = job.result || {};
    const rows = Number(result.rows || 0);
    const inserted = Number(result.rows_inserted || 0);
    const updated = Number(result.rows_updated || 0);
    uploadResult.value = {
      rows,
      rows_inserted: inserted,
      rows_updated: updated,
      table: String(result.table || ""),
      display_name: String(result.display_name || "")
    };
    ElMessage.success(
      `已入库 ${rows} 行（新增 ${inserted} / 更新 ${updated}） → ${uploadResult.value.table}`
    );
    await load(true);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    uploading.value = false;
  }
}

function onUploadChange(file: UploadFile) {
  uploadFile.value = file.raw || null;
  uploadResult.value = null;
}

function clearUploadFile() {
  uploadFile.value = null;
  uploadResult.value = null;
  uploadRef.value?.clearFiles();
}

watch(activeTab, tab => {
  if (tab === "logs" || tab === "topology" || tab === "upload") load();
});

onMounted(() => {
  load();
  timer = setInterval(() => {
    if (
      (activeTab.value === "logs" || activeTab.value === "topology") &&
      running.value
    ) {
      load(true);
    }
  }, 4000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="sfc-page">
    <el-alert
      v-if="backendHint"
      class="mb-4"
      type="warning"
      :closable="false"
      :title="backendHint"
    />

    <div
      v-if="loading"
      class="sfc-boot"
      v-loading="true"
      element-loading-text="加载配置…"
    />

    <el-tabs v-else v-model="activeTab" class="sfc-tabs">
      <el-tab-pane label="爬虫配置" name="config">
        <section class="sfc-panel">
          <header class="sfc-panel__head">
            <div>
              <h2>采集配置</h2>
              <p>SSO / SFC 地址与调度参数</p>
            </div>
            <el-button type="primary" :loading="saving" @click="onSaveConfig">
              保存配置
            </el-button>
          </header>
          <el-form label-position="top" class="sfc-form">
            <div class="sfc-switch-row">
              <div>
                <div class="sfc-switch-row__label">定时采集</div>
                <div class="sfc-switch-row__hint">
                  间隔 {{ config.crawl_interval }} 分钟
                </div>
              </div>
              <el-switch v-model="config.is_active" />
            </div>
            <div class="sfc-grid">
              <el-form-item label="SSO 地址">
                <el-input v-model="config.sso_login_url" />
              </el-form-item>
              <el-form-item label="SFC 基址">
                <el-input v-model="config.sfc_base_url" />
              </el-form-item>
              <el-form-item label="登录路径">
                <el-input v-model="config.sfc_logon_path" />
              </el-form-item>
              <el-form-item label="数据路径">
                <el-input v-model="config.sfc_data_path" />
              </el-form-item>
              <el-form-item label="Line">
                <el-input v-model="config.line_option" />
              </el-form-item>
              <el-form-item label="Section">
                <el-input v-model="config.section_option" />
              </el-form-item>
              <el-form-item label="间隔(分钟)">
                <el-input-number
                  v-model="config.crawl_interval"
                  :min="1"
                  :max="1440"
                  :controls="false"
                />
              </el-form-item>
              <el-form-item label="重试次数">
                <el-input-number
                  v-model="config.retry"
                  :min="1"
                  :max="10"
                  :controls="false"
                />
              </el-form-item>
            </div>
          </el-form>
        </section>

        <section class="sfc-panel">
          <header class="sfc-panel__head">
            <div>
              <h2>账号池</h2>
              <p>{{ enabledAccountCount }}/{{ accounts.length }} 账号启用</p>
            </div>
            <el-button type="primary" @click="openCreate">新增账号</el-button>
          </header>
          <el-table
            :data="accounts"
            class="sfc-table"
            empty-text="暂无账号"
            :row-class-name="
              ({ row }: { row: SfcAccount }) => (row.enabled ? '' : 'is-disabled')
            "
          >
            <el-table-column label="用户名" min-width="140" align="left">
              <template #default="{ row }">
                <code class="code-chip">{{ row.username }}</code>
              </template>
            </el-table-column>
            <el-table-column label="备注" min-width="120" align="left">
              <template #default="{ row }">
                {{ dash(row.name) }}
              </template>
            </el-table-column>
            <el-table-column
              prop="sort_order"
              label="顺序"
              min-width="80"
              align="left"
            />
            <el-table-column label="启用" width="80" align="center">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.enabled ? 'success' : 'info'"
                  effect="plain"
                  round
                >
                  {{ row.enabled ? "是" : "否" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="上次" min-width="100" align="left">
              <template #default="{ row }">
                <el-tag
                  v-if="row.last_use_status"
                  size="small"
                  :type="statusType(row.last_use_status)"
                  effect="light"
                  round
                >
                  {{ row.last_use_status }}
                </el-tag>
                <span v-else class="cell-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" align="center">
              <template #default="{ row }">
                <el-button type="primary" link @click="openEdit(row)">
                  编辑
                </el-button>
                <el-button type="danger" link @click="onDelete(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section class="sfc-panel">
          <header class="sfc-panel__head">
            <div>
              <h2>启用项目</h2>
              <p>{{ enabledProjectCount }}/{{ projects.length }} 项目启用</p>
            </div>
          </header>
          <el-table
            :data="projects"
            class="sfc-table"
            empty-text="暂无项目"
            :row-class-name="
              ({ row }: { row: SfcProjectRow }) =>
                row.enabled ? '' : 'is-disabled'
            "
          >
            <el-table-column label="项目" min-width="160" align="left">
              <template #default="{ row }">
                <span class="project-name">
                  {{ row.display_name }}
                  <span class="project-id">({{ row.project_id }})</span>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="sfc_code" min-width="120" align="left">
              <template #default="{ row }">
                <code class="code-chip">{{ dash(row.sfc_code) }}</code>
              </template>
            </el-table-column>
            <el-table-column label="type" min-width="90" align="left">
              <template #default="{ row }">
                <el-tag size="small" effect="plain" round>
                  {{ dash(row.btype || "0") }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="前缀" min-width="120" align="left">
              <template #default="{ row }">
                <code class="code-chip">{{ dash(row.prefix) }}</code>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="80" align="center">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled"
                  @change="v => onToggleProject(row, switchValue(v))"
                />
              </template>
            </el-table-column>
            <el-table-column label="最近采集" min-width="110" align="left">
              <template #default="{ row }">
                <el-tag
                  v-if="row.last_crawl_status"
                  size="small"
                  :type="statusType(row.last_crawl_status)"
                  effect="light"
                  round
                >
                  {{ row.last_crawl_status }}
                </el-tag>
                <span v-else class="cell-muted">未采集</span>
              </template>
            </el-table-column>
            <el-table-column label="行数" min-width="80" align="left">
              <template #default="{ row }">
                <span class="num-cell">{{ dash(row.last_crawl_rows) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="时间" min-width="150" align="left">
              <template #default="{ row }">
                <span class="time-cell">{{ dash(row.last_crawl_time) }}</span>
              </template>
            </el-table-column>
            <el-table-column
              label="操作"
              width="80"
              fixed="right"
              align="center"
            >
              <template #default="{ row }">
                <el-button type="primary" link @click="openProjectEdit(row)">
                  编辑
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="运行日志" name="logs">
        <section class="sfc-panel logs-hero">
          <header class="sfc-panel__head">
            <div>
              <h2>运行状态</h2>
              <p>查看最近采集结果，或立即发起一轮</p>
            </div>
            <div class="sfc-panel__actions">
              <el-button type="primary" :disabled="running" @click="() => onRun()">
                立即采集
              </el-button>
              <el-button @click="refresh">刷新</el-button>
            </div>
          </header>
          <div class="stat-grid">
            <article class="stat-card" :class="running ? 'is-busy' : 'is-idle'">
              <div class="stat-card__label">当前状态</div>
              <div class="stat-card__value">
                {{ running ? "采集中" : "空闲" }}
              </div>
              <div class="stat-card__hint">
                {{ config.is_active ? "定时已开" : "定时关闭" }}
              </div>
            </article>
            <article class="stat-card">
              <div class="stat-card__label">上次结果</div>
              <div class="stat-card__value">
                <el-tag
                  v-if="lastRunStatus"
                  size="small"
                  :type="statusType(lastRunStatus)"
                  effect="light"
                  round
                >
                  {{ statusLabel(lastRunStatus) }}
                </el-tag>
                <span v-else class="cell-muted">尚未运行</span>
              </div>
              <div class="stat-card__hint">最近一轮采集</div>
            </article>
            <article class="stat-card">
              <div class="stat-card__label">上次时间</div>
              <div class="stat-card__value time">{{ dash(lastRunTime) }}</div>
              <div class="stat-card__hint">完成或失败时间</div>
            </article>
            <article class="stat-card">
              <div class="stat-card__label">采集范围</div>
              <div class="stat-card__value">
                {{ enabledProjects.length }}
                <span class="stat-card__unit">项目</span>
              </div>
              <div class="stat-card__hint">
                {{ enabledAccounts.length }} 个启用账号
              </div>
            </article>
          </div>
        </section>

        <section class="sfc-panel">
          <header class="sfc-panel__head">
            <div>
              <h2>运行日志</h2>
              <p>按项目记录：账号、行数、耗时与逐步明细</p>
            </div>
            <div class="sfc-panel__actions">
              <span class="panel-count">{{ logs.length }} 条记录</span>
              <el-button
                :disabled="!logs.length"
                @click="onClearLogs"
              >
                清除日志
              </el-button>
            </div>
          </header>

          <div v-if="!logs.length" class="empty-block">
            <div class="empty-block__title">还没有运行记录</div>
            <div class="empty-block__desc">
              点击上方「立即采集」发起一轮，或开启定时采集后自动产生日志
            </div>
          </div>

          <el-table v-else :data="logs" class="sfc-table">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div v-if="row.detail?.lines?.length" class="log-lines">
                  <div
                    v-for="(line, idx) in row.detail.lines"
                    :key="idx"
                    class="log-line"
                    :class="`is-${line.level}`"
                  >
                    <span class="log-time">{{ line.time }}</span>
                    <span class="log-level">{{ line.level }}</span>
                    <span>{{ line.message }}</span>
                  </div>
                </div>
                <div v-else class="cell-muted log-empty">无明细</div>
              </template>
            </el-table-column>
            <el-table-column label="开始" min-width="150" align="left">
              <template #default="{ row }">
                <span class="time-cell">{{ dash(row.started_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="项目" min-width="110" align="left">
              <template #default="{ row }">
                {{ dash(row.project_name || row.project_id) }}
              </template>
            </el-table-column>
            <el-table-column label="账号" min-width="100" align="left">
              <template #default="{ row }">
                {{ dash(row.account) }}
              </template>
            </el-table-column>
            <el-table-column label="来源" width="88" align="center">
              <template #default="{ row }">
                <el-tag size="small" effect="plain" round>
                  {{ triggerLabel(row.trigger) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="statusType(row.status)"
                  effect="light"
                  round
                >
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="行数" width="96" align="right">
              <template #default="{ row }">
                <span class="time-cell">{{
                  Number(row.rows_affected || 0).toLocaleString()
                }}</span>
              </template>
            </el-table-column>
            <el-table-column label="更新" width="96" align="right">
              <template #default="{ row }">
                <span class="time-cell">{{
                  Number(row.rows_updated || 0).toLocaleString()
                }}</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="96" align="right">
              <template #default="{ row }">
                <span class="time-cell">{{
                  formatDuration(Number(row.duration || 0))
                }}</span>
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="200" align="left">
              <template #default="{ row }">
                <span class="msg-cell">{{ dash(row.message) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="爬虫执行拓扑图" name="topology">
        <section class="sfc-panel topo-panel">
          <header class="sfc-panel__head">
            <div>
              <h2>执行拓扑</h2>
              <p>与 runner 一致的串行采集链路</p>
            </div>
            <div class="sfc-panel__actions">
              <span
                class="status-pill"
                :class="running ? 'is-busy' : 'is-idle'"
              >
                {{ running ? "采集中" : "空闲" }}
              </span>
              <el-button @click="refresh">刷新</el-button>
            </div>
          </header>

          <div class="stat-grid topo-stats">
            <article class="stat-card" :class="running ? 'is-busy' : 'is-idle'">
              <div class="stat-card__label">当前状态</div>
              <div class="stat-card__value">
                {{ running ? "采集中" : "空闲" }}
              </div>
              <div class="stat-card__hint">{{ topologyTrigger }}</div>
            </article>
            <article class="stat-card">
              <div class="stat-card__label">启用账号</div>
              <div class="stat-card__value">
                {{ enabledAccounts.length }}
                <span class="stat-card__unit">个</span>
              </div>
              <div class="stat-card__hint">轮询登录</div>
            </article>
            <article class="stat-card">
              <div class="stat-card__label">启用项目</div>
              <div class="stat-card__value">
                {{ enabledProjects.length }}
                <span class="stat-card__unit">个</span>
              </div>
              <div class="stat-card__hint">串行下载入库</div>
            </article>
            <article class="stat-card">
              <div class="stat-card__label">上次结果</div>
              <div class="stat-card__value">
                <el-tag
                  v-if="lastRunStatus"
                  size="small"
                  :type="statusType(lastRunStatus)"
                  effect="light"
                  round
                >
                  {{ statusLabel(lastRunStatus) }}
                </el-tag>
                <span v-else class="cell-muted">尚未运行</span>
              </div>
              <div class="stat-card__hint">{{ dash(lastRunTime) }}</div>
            </article>
          </div>
        </section>

        <section class="sfc-panel topo-panel">
          <div class="topo" :class="{ 'is-running': running }">
            <ol class="topo-rail">
              <li class="topo-step">
                <div class="topo-step__index">1</div>
                <div class="topo-step__card is-trigger">
                  <div class="topo-step__title">触发</div>
                  <div class="topo-step__body">{{ topologyTrigger }}</div>
                  <div class="topo-step__meta">
                    间隔 {{ config.crawl_interval }} 分钟 · 定时
                    {{ config.is_active ? "开" : "关" }}
                  </div>
                </div>
              </li>
              <li class="topo-step">
                <div class="topo-step__index">2</div>
                <div class="topo-step__card">
                  <div class="topo-step__title">加载配置</div>
                  <div class="topo-step__body">SSO / SFC 地址与参数</div>
                  <div class="topo-step__meta">
                    retry {{ config.retry }} · line {{ config.line_option }} ·
                    section {{ config.section_option }}
                  </div>
                </div>
              </li>
              <li class="topo-step">
                <div class="topo-step__index">3</div>
                <div class="topo-step__card is-pool">
                  <div class="topo-step__title">账号池登录</div>
                  <div class="topo-step__body">
                    <template v-if="enabledAccounts.length">
                      <code
                        v-for="item in enabledAccounts.slice(0, 4)"
                        :key="item.id"
                        class="code-chip"
                      >
                        {{ item.username }}
                      </code>
                      <span
                        v-if="enabledAccounts.length > 4"
                        class="cell-muted"
                      >
                        +{{ enabledAccounts.length - 4 }}
                      </span>
                    </template>
                    <span v-else class="cell-muted">无启用账号</span>
                  </div>
                  <div class="topo-step__meta">失败换号，全部失败则中止</div>
                </div>
              </li>
              <li class="topo-step">
                <div class="topo-step__index">4</div>
                <div
                  class="topo-step__card is-session"
                  :class="{ 'is-live': running }"
                >
                  <div class="topo-step__title">会话</div>
                  <div class="topo-step__body">
                    {{ running ? "使用中" : "待命" }}
                  </div>
                  <div class="topo-step__meta">过期自动重登后继续项目</div>
                </div>
              </li>
              <li class="topo-step is-branch">
                <div class="topo-step__index">5</div>
                <div class="topo-step__card is-branch-card">
                  <div class="topo-step__title">按启用项目串行采集</div>
                  <div class="topo-step__meta topo-step__meta--tight">
                    下载 CSV → 解析 → UPSERT `{prefix}_raw`
                  </div>
                  <div class="topo-projects">
                    <article
                      v-for="(item, idx) in enabledProjects"
                      :key="item.project_id"
                      class="topo-project"
                      :class="
                        item.last_crawl_status
                          ? `is-${statusType(item.last_crawl_status)}`
                          : 'is-idle'
                      "
                    >
                      <div class="topo-project__head">
                        <span class="topo-project__ord">{{ idx + 1 }}</span>
                        <div>
                          <div class="topo-project__name">
                            {{ item.display_name }}
                            <span>({{ item.project_id }})</span>
                          </div>
                          <div class="topo-project__params">
                            <code>p={{ item.sfc_code || "—" }}</code>
                            <code>type={{ item.btype || "0" }}</code>
                            <code>{{ item.prefix || "—" }}_raw</code>
                          </div>
                        </div>
                        <el-tag
                          v-if="item.last_crawl_status"
                          size="small"
                          :type="statusType(item.last_crawl_status)"
                          effect="light"
                          round
                        >
                          {{ item.last_crawl_status }}
                        </el-tag>
                        <span v-else class="cell-muted">未采集</span>
                      </div>
                      <div class="topo-project__pipe">
                        <span>下载</span>
                        <i />
                        <span>解析</span>
                        <i />
                        <span>入库</span>
                        <em>{{ dash(item.last_crawl_rows) }} 行</em>
                      </div>
                    </article>
                    <div v-if="!enabledProjects.length" class="topo-empty">
                      暂无启用项目
                    </div>
                  </div>
                </div>
              </li>
              <li class="topo-step">
                <div class="topo-step__index">6</div>
                <div class="topo-step__card is-db">
                  <div class="topo-step__title">写入 lim_raw</div>
                  <div class="topo-step__body">各项目 raw 表 UPSERT</div>
                  <div class="topo-step__meta">按 prefix 分表落库</div>
                </div>
              </li>
              <li class="topo-step">
                <div class="topo-step__index">7</div>
                <div class="topo-step__card is-log">
                  <div class="topo-step__title">写运行日志</div>
                  <div class="topo-step__body">
                    {{ dash(lastRunStatus) }}
                  </div>
                  <div class="topo-step__meta">{{ dash(lastRunTime) }}</div>
                </div>
              </li>
              <li class="topo-step">
                <div class="topo-step__index">8</div>
                <div
                  class="topo-step__card is-done"
                  :class="{ 'is-live': running }"
                >
                  <div class="topo-step__title">结束</div>
                  <div class="topo-step__body">
                    {{ running ? "进行中" : "完成 / 待命" }}
                  </div>
                  <div class="topo-step__meta">回写项目最近采集状态</div>
                </div>
              </li>
            </ol>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="数据上传" name="upload">
        <section class="sfc-panel upload-panel">
          <header class="sfc-panel__head">
            <div>
              <h2>手动上传通道</h2>
              <p>绕过 SFC 网页，CSV 按项目 UPSERT 入库 lim_raw</p>
            </div>
            <div class="sfc-panel__actions">
              <el-button
                type="primary"
                :loading="uploading"
                :disabled="!canUpload"
                @click="onUpload"
              >
                {{ uploading ? "入库中…" : "上传入库" }}
              </el-button>
            </div>
          </header>

          <div class="upload-main">
            <div class="upload-step">
              <div class="upload-step__label">
                <span class="upload-step__num">1</span>
                目标项目
              </div>
              <el-select
                v-model="uploadProjectId"
                filterable
                clearable
                placeholder="选择要写入的项目"
                class="upload-select"
              >
                <el-option
                  v-for="item in projects"
                  :key="item.project_id"
                  :label="`${item.display_name} (${item.project_id})`"
                  :value="item.project_id"
                >
                  <div class="upload-option">
                    <span>
                      {{ item.display_name }}
                      <em>{{ item.project_id }}</em>
                    </span>
                    <code>{{ item.prefix || item.project_id }}_raw</code>
                  </div>
                </el-option>
              </el-select>

              <div v-if="uploadTarget" class="upload-summary">
                <div class="upload-summary__item">
                  <span class="upload-summary__k">项目</span>
                  <span class="upload-summary__v">{{ uploadTarget.name }}</span>
                </div>
                <div class="upload-summary__item">
                  <span class="upload-summary__k">表</span>
                  <code class="code-chip">{{ uploadTarget.table }}</code>
                </div>
                <div class="upload-summary__item">
                  <span class="upload-summary__k">策略</span>
                  <span class="upload-summary__v">UPSERT · 存在更新 / 不存在插入</span>
                </div>
              </div>
            </div>

            <div class="upload-step">
              <div class="upload-step__label">
                <span class="upload-step__num">2</span>
                CSV 文件
              </div>
              <el-upload
                ref="uploadRef"
                class="upload-drop"
                drag
                :auto-upload="false"
                :limit="1"
                accept=".csv,.txt,text/csv"
                :show-file-list="false"
                :on-exceed="() => ElMessage.warning('一次只上传一个文件')"
                :on-change="onUploadChange"
              >
                <div class="upload-drop__inner">
                  <div class="upload-drop__icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="28" height="28" fill="none">
                      <path
                        d="M12 16V4m0 0 4 4m-4-4-4 4"
                        stroke="currentColor"
                        stroke-width="1.8"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                      <path
                        d="M4 14v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"
                        stroke="currentColor"
                        stroke-width="1.8"
                        stroke-linecap="round"
                      />
                    </svg>
                  </div>
                  <div class="upload-drop__title">拖拽文件到此处，或点击选择</div>
                  <div class="upload-drop__hint">
                    支持 .csv / .txt · 上限 80MB · 按 FCoverSN 覆盖更新
                  </div>
                </div>
              </el-upload>

              <div v-if="uploadFileMeta" class="upload-file">
                <div class="upload-file__meta">
                  <span class="upload-file__name">{{ uploadFileMeta.name }}</span>
                  <span class="upload-file__size">{{ uploadFileMeta.size }}</span>
                </div>
                <el-button type="primary" link @click="clearUploadFile">
                  清除
                </el-button>
              </div>
            </div>

            <div v-if="uploadResult" class="upload-result">
              <div class="upload-result__ok">上传成功</div>
              <div class="upload-result__body">
                <span>{{ uploadResult.display_name }}</span>
                <strong>{{ uploadResult.rows.toLocaleString() }}</strong>
                <span>
                  行（新增
                  {{ Number(uploadResult.rows_inserted || 0).toLocaleString() }}
                  / 更新
                  {{ Number(uploadResult.rows_updated || 0).toLocaleString() }}）→
                </span>
                <code class="code-chip">{{ uploadResult.table }}</code>
              </div>
            </div>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="projectDialogVisible"
      :title="`编辑项目 · ${projectForm.display_name || projectForm.project_id}`"
      width="420px"
    >
      <el-form label-width="90px">
        <el-form-item label="sfc_code">
          <el-input
            v-model="projectForm.sfc_code"
            :placeholder="defaultSfcCode(projectForm.display_name) || 'SFC…'"
          />
        </el-form-item>
        <el-form-item label="type">
          <el-input v-model="projectForm.btype" placeholder="0" />
        </el-form-item>
        <el-form-item label="前缀" required>
          <el-input v-model="projectForm.prefix" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="projectForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="projectDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="projectSaving"
          @click="submitProject"
        >
          确定
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑账号' : '新增账号'"
      width="420px"
    >
      <el-form label-width="80px">
        <el-form-item label="用户名" required>
          <el-input v-model="accountForm.username" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="accountForm.name" />
        </el-form-item>
        <el-form-item label="密码" :required="editingId == null">
          <el-input
            v-model="accountForm.password"
            type="password"
            show-password
            :placeholder="editingId ? '留空不改' : ''"
          />
        </el-form-item>
        <el-form-item label="顺序">
          <el-input-number v-model="accountForm.sort_order" :controls="false" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="accountForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAccount">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
// as *：与原 @import 的全局作用域语义一致
@use "./sfc.styles/scoped.scss" as *;
</style>
