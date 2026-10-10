<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  clearDiskCleanupLogs,
  getDiskCleanup,
  listDiskCleanupLogs,
  runDiskCleanup,
  saveDiskCleanup,
  type DiskCleanupConfig,
  type DiskCleanupLog,
  type DiskDbUsage,
  type DiskPathUsage
} from "@/api/modules/diskCleanup";
import { backendErrorHint } from "@/api/http";
import { statusType } from "@/composables/useFieldList";

defineOptions({
  name: "FeatureDiskCleanup"
});

const loading = ref(false);
const saving = ref(false);
const running = ref(false);
const activeTab = ref("config");
const logs = ref<DiskCleanupLog[]>([]);
const logsLoading = ref(false);

const form = reactive({
  enabled: true,
  db_retention_days: 90,
  image_retention_days: 90,
  run_hour: 3
});

const lastRun = reactive({
  time: "",
  status: "",
  message: "",
  result: {} as Record<string, unknown>
});

const paths = reactive<{
  raw_csv: DiskPathUsage | null;
  meta: DiskPathUsage | null;
  images: DiskPathUsage | null;
}>({
  raw_csv: null,
  meta: null,
  images: null
});

const databases = reactive<{
  raw: DiskDbUsage | null;
  dwh: DiskDbUsage | null;
  defect: DiskDbUsage | null;
}>({
  raw: null,
  dwh: null,
  defect: null
});

const statusTag = computed(() => {
  const s = lastRun.status;
  if (s === "success") return { type: "success" as const, text: "上次成功" };
  if (s === "failed") return { type: "danger" as const, text: "上次失败" };
  if (s === "queued" || s === "busy")
    return { type: "warning" as const, text: s === "queued" ? "已入队" : "忙碌" };
  if (form.enabled) return { type: "info" as const, text: "已启用定时清理" };
  return { type: "info" as const, text: "已关闭定时清理" };
});

const pathCards = computed(() => [
  { key: "raw_csv" as const, title: "本地 CSV", item: paths.raw_csv },
  { key: "meta" as const, title: "元数据目录", item: paths.meta },
  { key: "images" as const, title: "图片目录", item: paths.images }
]);

function fmtDetailSize(bytes: number | null | undefined) {
  if (bytes == null) return "—";
  const n = Number(bytes);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

const dbCards = computed(() => [
  { key: "raw" as const, title: "原始库 raw", item: databases.raw },
  { key: "dwh" as const, title: "ETL 库 dwh", item: databases.dwh },
  { key: "defect" as const, title: "次品库 defect", item: databases.defect }
]);

const latestLog = computed(() => logs.value[0] || null);

function applyConfig(cfg: DiskCleanupConfig) {
  form.enabled = !!cfg.enabled;
  form.db_retention_days = Number(cfg.db_retention_days || 90);
  form.image_retention_days = Number(cfg.image_retention_days || 90);
  form.run_hour = Number(cfg.run_hour ?? 3);
  lastRun.time = cfg.last_run_time || "";
  lastRun.status = cfg.last_run_status || "";
  lastRun.message = cfg.last_run_message || "";
  lastRun.result = cfg.last_run_result || {};
}

function dash(value: unknown) {
  const text = String(value ?? "").trim();
  return text || "—";
}

function triggerLabel(trigger: string) {
  if (trigger === "auto") return "自动";
  if (trigger === "manual") return "手动";
  return trigger || "—";
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    success: "成功",
    failed: "失败",
    running: "进行中",
    queued: "已排队",
    busy: "忙碌"
  };
  return map[status] || status || "—";
}

function formatDuration(sec: number) {
  const n = Number(sec) || 0;
  if (n < 60) return `${n.toFixed(1)} 秒`;
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return `${m} 分 ${s} 秒`;
}

function onTabChange(name: string | number) {
  if (name === "logs") void loadLogs();
}

async function loadLogs(silent = false) {
  if (!silent) logsLoading.value = true;
  try {
    const res = await listDiskCleanupLogs(50);
    logs.value = res?.data?.logs || [];
  } catch (error) {
    if (!silent) ElMessage.error(backendErrorHint(error));
  } finally {
    if (!silent) logsLoading.value = false;
  }
}

async function onClearLogs() {
  if (!logs.value.length) return;
  try {
    await ElMessageBox.confirm(
      "清除全部清理日志？进行中的记录会保留。",
      "清除日志",
      { type: "warning" }
    );
  } catch {
    return;
  }
  try {
    const res = await clearDiskCleanupLogs();
    ElMessage.success(`已清除 ${res?.data?.deleted ?? 0} 条`);
    await loadLogs();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  }
}

async function load() {
  loading.value = true;
  try {
    const res = await getDiskCleanup();
    const data = res?.data;
    if (data?.config) applyConfig(data.config);
    if (data?.capacity?.paths) {
      paths.raw_csv = data.capacity.paths.raw_csv;
      paths.meta = data.capacity.paths.meta;
      paths.images = data.capacity.paths.images;
    }
    if (data?.capacity?.databases) {
      databases.raw = data.capacity.databases.raw;
      databases.dwh = data.capacity.databases.dwh;
      databases.defect = data.capacity.databases.defect;
    }
    if (activeTab.value === "logs") await loadLogs(true);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    loading.value = false;
  }
}

async function onSave() {
  saving.value = true;
  try {
    const res = await saveDiskCleanup({
      enabled: form.enabled,
      db_retention_days: form.db_retention_days,
      image_retention_days: form.image_retention_days,
      run_hour: form.run_hour
    });
    if (res?.data?.config) applyConfig(res.data.config);
    ElMessage.success("已保存清理配置");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

async function onRun() {
  try {
    await ElMessageBox.confirm(
      `将按当前保留天数清理 Postgres 旧数据与图片目录（CSV 入库成功后已即时删除）。确认入队执行？`,
      "立即清理",
      { type: "warning", confirmButtonText: "入队执行", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  running.value = true;
  try {
    const res = await runDiskCleanup();
    const msg = res?.data?.message || `已入队 #${res?.data?.job_id}`;
    ElMessage.success(msg);
    lastRun.status = res?.data?.status || "queued";
    lastRun.message = msg;
    setTimeout(() => {
      void load();
      if (activeTab.value === "logs") void loadLogs(true);
    }, 1500);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    running.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="disk-page main-content" v-loading="loading">
    <div class="disk-head">
      <div>
        <h2>磁盘清理</h2>
        <p>
          监控本机目录与三库容量；按保留天数自动清理 Postgres / 图片。CSV
          入库成功后立即删除。
        </p>
      </div>
      <el-tag :type="statusTag.type">{{ statusTag.text }}</el-tag>
    </div>

    <el-tabs v-model="activeTab" class="disk-tabs" @tab-change="onTabChange">
      <el-tab-pane label="清理配置" name="config">
    <section class="disk-capacity">
      <h3>容量监控</h3>
      <div class="disk-db-row">
        <article v-for="card in dbCards" :key="card.key" class="disk-cap-card">
          <header>
            <strong>{{ card.title }}</strong>
            <span>{{ card.item?.ok ? card.item.label : "不可用" }}</span>
          </header>
          <p v-if="card.item?.error" class="disk-err">{{ card.item.error }}</p>
          <p v-else class="disk-muted">PostgreSQL 库体积</p>
        </article>
      </div>
      <div class="disk-path-row">
        <article v-for="card in pathCards" :key="card.key" class="disk-cap-card">
          <header>
            <strong>{{ card.title }}</strong>
            <span>{{ card.item?.dir_label || "—" }}</span>
          </header>
          <p class="disk-line">
            本卷已用 {{ card.item?.used_label || "—" }} /
            {{ card.item?.total_label || "—" }}
            <template v-if="card.item?.used_pct != null">
              · {{ card.item.used_pct }}%
            </template>
            <span class="disk-muted">（整盘，不是下面目录）</span>
          </p>
          <p class="disk-line">
            目录占用 {{ card.item?.dir_label || "—" }}
            <template v-if="card.item?.dir_files != null">
              · {{ card.item.dir_files.toLocaleString() }} 文件
            </template>
            <span v-if="card.item?.dir_bytes_truncated" class="disk-err">
              （文件数超过 20 万，计数可能不完整）
            </span>
            <span class="disk-muted">（磁盘占用，含子目录）</span>
          </p>
          <template v-if="card.key === 'images' && card.item?.details?.length">
            <p
              v-for="(d, i) in card.item.details"
              :key="i"
              class="disk-path"
            >
              {{ d.label }} {{ d.path || "未配置" }}
              ·
              {{ d.exists ? fmtDetailSize(d.dir_bytes) : d.error || "不可用" }}
              <template v-if="d.exists && d.dir_files != null">
                · {{ Number(d.dir_files).toLocaleString() }} 文件
              </template>
            </p>
          </template>
          <p v-else class="disk-path">{{ card.item?.path || "未配置" }}</p>
          <p v-if="card.item?.error" class="disk-err">{{ card.item.error }}</p>
        </article>
      </div>
    </section>

    <section class="disk-panel">
      <el-form label-width="140px" class="disk-form">
        <el-form-item label="启用每日清理">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="数据库保留天数">
          <el-input-number
            v-model="form.db_retention_days"
            :min="1"
            :max="3650"
            :step="1"
          />
          <span class="disk-unit">天前数据删除</span>
        </el-form-item>
        <el-form-item label="图片保留天数">
          <el-input-number
            v-model="form.image_retention_days"
            :min="1"
            :max="3650"
            :step="1"
          />
          <span class="disk-unit">天前文件删除</span>
        </el-form-item>
        <el-form-item label="每日执行时刻">
          <el-input-number
            v-model="form.run_hour"
            :min="0"
            :max="23"
            :step="1"
          />
          <span class="disk-unit">时（Asia/Shanghai，整点）</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="onSave">
            保存
          </el-button>
          <el-button :loading="running" @click="onRun">立即清理</el-button>
          <el-button plain @click="load">刷新容量</el-button>
        </el-form-item>
      </el-form>
      <aside class="disk-aside">
        <h3>说明</h3>
        <ul>
          <li>清理由 collector.worker 串行执行，API 只入队，不堵页面。</li>
          <li>Postgres 按时间列分批删除（默认保留 90 天）。</li>
          <li>图片目录读取「图片目录」配置的注塑 / 外观根路径。</li>
          <li>CSV 上传入库成功后立即删除本地文件；失败则保留。</li>
          <li>每次清理结果见「清理日志」。</li>
        </ul>
      </aside>
    </section>
      </el-tab-pane>

      <el-tab-pane label="清理日志" name="logs">
        <section class="disk-panel disk-logs-panel" v-loading="logsLoading">
          <header class="disk-logs-head">
            <div>
              <h3>清理日志</h3>
              <p>
                最近
                {{
                  latestLog
                    ? `${dash(latestLog.ended_at || latestLog.started_at)} · ${statusLabel(latestLog.status)}`
                    : lastRun.time
                      ? `${dash(lastRun.time)} · ${statusLabel(lastRun.status)}`
                      : "尚无记录"
                }}
              </p>
            </div>
            <div class="disk-logs-actions">
              <span class="disk-count">{{ logs.length }} 条记录</span>
              <el-button :loading="running" @click="onRun">立即清理</el-button>
              <el-button :loading="logsLoading" @click="loadLogs()">
                刷新
              </el-button>
              <el-button :disabled="!logs.length" @click="onClearLogs">
                清除日志
              </el-button>
            </div>
          </header>

          <div v-if="!logs.length" class="disk-logs-empty">
            <div class="disk-logs-empty__title">还没有清理记录</div>
            <div class="disk-logs-empty__desc">
              点「立即清理」或等每日定时跑完后，这里会列出每次结果
            </div>
          </div>

          <el-table v-else :data="logs" class="disk-logs-table">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div v-if="row.detail && Object.keys(row.detail).length" class="disk-log-detail">
                  <div>
                    库行
                    {{ Number((row.detail.deleted_rows ?? row.deleted_rows) || 0).toLocaleString() }}
                    · 图片
                    {{ Number((row.detail.deleted_files ?? row.deleted_files) || 0).toLocaleString() }}
                    · 注塑
                    {{ Number(row.detail.images_mold_files || 0).toLocaleString() }}
                    · 外观
                    {{ Number(row.detail.images_appearance_files || 0).toLocaleString() }}
                  </div>
                  <div v-if="Array.isArray(row.detail.errors) && row.detail.errors.length" class="disk-err">
                    {{ row.detail.errors.slice(0, 5).join("；") }}
                  </div>
                </div>
                <div v-else class="disk-muted">无明细</div>
              </template>
            </el-table-column>
            <el-table-column label="开始" min-width="160">
              <template #default="{ row }">
                <span class="disk-num">{{ dash(row.started_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="结束" min-width="160">
              <template #default="{ row }">
                <span class="disk-num">{{ dash(row.ended_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="来源" width="96" align="center">
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
            <el-table-column label="删除库行" width="110" align="right">
              <template #default="{ row }">
                <span class="disk-num">{{
                  Number(row.deleted_rows || 0).toLocaleString()
                }}</span>
              </template>
            </el-table-column>
            <el-table-column label="删除图片" width="110" align="right">
              <template #default="{ row }">
                <span class="disk-num">{{
                  Number(row.deleted_files || 0).toLocaleString()
                }}</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="100" align="right">
              <template #default="{ row }">
                <span class="disk-num">{{
                  formatDuration(row.duration)
                }}</span>
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="220">
              <template #default="{ row }">
                {{ dash(row.message) }}
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.disk-page {
  padding: var(--la-page-pad-y) var(--la-page-pad-x) var(--la-space-xl);
}

.disk-tabs {
  margin-top: 4px;
}

.disk-logs-panel {
  display: block;
}

.disk-logs-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.disk-logs-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}

.disk-logs-head p {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.disk-logs-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.disk-count {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-right: 4px;
  font-variant-numeric: tabular-nums;
  line-height: 32px;
}

.disk-logs-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 48px 16px;
  text-align: center;
}

.disk-logs-empty__title {
  font-size: 15px;
  font-weight: 650;
}

.disk-logs-empty__desc {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.disk-logs-table {
  width: 100%;
}

.disk-num {
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}

.disk-log-detail {
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--el-text-color-regular);
}

.disk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--la-space-md);
  margin-bottom: var(--la-space-lg);
}

.disk-head h2 {
  margin: 0 0 2px;
  font-size: var(--la-page-title);
  font-weight: 650;
}

.disk-head p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--la-page-desc);
}

.disk-capacity {
  margin-bottom: 16px;
  padding: 16px 18px 18px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.disk-capacity h3 {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 650;
}

.disk-db-row,
.disk-path-row {
  display: grid;
  gap: 12px;
}

.disk-db-row {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 12px;
}

.disk-path-row {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.disk-cap-card {
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: color-mix(in srgb, var(--el-fill-color-light) 55%, var(--el-bg-color));
}

.disk-cap-card header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.disk-cap-card header strong {
  font-size: 13px;
  font-weight: 650;
}

.disk-cap-card header span {
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  font-weight: 650;
}

.disk-line {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}

.disk-path {
  margin: 2px 0 0;
  font-size: 12px;
  word-break: break-all;
  color: var(--el-text-color-regular);
}

.disk-muted {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.45;
}

.disk-err {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--el-color-danger);
}

.disk-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 20px;
  padding: 20px 22px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.disk-form {
  max-width: 640px;
}

.disk-unit {
  margin-left: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.disk-aside h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.disk-aside ul {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 1100px) {
  .disk-db-row,
  .disk-path-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .disk-panel {
    grid-template-columns: 1fr;
  }
}
</style>
